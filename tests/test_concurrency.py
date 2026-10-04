"""并发保护测试：全站容量、会话锁、频率限制、幂等、流式清理、超时与熔断。

协调后端同时覆盖 memory 与 Redis Lua 脚本（fakeredis + lupa 执行真实脚本）。
"""

import asyncio
import contextlib
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from app.core.config import get_settings
from app.core.exceptions import (
    AgentTimeoutException,
    CapacityUnavailableException,
    QueueTimeoutException,
    RateLimitedException,
    ServerBusyException,
    SessionBusyException,
)
from app.services import coordination
from app.services.admission import AdmissionTicket, capacity_snapshot
from app.services.session_lock import acquire_session_lock, request_cancel
from tests.conftest import make_request

try:
    import fakeredis
    import lupa  # noqa: F401
except ImportError:  # pragma: no cover
    fakeredis = None

pytestmark = pytest.mark.asyncio


@pytest.fixture
def cfg():
    """临时修改配置，用例结束后恢复。"""
    settings = get_settings()
    original = {}

    def set_(**values):
        for key, value in values.items():
            original.setdefault(key, getattr(settings, key))
            setattr(settings, key, value)

    yield set_
    for key, value in original.items():
        setattr(settings, key, value)


@pytest.fixture(params=["memory", "redis"])
def backend(request):
    if request.param == "redis":
        if fakeredis is None:
            pytest.skip("fakeredis[lua] not installed")
        impl = coordination.RedisCoordination(fakeredis.FakeAsyncRedis(decode_responses=True))
    else:
        impl = coordination.MemoryCoordination()
    coordination.set_coordination(impl)
    return impl


# --- 全站容量 ---

async def test_capacity_admits_three_then_queues_then_rejects(backend, cfg):
    cfg(AGENT_MAX_CONCURRENCY=3, AGENT_MAX_QUEUE=2)
    tickets = [AdmissionTicket() for _ in range(5)]
    results = [await t.attempt() for t in tickets]
    assert results == [True, True, True, False, False]
    assert [t.position for t in tickets[3:]] == [1, 2]
    with pytest.raises(ServerBusyException) as exc:
        await AdmissionTicket().attempt()
    assert exc.value.headers["Retry-After"]
    assert await capacity_snapshot() == {"status": "ok", "active": 3, "waiting": 2, "max_active": 3, "max_queue": 2}

    await tickets[0].release()
    assert await tickets[4].attempt() is False, "队尾不能插队"
    assert await tickets[3].attempt() is True
    for t in tickets:
        await t.release()
    assert (await capacity_snapshot())["active"] == 0


async def test_queue_timeout_removes_wait_record(backend, cfg):
    cfg(AGENT_MAX_CONCURRENCY=1, AGENT_MAX_QUEUE=5, AGENT_QUEUE_TIMEOUT_SECONDS=0.3, AGENT_QUEUE_POLL_SECONDS=0.05)
    holder = AdmissionTicket()
    assert await holder.attempt()
    waiter = AdmissionTicket()
    with pytest.raises(QueueTimeoutException):
        await waiter.wait()
    assert (await capacity_snapshot())["waiting"] == 0
    await holder.release()


async def test_expired_lease_is_reclaimed_and_release_checks_owner(backend, cfg):
    cfg(AGENT_MAX_CONCURRENCY=1, AGENT_LEASE_SECONDS=0.2)
    crashed = AdmissionTicket()
    assert await crashed.attempt()
    crashed._renew_task.cancel()  # 模拟进程崩溃：不再续租，也不释放
    assert await backend.release_lease("someone-else:token") is False
    assert (await capacity_snapshot())["active"] == 1
    await asyncio.sleep(0.3)
    nxt = AdmissionTicket()
    assert await nxt.attempt(), "过期租约应被回收"
    await crashed.release()  # 迟到的释放不能删掉别人的名额
    assert (await capacity_snapshot())["active"] == 1
    await nxt.release()


async def test_lease_renewal_keeps_slot(backend, cfg):
    cfg(AGENT_MAX_CONCURRENCY=1, AGENT_LEASE_SECONDS=0.3)
    holder = AdmissionTicket()
    assert await holder.attempt()
    await asyncio.sleep(0.5)
    assert await AdmissionTicket().attempt() is False
    await holder.release()


