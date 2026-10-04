"""同一会话的跨进程写锁：同一 session_id 同时只允许一个请求修改对话状态。

锁按 session_id 加，不按玩家 UID；不同访客即使选择同一个测试 UID，会话号也不同，互不阻塞。
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
import uuid
from typing import AsyncIterator, Callable, Optional

from app.core.config import get_settings
from app.core.exceptions import CapacityUnavailableException, SessionBusyException
from app.services.coordination import CoordinationUnavailable, get_coordination

logger = logging.getLogger(__name__)

_CANCEL_CHECK_SECONDS = 1.0


def _lock_key(session_id: str) -> str:
    return f"gsa:session-lock:{session_id}"


def _cancel_key(session_id: str) -> str:
    return f"gsa:session-cancel:{session_id}"


class SessionGuard:
    """持有中的会话锁：后台续租，并监听「结束对话」发出的取消标记。"""

    def __init__(self, session_id: str, max_hold_seconds: float) -> None:
        self.session_id = session_id
        self.key = _lock_key(session_id)
        self.token = uuid.uuid4().hex
        self._max_hold = max_hold_seconds
        self._on_cancel: Optional[Callable[[], object]] = None
        self._task: Optional[asyncio.Task] = None
        self._released = False
        self.cancel_requested = False  # 排队阶段据此退出；执行阶段由 _on_cancel 取消任务

    def bind_cancel(self, callback: Callable[[], object]) -> None:
        """登记收到取消标记时的回调（通常是取消正在执行的 Agent 任务）。"""
        self._on_cancel = callback
        if self.cancel_requested:
            callback()

    def start(self) -> None:
        self._task = asyncio.create_task(self._keepalive())

    async def _keepalive(self) -> None:
        backend = get_coordination()
        ttl = get_settings().SESSION_LOCK_TTL_SECONDS
        stop_at = time.monotonic() + self._max_hold
        last_renew = time.monotonic()
        while time.monotonic() < stop_at:
            await asyncio.sleep(_CANCEL_CHECK_SECONDS)
            try:
                if not self.cancel_requested and await backend.has_flag(_cancel_key(self.session_id)):
                    logger.info("session %s cancelled by another request", self.session_id)
                    self.cancel_requested = True
                    if self._on_cancel:
                        self._on_cancel()
                if time.monotonic() - last_renew >= ttl / 3:
                    last_renew = time.monotonic()
                    if not await backend.lock_renew(self.key, self.token, int(ttl * 1000)):
                        logger.warning("session lock for %s lost before release", self.session_id)
                        self.cancel_requested = True
                        if self._on_cancel:
                            self._on_cancel()
                        return
            except CoordinationUnavailable:
                logger.warning("session lock keepalive failed for %s", self.session_id)
                self.cancel_requested = True
                if self._on_cancel:
                    self._on_cancel()
                return
        logger.warning("session lock for %s exceeded max hold; letting it expire", self.session_id)

    async def release(self) -> None:
        """只删除自己持有的锁（token 比对），可重复调用。"""
        if self._released:
            return
        self._released = True
        if self._task is not None:
            self._task.cancel()
        try:
            await get_coordination().lock_release(self.key, self.token)
        except CoordinationUnavailable:
            logger.warning("session lock release failed for %s; it expires by TTL", self.session_id)


def _default_max_hold() -> float:
    s = get_settings()
    return s.AGENT_QUEUE_TIMEOUT_SECONDS + s.AGENT_EXEC_TIMEOUT_SECONDS + s.SESSION_LOCK_TTL_SECONDS


async def acquire_session_lock(session_id: str, wait_seconds: Optional[float] = None) -> SessionGuard:
    """获取会话锁；等待超时抛 409 session_busy，Redis 不可用抛 503（不静默放行）。"""
    s = get_settings()
    wait = s.SESSION_LOCK_WAIT_SECONDS if wait_seconds is None else wait_seconds
    guard = SessionGuard(session_id, _default_max_hold())
    deadline = time.monotonic() + wait
    backend = get_coordination()
    while True:
        try:
            if await backend.lock_acquire(guard.key, guard.token, int(s.SESSION_LOCK_TTL_SECONDS * 1000)):
                guard.start()
                return guard
        except CoordinationUnavailable:
            logger.error("session lock backend unavailable; rejecting state change")
            raise CapacityUnavailableException()
        if time.monotonic() >= deadline:
            raise SessionBusyException()
        await asyncio.sleep(0.1)


async def try_session_lock(session_id: str) -> Optional[SessionGuard]:
    """非阻塞尝试获取锁；忙或不可用时返回 None（用于空闲自动关闭等可跳过的后台写入）。"""
    try:
        return await acquire_session_lock(session_id, wait_seconds=0)
    except (SessionBusyException, CapacityUnavailableException):
        return None


@contextlib.asynccontextmanager
async def session_guard(session_id: str, wait_seconds: Optional[float] = None) -> AsyncIterator[SessionGuard]:
    """短写入使用的锁上下文。"""
    guard = await acquire_session_lock(session_id, wait_seconds)
    try:
        yield guard
    finally:
        await guard.release()


async def request_cancel(session_id: str, ttl_seconds: float = 15) -> None:
    """通知正在执行的本会话请求尽快退出（结束对话使用）。"""
    try:
        await get_coordination().set_flag(_cancel_key(session_id), int(ttl_seconds * 1000))
    except CoordinationUnavailable:
        raise CapacityUnavailableException()


async def clear_cancel(session_id: str) -> None:
    try:
        await get_coordination().delete(_cancel_key(session_id))
    except CoordinationUnavailable:
        logger.warning("failed to clear cancel flag for %s", session_id)
