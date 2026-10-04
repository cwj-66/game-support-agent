"""问答执行编排：会话锁 → 全站容量排队 → 带整体时限的 Agent 执行 → 按顺序清理。

清理顺序固定为：取消并等待 Agent 任务真正结束 → 释放容量名额 → 释放会话锁。
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import time
from typing import Any, AsyncIterator, Awaitable, Callable, Optional

from app.core.config import get_settings
from app.core.exceptions import (
    AgentTimeoutException,
    AppException,
    QueueTimeoutException,
    TurnCancelledException,
    UpstreamUnavailableException,
)
from app.core.resilience import UpstreamUnavailable
from app.services.admission import AdmissionTicket
from app.services.session_lock import SessionGuard

logger = logging.getLogger(__name__)

HEARTBEAT = ": ping\n\n"
_END = object()
_WATCHDOG_SECONDS = 10
_background: set[asyncio.Task] = set()  # 持有清理任务引用，防止被 GC 提前回收


def sse(payload: dict) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False, default=str)}\n\n"


def to_app_exception(exc: BaseException) -> AppException:
    """把内部异常转换为面向玩家的错误，不携带异常细节。"""
    if isinstance(exc, AppException):
        return exc
    if isinstance(exc, UpstreamUnavailable):
        retry = int(exc.retry_after) if exc.retry_after else 30
        return UpstreamUnavailableException(retry_after=max(1, retry))
    return AppException(500, "agent_error", "本轮回复未能完成，请稍后重试。")


async def execute_with_deadline(coro: Awaitable[Any], guard: Optional[SessionGuard]) -> Any:
    """在整体时限内执行 Agent；超时或被「结束对话」取消时，等任务真正结束后再返回。"""
    task = asyncio.ensure_future(coro)
    if guard is not None:
        guard.bind_cancel(task.cancel)
    try:
        done, _ = await asyncio.wait({task}, timeout=get_settings().AGENT_EXEC_TIMEOUT_SECONDS)
        if not done:
            raise AgentTimeoutException()
        if task.cancelled():
            raise TurnCancelledException()
        return task.result()
    finally:
        if not task.done():
            task.cancel()
        while not task.done():
            try:
                await asyncio.wait({task})
            except asyncio.CancelledError:
                continue


class StreamTurn:
    """一次 SSE 问答。

    Args:
        guard: 已持有的会话锁。
        ticket: 已尝试过一次入场的容量票据；为 None 表示不需要模型（人工接待消息）。
        agent_events: 产生公开事件的 Agent 流（stage / tool / delta / done）。
        direct: 不经过模型的处理函数，返回 done 事件载荷。
        on_done: done 事件发出前的回调（保存幂等结果）。
    """

    def __init__(
        self,
        guard: SessionGuard,
        ticket: Optional[AdmissionTicket],
        *,
        agent_events: Optional[Callable[[], AsyncIterator[dict]]] = None,
        direct: Optional[Callable[[], Awaitable[dict]]] = None,
        on_done: Callable[[dict], Awaitable[None]],
    ) -> None:
        self.guard = guard
        self.ticket = ticket
        self._agent_events = agent_events
        self._direct = direct
        self._on_done = on_done
        self._queue: asyncio.Queue = asyncio.Queue()
        self._task: Optional[asyncio.Task] = None
        self._cleanup: Optional[asyncio.Task] = None
        self._started = False
        self._delta_sent = False
        self._watchdog: Optional[asyncio.TimerHandle] = None

    def arm_watchdog(self) -> None:
        """响应体迟迟未被读取（连接在开始前断开）时，主动释放锁与名额。"""
        loop = asyncio.get_running_loop()
        self._watchdog = loop.call_later(_WATCHDOG_SECONDS, self._on_watchdog)

    def _on_watchdog(self) -> None:
        if not self._started:
            logger.warning("stream for %s never started; releasing resources", self.guard.session_id)
            self.finalize()

    async def events(self) -> AsyncIterator[str]:
        self._started = True
        s = get_settings()
        try:
            if self.ticket is None:
                payload = await self._direct()
                await self._on_done(payload)
                yield sse(payload)
                return

            if not self.ticket.admitted:
                async for frame in self._wait_in_queue(s):
                    yield frame
            yield sse({"type": "queue", "status": "admitted"})

            deadline = time.monotonic() + s.AGENT_EXEC_TIMEOUT_SECONDS
            self._task = asyncio.create_task(self._produce())
            self.guard.bind_cancel(self._task.cancel)
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise AgentTimeoutException()
                try:
                    item = await asyncio.wait_for(self._queue.get(), timeout=min(s.SSE_HEARTBEAT_SECONDS, remaining))
                except asyncio.TimeoutError:
                    yield HEARTBEAT
                    continue
                if item is _END:
                    break
                yield sse(item)
        except AppException as exc:
            yield sse(exc.public_event())
        except Exception:
            logger.exception("stream turn failed for %s", self.guard.session_id)
            yield sse(to_app_exception(RuntimeError()).public_event())
        finally:
            cleanup = self.finalize()
            with contextlib.suppress(asyncio.CancelledError):
                await asyncio.shield(cleanup)

    async def _wait_in_queue(self, s) -> AsyncIterator[str]:
        """排队阶段：只发送真实的队列位置和心跳，不发送任何执行步骤。"""
        position = self.ticket.position
        yield sse({"type": "queue", "status": "queued", "position": position})
        last_beat = time.monotonic()
        while not await self.ticket.attempt():
            if self.guard.cancel_requested:
                raise TurnCancelledException()
            if self.ticket.position != position:
                position = self.ticket.position
                yield sse({"type": "queue", "status": "queued", "position": position})
            remaining = self.ticket.queue_deadline - time.monotonic()
            if remaining <= 0:
                raise QueueTimeoutException()
            if time.monotonic() - last_beat >= s.SSE_HEARTBEAT_SECONDS:
                last_beat = time.monotonic()
                yield HEARTBEAT
            await asyncio.sleep(min(s.AGENT_QUEUE_POLL_SECONDS, remaining))

    async def _produce(self) -> None:
        try:
            async for event in self._agent_events():
                if event.get("type") == "delta":
                    self._delta_sent = True
                if event.get("type") == "done":
                    await self._on_done(event)
                self._queue.put_nowait(event)
        except asyncio.CancelledError:
            self._queue.put_nowait(TurnCancelledException().public_event())
            raise
        except Exception as exc:
            logger.warning("agent stream failed for %s: %s", self.guard.session_id, type(exc).__name__)
            event = to_app_exception(exc).public_event()
            if self._delta_sent:
                # 已经输出过部分回复：明确标记中断，不自动从头重试，避免内容重复。
                event.update(code="stream_interrupted", partial=True, message="回复中断，请重新发送问题。")
            self._queue.put_nowait(event)
        finally:
            self._queue.put_nowait(_END)

    def finalize(self) -> asyncio.Task:
        """调度一次（且只一次）清理；返回清理任务，可等待其完成。"""
        if self._cleanup is None:
            self._cleanup = asyncio.ensure_future(self._do_cleanup())
            _background.add(self._cleanup)
            self._cleanup.add_done_callback(_background.discard)
        return self._cleanup

    async def _do_cleanup(self) -> None:
        if self._watchdog is not None:
            self._watchdog.cancel()
        task = self._task
        if task is not None and not task.done():
            task.cancel()
        if task is not None:
            await asyncio.wait({task})
        if self.ticket is not None:
            await self.ticket.release()
        await self.guard.release()