async def test_abandoned_waiter_expires(backend, cfg):
    cfg(AGENT_MAX_CONCURRENCY=1, AGENT_MAX_QUEUE=1, AGENT_QUEUE_POLL_SECONDS=0.05)
    holder = AdmissionTicket()
    await holder.attempt()
    ghost = AdmissionTicket()
    assert await ghost.attempt() is False
    with pytest.raises(ServerBusyException):
        await AdmissionTicket().attempt()
    with patch.object(AdmissionTicket, "_params", return_value={
        "lease_ms": 30000, "max_active": 1, "max_queue": 1, "heartbeat_ms": 100,
    }):
        assert await ghost.attempt() is False  # 刷新为短心跳后不再轮询
        await asyncio.sleep(0.2)
        assert await AdmissionTicket().attempt() is False, "过期等待记录被清除后可以入队"
    await holder.release()


async def test_backend_failure_rejects_instead_of_unlimited(cfg):
    class Broken:
        async def eval(self, *a, **k):
            raise ConnectionError("down")

        def register_script(self, src):
            async def run(keys=None, args=None):
                raise ConnectionError("down")
            return run

        async def set(self, *a, **k):
            raise ConnectionError("down")

    coordination.set_coordination(coordination.RedisCoordination(Broken()))
    with pytest.raises(CapacityUnavailableException):
        await AdmissionTicket().attempt()
    with pytest.raises(CapacityUnavailableException):
        await acquire_session_lock("u_1")


# --- 会话锁 ---

async def test_session_lock_is_exclusive_and_owned(backend, cfg):
    cfg(SESSION_LOCK_TTL_SECONDS=0.3)
    first = await acquire_session_lock("10001_a", wait_seconds=0)
    with pytest.raises(SessionBusyException):
        await acquire_session_lock("10001_a", wait_seconds=0)
    other = await acquire_session_lock("10001_b", wait_seconds=0)  # 同 UID 不同会话互不阻塞
    assert await backend.lock_release(first.key, "wrong-token") is False
    await first.release()
    again = await acquire_session_lock("10001_a", wait_seconds=0)
    await again.release()
    await other.release()


async def test_session_lock_expires_when_holder_dies(backend, cfg):
    cfg(SESSION_LOCK_TTL_SECONDS=0.2)
    dead = await acquire_session_lock("u_dead", wait_seconds=0)
    dead._task.cancel()
    await asyncio.sleep(0.3)
    alive = await acquire_session_lock("u_dead", wait_seconds=0)
    await dead.release()  # token 不匹配，不会删除新持有者的锁
    with pytest.raises(SessionBusyException):
        await acquire_session_lock("u_dead", wait_seconds=0)
    await alive.release()


# --- 频率限制与真实 IP ---

async def test_rate_limit_per_visitor_and_ip(backend, cfg):
    from app.services.rate_limit import enforce_chat_rate

    cfg(CHAT_RATE_LIMIT_PER_MINUTE=3, CHAT_RATE_LIMIT_PER_IP_PER_MINUTE=5)
    for _ in range(3):
        await enforce_chat_rate(make_request(visitor="a" * 32))
    with pytest.raises(RateLimitedException) as exc:
        await enforce_chat_rate(make_request(visitor="a" * 32))
    assert exc.value.status_code == 429 and 1 <= int(exc.value.headers["Retry-After"]) <= 60
    await enforce_chat_rate(make_request(visitor="b" * 32))
    await enforce_chat_rate(make_request(visitor="c" * 32))
    with pytest.raises(RateLimitedException):
        await enforce_chat_rate(make_request(visitor="d" * 32))  # 清 cookie 绕过被 IP 上限拦下
    await enforce_chat_rate(make_request(ip="198.51.100.7", visitor="e" * 32))


async def test_client_ip_trusts_only_proxy_chain():
    from app.core.client_ip import client_ip

    spoof = {"X-Forwarded-For": "1.1.1.1"}
    assert client_ip(make_request(ip="203.0.113.5", headers=spoof)) == "203.0.113.5"
    chain = {"X-Forwarded-For": "6.6.6.6, 203.0.113.9, 172.18.0.1"}
    assert client_ip(make_request(ip="172.18.0.5", headers=chain)) == "203.0.113.9"
    assert client_ip(make_request(ip="127.0.0.1", headers={"X-Forwarded-For": "198.51.100.2"})) == "198.51.100.2"
    assert client_ip(make_request(ip="127.0.0.1")) == "127.0.0.1"


