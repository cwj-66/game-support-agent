"""云端与下游调用保护：错误分类、有限退避重试（尊重 Retry-After）、按依赖熔断。

决策：重试只发生在调用的最内层一次（Qwen / 检索 HTTP），图节点和 MCP 工具层不再重试，避免多层相乘。
"""

from __future__ import annotations

import asyncio
import logging
import random
import time
from dataclasses import dataclass
from typing import Awaitable, Callable, Optional, TypeVar

from app.core.config import get_settings

logger = logging.getLogger(__name__)
T = TypeVar("T")

_RETRYABLE_STATUS = {408, 429, 500, 502, 503, 504}
_NON_RETRYABLE_HINTS = ("insufficient_quota", "arrearage", "balance", "quota", "余额", "欠费", "data_inspection")


class UpstreamUnavailable(RuntimeError):
    """依赖已熔断或重试后仍失败；message 只含依赖名，不含下游返回内容。"""

    def __init__(self, dependency: str, retry_after: float | None = None) -> None:
        super().__init__(f"{dependency} unavailable")
        self.dependency = dependency
        self.retry_after = retry_after


@dataclass
class Failure:
    retryable: bool
    status: Optional[int]
    retry_after: Optional[float]
    trips_breaker: bool  # 是否计入熔断（参数错误不计，鉴权/余额/超时/5xx 计入）


def _retry_after(headers) -> Optional[float]:
    if not headers:
        return None
    value = headers.get("retry-after") or headers.get("Retry-After")
    try:
        return max(0.0, float(value)) if value is not None else None
    except (TypeError, ValueError):
        return None


def classify(exc: BaseException) -> Failure:
    """把 openai / httpx / 超时异常归类为可重试或不可重试。"""
    import httpx

    try:
        import openai
    except ImportError:  # pragma: no cover
        openai = None

    if isinstance(exc, (asyncio.TimeoutError, TimeoutError)):
        return Failure(True, None, None, True)
    if openai is not None:
        if isinstance(exc, (openai.APITimeoutError, openai.APIConnectionError)):
            return Failure(True, None, None, True)
        if isinstance(exc, openai.APIStatusError):
            return _classify_status(exc.status_code, getattr(exc.response, "headers", None), str(getattr(exc, "body", "") or exc))
    if isinstance(exc, (httpx.TimeoutException, httpx.NetworkError, httpx.RemoteProtocolError)):
        return Failure(True, None, None, True)
    if isinstance(exc, httpx.HTTPStatusError):
        return _classify_status(exc.response.status_code, exc.response.headers, "")
    return Failure(False, None, None, False)


def _classify_status(status: int, headers, body: str) -> Failure:
    text = (body or "").lower()
    if any(hint in text for hint in _NON_RETRYABLE_HINTS):
        return Failure(False, status, None, True)
    if status in _RETRYABLE_STATUS:
        return Failure(True, status, _retry_after(headers), True)
    return Failure(False, status, None, status in (401, 402, 403))


class CircuitBreaker:
    """进程内熔断器：窗口内失败达到阈值后打开，冷却后仅放行一个探测请求。"""

    def __init__(self, name: str) -> None:
        self.name = name
        self._failures: list[float] = []
        self._opened_at: Optional[float] = None
        self._probe_in_flight = False

    def _cfg(self):
        s = get_settings()
        return s.BREAKER_FAILURE_THRESHOLD, s.BREAKER_WINDOW_SECONDS, s.BREAKER_OPEN_SECONDS

    @property
    def state(self) -> str:
        if self._opened_at is None:
            return "closed"
        _, _, open_seconds = self._cfg()
        return "half_open" if time.monotonic() - self._opened_at >= open_seconds else "open"

    def before_call(self) -> bool:
        """返回本次是否为半开探测；熔断打开时抛 UpstreamUnavailable。"""
        state = self.state
        if state == "closed":
            return False
        _, _, open_seconds = self._cfg()
        if state == "open" or self._probe_in_flight:
            remaining = open_seconds - (time.monotonic() - self._opened_at)
            raise UpstreamUnavailable(self.name, retry_after=max(1.0, remaining))
        self._probe_in_flight = True
        return True

    def record_success(self, probe: bool) -> None:
        if probe or self._opened_at is not None:
            logger.info("circuit %s closed after successful probe", self.name)
        self._failures.clear()
        self._opened_at = None
        self._probe_in_flight = False

    def record_failure(self, probe: bool) -> None:
        threshold, window, _ = self._cfg()
        now = time.monotonic()
        if probe:
            self._opened_at = now
            self._probe_in_flight = False
            logger.warning("circuit %s probe failed; staying open", self.name)
            return
        self._failures = [t for t in self._failures if now - t < window] + [now]
        if len(self._failures) >= threshold and self._opened_at is None:
            self._opened_at = now
            logger.warning("circuit %s opened after %d failures in %.0fs", self.name, len(self._failures), window)

    def release_probe(self) -> None:
        self._probe_in_flight = False


_breakers: dict[str, CircuitBreaker] = {}


def breaker(name: str) -> CircuitBreaker:
    if name not in _breakers:
        _breakers[name] = CircuitBreaker(name)
    return _breakers[name]


def breaker_states() -> dict[str, str]:
    return {name: b.state for name, b in _breakers.items()}


async def guarded_call(
    dependency: str,
    call: Callable[[], Awaitable[T]],
    *,
    retries: Optional[int] = None,
    can_retry: Callable[[], bool] = lambda: True,
) -> T:
    """熔断 + 有限重试执行一次下游调用。

    Args:
        dependency: 依赖名（日志与熔断键），如 qwen / rag / mcp。
        call: 无参协程工厂，每次重试重新创建请求。
        retries: 最大重试次数，默认 UPSTREAM_MAX_RETRIES。
        can_retry: 返回 False 时不再重试（例如流式已向客户端输出内容）。

    Returns:
        call 的返回值。不可重试错误原样抛出；可重试错误耗尽后抛 UpstreamUnavailable。
    """
    s = get_settings()
    max_retries = s.UPSTREAM_MAX_RETRIES if retries is None else retries
    cb = breaker(dependency)
    attempt = 0
    while True:
        probe = cb.before_call()
        start = time.perf_counter()
        try:
            result = await call()
        except asyncio.CancelledError:
            if probe:
                cb.release_probe()
            raise
        except Exception as exc:
            failure = classify(exc)
            elapsed = int((time.perf_counter() - start) * 1000)
            logger.warning("upstream %s failed: type=%s status=%s retryable=%s elapsed_ms=%d attempt=%d",
                           dependency, type(exc).__name__, failure.status, failure.retryable, elapsed, attempt)
            if failure.trips_breaker:
                cb.record_failure(probe)
            elif probe:
                cb.release_probe()
            if not failure.retryable:
                raise
            if attempt >= max_retries or not can_retry() or cb.state != "closed":
                raise UpstreamUnavailable(dependency, failure.retry_after) from exc
            delay = failure.retry_after if failure.retry_after is not None else 0.3 * (2 ** attempt) + random.uniform(0, 0.2)
            if delay > s.UPSTREAM_RETRY_MAX_WAIT_SECONDS:
                raise UpstreamUnavailable(dependency, failure.retry_after) from exc
            attempt += 1
            await asyncio.sleep(delay)
            continue
        cb.record_success(probe)
        return result
