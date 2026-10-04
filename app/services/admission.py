"""全站问答容量控制：Redis 租约 + 有界 FIFO 排队，覆盖完整 Agent 执行周期。"""

from __future__ import annotations

import asyncio
import logging
import os
import socket
import time
import uuid
from typing import Awaitable, Callable, Optional

from app.core.config import get_settings
from app.core.exceptions import (
    CapacityUnavailableException,
    QueueTimeoutException,
    ServerBusyException,
    TurnCancelledException,
)
from app.services.coordination import CoordinationUnavailable, get_coordination

logger = logging.getLogger(__name__)

_WORKER_ID = f"{socket.gethostname()}:{os.getpid()}"
_held: set["AdmissionTicket"] = set()  # 本进程持有或排队中的票据，进程退出时统一释放


class AdmissionTicket:
    """一次问答的容量票据：attempt() 尝试入场，wait() 排队，release() 释放（幂等）。

    member 含随机 token，只有持有者能释放自己的名额，避免误删他人租约。
    """

    def __init__(self) -> None:
        self.member = f"{_WORKER_ID}:{uuid.uuid4().hex}"
        self.admitted = False
        self.position: Optional[int] = None
        self._created = time.monotonic()
        self._renew_task: Optional[asyncio.Task] = None
        self._released = False
        _held.add(self)

    @staticmethod
    def _params() -> dict:
        s = get_settings()
        return {
            "lease_ms": int(s.AGENT_LEASE_SECONDS * 1000),
            "max_active": s.AGENT_MAX_CONCURRENCY,
            "max_queue": s.AGENT_MAX_QUEUE,
            # 排队者心跳过期时间：至少覆盖数次轮询，进程崩溃后等待记录会被自动清除
            "heartbeat_ms": int(max(s.AGENT_QUEUE_POLL_SECONDS * 6, 5) * 1000),
        }

    @property
    def queue_deadline(self) -> float:
        return self._created + get_settings().AGENT_QUEUE_TIMEOUT_SECONDS

    async def attempt(self) -> bool:
        """原子尝试一次入场；队列已满抛 ServerBusy，协调存储不可用抛 CapacityUnavailable。"""
        if self.admitted:
            return True
        try:
            status, position = await get_coordination().admit(self.member, **self._params())
        except CoordinationUnavailable:
            logger.error("capacity backend unavailable; rejecting new turn")
            await self.release()
            raise CapacityUnavailableException()
        if status == -1:
            await self.release()
            raise ServerBusyException()
        if status == 1:
            self.admitted = True
            self.position = None
            self._renew_task = asyncio.create_task(self._renew_loop())
            return True
        self.position = position
        return False

    async def wait(
        self,
        on_position: Optional[Callable[[int], Awaitable[None]]] = None,
        cancelled: Callable[[], bool] = lambda: False,
    ) -> None:
        """排队直到入场；超时抛 QueueTimeout，cancelled() 为真时抛 TurnCancelled。"""
        last = None
        poll = get_settings().AGENT_QUEUE_POLL_SECONDS
        while not await self.attempt():
            if cancelled():
                await self.release()
                raise TurnCancelledException()
            if on_position and self.position != last:
                last = self.position
                await on_position(self.position)
            remaining = self.queue_deadline - time.monotonic()
            if remaining <= 0:
                await self.release()
                raise QueueTimeoutException()
            await asyncio.sleep(min(poll, remaining))

    async def _renew_loop(self) -> None:
        s = get_settings()
        interval = s.AGENT_LEASE_SECONDS / 3
        # 续租最多持续到执行上限 + 一个租约周期；即使释放路径异常，名额也会自然过期。
        stop_at = time.monotonic() + s.AGENT_EXEC_TIMEOUT_SECONDS + s.AGENT_LEASE_SECONDS
        params = self._params()
        while time.monotonic() < stop_at:
            await asyncio.sleep(interval)
            try:
                if not await get_coordination().renew_lease(self.member, params["lease_ms"], params["max_active"]):
                    logger.warning("capacity lease lost and slots full; turn continues until exec timeout")
            except CoordinationUnavailable:
                logger.warning("capacity lease renew failed (redis unavailable)")

    async def release(self) -> None:
        """释放名额与等待记录；只删除自己的 member，可重复调用。"""
        if self._released:
            return
        self._released = True
        _held.discard(self)
        if self._renew_task is not None:
            self._renew_task.cancel()
        try:
            await get_coordination().release_lease(self.member)
        except CoordinationUnavailable:
            logger.warning("capacity release failed; lease will expire after AGENT_LEASE_SECONDS")


async def release_all_held() -> None:
    """进程退出时释放本进程仍持有的名额与排队记录。"""
    for ticket in list(_held):
        await ticket.release()


async def capacity_snapshot() -> dict:
    """当前执行中与排队数量（健康检查用）。"""
    try:
        active, waiting = await get_coordination().capacity_snapshot()
    except CoordinationUnavailable:
        return {"status": "unavailable"}
    s = get_settings()
    return {"status": "ok", "active": active, "waiting": waiting,
            "max_active": s.AGENT_MAX_CONCURRENCY, "max_queue": s.AGENT_MAX_QUEUE}