# --- 接口级：幂等与同会话并发 ---

def _agent_result(text="好的"):
    return {"final_response": text, "metadata": {}, "tool_calls": []}


async def test_send_idempotent_retry_runs_agent_once(backend):
    from app.api.deps import CurrentPlayer
    from app.api.v1.chat import send_message
    from app.models.chat import ChatRequest

    run = AsyncMock(return_value=_agent_result("首次结果"))
    body = ChatRequest(session_id="p1_s1", message="hi", client_request_id="req-00000001")
    with patch("app.api.v1.chat._human_mode_active", new=AsyncMock(return_value=False)), \
         patch("app.api.v1.chat.run_agent", new=run):
        first = await send_message(body, make_request(), CurrentPlayer(user_id="p1"))
        second = await send_message(body, make_request(), CurrentPlayer(user_id="p1"))
    assert run.await_count == 1
    assert first.response == second.response == "首次结果"


async def test_concurrent_send_same_session_gets_409(backend, cfg):
    from app.api.deps import CurrentPlayer
    from app.api.v1.chat import send_message
    from app.models.chat import ChatRequest

    cfg(SESSION_LOCK_WAIT_SECONDS=0)
    gate = asyncio.Event()

    async def slow(**kwargs):
        await gate.wait()
        return _agent_result()

    with patch("app.api.v1.chat._human_mode_active", new=AsyncMock(return_value=False)), \
         patch("app.api.v1.chat.run_agent", new=slow):
        task = asyncio.create_task(send_message(ChatRequest(session_id="p1_s", message="a"), make_request(), CurrentPlayer(user_id="p1")))
        await asyncio.sleep(0.05)
        with pytest.raises(SessionBusyException):
            await send_message(ChatRequest(session_id="p1_s", message="b"), make_request(visitor="f" * 32), CurrentPlayer(user_id="p1"))
        gate.set()
        await task
    assert (await capacity_snapshot())["active"] == 0


async def test_double_ticket_confirm_creates_one_ticket(backend):
    from app.api.deps import CurrentPlayer
    from app.api.v1.chat import TicketConfirmRequest, confirm_ticket_offer

    state = {"ticket_offer": {"issue_type": "payment", "summary": "未到账"}, "tool_calls": []}

    async def get_tuple(config):
        return SimpleNamespace(checkpoint={"channel_values": dict(state)})

    async def write_state(session_id, messages, extra_state=None):
        await asyncio.sleep(0.05)
        state.update(extra_state or {})

    async def reply(session_id, content, **extra):
        state.update(extra)

    create = patch("app.services.ticket_service.create_ticket_core", return_value={
        "status": "submitted", "ticket_id": "TK-1", "estimated_response": "1 天"})
    with patch("app.api.v1.chat.get_checkpointer", new=AsyncMock(return_value=SimpleNamespace(aget_tuple=get_tuple))), \
         patch("app.core.checkpoint_helper.append_session_messages", new=write_state), \
         patch("app.core.checkpoint_helper.append_agent_reply", new=reply), create as created:
        results = await asyncio.gather(*[
            confirm_ticket_offer(TicketConfirmRequest(session_id="p1_t", confirmed=True), CurrentPlayer(user_id="p1"))
            for _ in range(2)
        ], return_exceptions=True)
    assert created.call_count == 1
    outcomes = {str(getattr(r, "status", None) or getattr(r, "status_code", None)) for r in results}
    assert "created" in outcomes and outcomes & {"400", "409"}


# --- 流式：排队事件、心跳、断开清理、中断不重放 ---

async def _collect(gen, limit=None):
    frames = []
    async for frame in gen:
        frames.append(frame)
        if limit and len(frames) >= limit:
            break
    return frames


def _events(frames):
    return [json.loads(f[6:]) for f in frames if f.startswith("data: ")]


def _turn(session_id, ticket, agent_events, guard):
    from app.services.turn_runner import StreamTurn

    async def on_done(payload):
        return None

    return StreamTurn(guard, ticket, agent_events=agent_events, direct=None, on_done=on_done)


async def test_stream_reports_queue_then_runs_with_heartbeats(backend, cfg):
    cfg(AGENT_MAX_CONCURRENCY=1, AGENT_QUEUE_POLL_SECONDS=0.02, SSE_HEARTBEAT_SECONDS=0.05)
    holder = AdmissionTicket()
    await holder.attempt()

    async def agent():
        yield {"type": "stage", "name": "reasoning", "status": "running"}
        await asyncio.sleep(0.12)
        yield {"type": "delta", "text": "你好"}
        yield {"type": "done", "status": "ok", "response": "你好"}

    ticket = AdmissionTicket()
    assert await ticket.attempt() is False
    guard = await acquire_session_lock("p_stream", wait_seconds=0)
    turn = _turn("p_stream", ticket, agent, guard)
    asyncio.get_running_loop().call_later(0.15, lambda: asyncio.ensure_future(holder.release()))
    frames = await _collect(turn.events())
    events = _events(frames)
    assert events[0] == {"type": "queue", "status": "queued", "position": 1}
    assert {"type": "queue", "status": "admitted"} in events
    admitted = events.index({"type": "queue", "status": "admitted"})
    assert all(e["type"] == "queue" for e in events[:admitted]), "排队期间不能出现执行步骤"
    assert ": ping\n\n" in frames
    assert events[-1]["type"] == "done"
    assert (await capacity_snapshot())["active"] == 0
    (await acquire_session_lock("p_stream", wait_seconds=0)).start  # 锁已释放


async def test_stream_client_disconnect_cancels_agent_and_releases(backend):
    cancelled = asyncio.Event()

    async def agent():
        yield {"type": "stage", "name": "reasoning", "status": "running"}
        try:
            await asyncio.sleep(10)
        except asyncio.CancelledError:
            cancelled.set()
            raise
        yield {"type": "done"}

    ticket = AdmissionTicket()
    await ticket.attempt()
    guard = await acquire_session_lock("p_disc", wait_seconds=0)
    gen = _turn("p_disc", ticket, agent, guard).events()
    await _collect(gen, limit=2)
    assert (await capacity_snapshot())["active"] == 1
    await gen.aclose()  # 客户端断开
    assert cancelled.is_set()
    assert (await capacity_snapshot())["active"] == 0
    lock = await acquire_session_lock("p_disc", wait_seconds=0)
    await lock.release()


async def test_stream_failure_after_delta_is_not_replayed(backend):
    calls = 0

    async def agent():
        nonlocal calls
        calls += 1
        yield {"type": "delta", "text": "前半句"}
        raise httpx.ReadTimeout("slow")

    ticket = AdmissionTicket()
    await ticket.attempt()
    guard = await acquire_session_lock("p_part", wait_seconds=0)
    events = _events(await _collect(_turn("p_part", ticket, agent, guard).events()))
    assert calls == 1
    assert [e["type"] for e in events] == ["queue", "delta", "error"]
    assert events[-1]["code"] == "stream_interrupted" and events[-1]["partial"] is True
    assert "slow" not in json.dumps(events, ensure_ascii=False)


async def test_end_conversation_cancels_running_stream(backend):
    from app.api.deps import CurrentPlayer
    from app.api.v1.chat import EndConversationRequest, end_conversation

    async def agent():
        yield {"type": "stage", "name": "reasoning", "status": "running"}
        await asyncio.sleep(10)
        yield {"type": "done"}

    ticket = AdmissionTicket()
    await ticket.attempt()
    guard = await acquire_session_lock("p1_end", wait_seconds=0)
    gen = _turn("p1_end", ticket, agent, guard).events()
    consumer = asyncio.create_task(_collect(gen))
    await asyncio.sleep(0.05)
    with patch("app.api.v1.chat._human_mode_active", new=AsyncMock(return_value=False)):
        result = await end_conversation(EndConversationRequest(session_id="p1_end"), CurrentPlayer(user_id="p1"))
    assert result["status"] == "ended"
    events = _events(await consumer)
    assert events[-1]["code"] == "turn_cancelled"
    assert (await capacity_snapshot())["active"] == 0


# --- 执行时限与云端重试/熔断 ---

async def test_execution_deadline_cancels_task(cfg):
    from app.services.turn_runner import execute_with_deadline

    cfg(AGENT_EXEC_TIMEOUT_SECONDS=0.1)
    stopped = asyncio.Event()

    async def slow():
        try:
            await asyncio.sleep(5)
        finally:
            stopped.set()

    with pytest.raises(AgentTimeoutException):
        await execute_with_deadline(slow(), None)
    assert stopped.is_set(), "返回前任务必须已经结束"


def _status_error(status, headers=None):
    request = httpx.Request("POST", "http://mock/v1")
    response = httpx.Response(status, headers=headers or {}, request=request)
    return httpx.HTTPStatusError("x", request=request, response=response)


async def test_guarded_call_retries_once_and_respects_retry_after(cfg):
    from app.core.resilience import UpstreamUnavailable, guarded_call

    cfg(UPSTREAM_MAX_RETRIES=1, UPSTREAM_RETRY_MAX_WAIT_SECONDS=1)
    calls = []

    async def flaky():
        calls.append(1)
        if len(calls) == 1:
            raise _status_error(503, {"Retry-After": "0.05"})
        return "ok"

    assert await guarded_call("dep-a", flaky) == "ok" and len(calls) == 2

    async def always_429():
        calls.append(1)
        raise _status_error(429, {"Retry-After": "120"})

    calls.clear()
    with pytest.raises(UpstreamUnavailable):
        await guarded_call("dep-b", always_429)
    assert len(calls) == 1, "Retry-After 超过上限时不等待重试"


async def test_auth_errors_are_not_retried(cfg):
    from app.core.resilience import guarded_call

    calls = []

    async def unauthorized():
        calls.append(1)
        raise _status_error(401)

    with pytest.raises(httpx.HTTPStatusError):
        await guarded_call("dep-c", unauthorized)
    assert len(calls) == 1


async def test_breaker_opens_and_recovers_with_single_probe(cfg):
    from app.core.resilience import UpstreamUnavailable, breaker, guarded_call

    cfg(BREAKER_FAILURE_THRESHOLD=2, BREAKER_OPEN_SECONDS=0.1, UPSTREAM_MAX_RETRIES=0)

    async def down():
        raise httpx.ConnectError("refused")

    for _ in range(2):
        with pytest.raises(UpstreamUnavailable):
            await guarded_call("dep-d", down)
    assert breaker("dep-d").state == "open"
    called = []

    async def ok():
        called.append(1)
        return "ok"

    with pytest.raises(UpstreamUnavailable):
        await guarded_call("dep-d", ok)
    assert called == [], "熔断打开时不再调用下游"
    await asyncio.sleep(0.12)
    assert await guarded_call("dep-d", ok) == "ok"
    assert breaker("dep-d").state == "closed"


async def test_llm_stream_never_retries_after_output(cfg):
    from app.core.llm import llm_stream

    cfg(UPSTREAM_MAX_RETRIES=1)
    attempts = 0

    class Model:
        async def astream(self, messages):
            nonlocal attempts
            attempts += 1
            yield SimpleNamespace(content="部分")
            raise httpx.ReadTimeout("t")

    seen = []
    with pytest.raises(Exception):
        await llm_stream(Model(), [], seen.append)
    assert attempts == 1 and seen == ["部分"]


async def test_run_blocking_waits_for_thread_on_cancel():
    import threading
    import time as _time

    from app.core.blocking import run_blocking

    finished = threading.Event()

    def work():
        _time.sleep(0.2)
        finished.set()

    task = asyncio.create_task(run_blocking(work))
    await asyncio.sleep(0.05)
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task
    assert finished.is_set(), "取消返回时线程里的数据库操作必须已结束"


async def test_summaries_do_not_cross_visitors_with_same_uid(monkeypatch):
    from app.services import long_term_memory as memory
    monkeypatch.setattr(memory, "_memory", {})
    monkeypatch.setattr(memory, "_get_redis", AsyncMock(return_value=None))
    await memory.save_session_summary("10001", "访客 A 的问题", session_id="10001_visitor_a")
    assert await memory.get_recent_summaries("10001", session_id="10001_visitor_b") == []
    assert await memory.get_recent_summaries("10001") == []
    own = await memory.get_recent_summaries("10001", session_id="10001_visitor_a")
    assert own[0]["summary"] == "访客 A 的问题"


async def test_lost_session_lock_cancels_running_turn(backend, cfg):
    cfg(SESSION_LOCK_TTL_SECONDS=0.3)
    guard = await acquire_session_lock("10001_lost_lock")
    cancelled = asyncio.Event()
    guard.bind_cancel(cancelled.set)
    await backend.lock_release(guard.key, guard.token)
    await asyncio.wait_for(cancelled.wait(), timeout=2)
    assert guard.cancel_requested
    await guard.release()
