"""模拟云端并发压测：在本进程内启动「可控延迟/错误的 OpenAI 兼容模拟服务」和 Agent API，
通过真实 HTTP + SSE 验证容量排队、会话锁、频率限制、重试熔断与断线清理。

不调用真实 Qwen / 硅基流动，不消耗 token。结果只代表本机模拟环境，不是生产容量保证。

用法：
    python scripts/load_test_mock.py                 # 全部场景，memory 协调后端
    python scripts/load_test_mock.py --redis-url redis://127.0.0.1:6380/0   # 使用真实 Redis
    python scripts/load_test_mock.py --scenarios burst,disconnect --delay 1.5
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import random
import secrets
import statistics
import sys
import tempfile
import time
from pathlib import Path
from fastapi import Request

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

MOCK_PORT = 18080
AGENT_PORT = 18002
RESULTS_PATH = ROOT / "deploy" / "vultr" / "concurrency-results.json"


# --- 模拟云端模型 ---

class MockState:
    """模拟服务的可调参数与观测值。"""

    delay = 1.0          # 每次模型调用耗时（秒）
    error_rate = 0.0     # 返回错误的概率
    error_status = 503
    retry_after = None   # 错误响应的 Retry-After
    in_flight = 0
    max_in_flight = 0
    calls = 0
    errors = 0


def build_mock_app():
    from fastapi import FastAPI
    from fastapi.responses import JSONResponse, StreamingResponse

    app = FastAPI()

    @app.post("/v1/chat/completions")
    async def completions(request: Request):
        body = await request.json()
        MockState.calls += 1
        MockState.in_flight += 1
        MockState.max_in_flight = max(MockState.max_in_flight, MockState.in_flight)
        try:
            if random.random() < MockState.error_rate:
                MockState.errors += 1
                await asyncio.sleep(0.05)
                headers = {"Retry-After": str(MockState.retry_after)} if MockState.retry_after is not None else {}
                return JSONResponse({"error": {"message": "mock upstream error"}}, status_code=MockState.error_status, headers=headers)
            text = "这是模拟客服回复，用于压测。"
            if body.get("stream"):
                async def chunks():
                    pieces = [text[i:i + 4] for i in range(0, len(text), 4)]
                    for piece in pieces:
                        await asyncio.sleep(MockState.delay / len(pieces))
                        yield "data: " + json.dumps({
                            "id": "mock", "object": "chat.completion.chunk", "created": 0, "model": body.get("model"),
                            "choices": [{"index": 0, "delta": {"content": piece}, "finish_reason": None}],
                        }, ensure_ascii=False) + "\n\n"
                    yield "data: " + json.dumps({
                        "id": "mock", "object": "chat.completion.chunk", "created": 0, "model": body.get("model"),
                        "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
                    }) + "\n\n"
                    yield "data: [DONE]\n\n"
                return StreamingResponse(chunks(), media_type="text/event-stream")
            await asyncio.sleep(MockState.delay)
            return {
                "id": "mock", "object": "chat.completion", "created": 0, "model": body.get("model"),
                "choices": [{"index": 0, "message": {"role": "assistant", "content": text}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            }
        finally:
            MockState.in_flight -= 1

    return app


# --- 资源观测（Windows 用 GetProcessMemoryInfo，其他平台用 resource）---

def peak_rss_mb() -> float | None:
    try:
        if sys.platform == "win32":
            import ctypes
            from ctypes import wintypes

            class PMC(ctypes.Structure):
                _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD),
                            ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
                            ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
                            ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t), ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                            ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t)]
            pmc = PMC()
            pmc.cb = ctypes.sizeof(PMC)
            ctypes.windll.kernel32.GetCurrentProcess.restype = wintypes.HANDLE
            ctypes.windll.psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(PMC), wintypes.DWORD]
            handle = ctypes.windll.kernel32.GetCurrentProcess()
            if not ctypes.windll.psapi.GetProcessMemoryInfo(handle, ctypes.byref(pmc), pmc.cb):
                return None
            return round(pmc.PeakWorkingSetSize / 1024 / 1024, 1)
        import resource
        return round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, 1)
    except Exception:
        return None


# --- 客户端 ---

class Visitor:
    """一个模拟访客：独立 cookie 与客户端 IP（经可信代理头传入）。"""

    def __init__(self, ip: str | None = None):
        self.cookie = secrets.token_hex(16)
        self.ip = ip or f"198.51.100.{random.randint(1, 250)}"

    def headers(self) -> dict:
        return {"Cookie": f"gsa_visitor={self.cookie}", "X-Forwarded-For": self.ip, "Content-Type": "application/json"}


async def stream_turn(client, visitor: Visitor, session_id: str, message: str = "测试问题",
                      cancel_after: float | None = None) -> dict:
    """发起一次 SSE 问答，记录 HTTP 状态、排队位置、首字节时间与最终结果。"""
    import httpx

    start = time.perf_counter()
    result = {"status": None, "outcome": None, "queued_position": None, "ttfb_ms": None, "total_ms": None, "heartbeats": 0}
    payload = {"session_id": session_id, "message": message, "client_request_id": secrets.token_hex(8)}
    try:
        async with client.stream("POST", f"http://127.0.0.1:{AGENT_PORT}/api/v1/chat/stream",
                                 json=payload, headers=visitor.headers(), timeout=200) as resp:
            result["status"] = resp.status_code
            if resp.status_code != 200:
                body = json.loads(await resp.aread() or b"{}")
                result["outcome"] = body.get("error_code") or f"http_{resp.status_code}"
                return result
            async def read():
                async for line in resp.aiter_lines():
                    if line.startswith(":"):
                        result["heartbeats"] += 1
                        continue
                    if not line.startswith("data: "):
                        continue
                    event = json.loads(line[6:])
                    if event["type"] == "queue" and event.get("status") == "queued" and result["queued_position"] is None:
                        result["queued_position"] = event.get("position")
                    if event["type"] == "delta" and result["ttfb_ms"] is None:
                        result["ttfb_ms"] = int((time.perf_counter() - start) * 1000)
                    if event["type"] == "done":
                        result["outcome"] = "ok"
                    if event["type"] == "error":
                        result["outcome"] = event.get("code")
            if cancel_after is not None:
                try:
                    await asyncio.wait_for(read(), cancel_after)
                except asyncio.TimeoutError:
                    result["outcome"] = "client_cancelled"
            else:
                await read()
    except httpx.HTTPError as exc:
        result["outcome"] = f"client_error:{type(exc).__name__}"
    finally:
        result["total_ms"] = int((time.perf_counter() - start) * 1000)
    return result


def summarize(results: list[dict]) -> dict:
    outcomes: dict[str, int] = {}
    for r in results:
        outcomes[r["outcome"] or "unknown"] = outcomes.get(r["outcome"] or "unknown", 0) + 1
    ok = [r["total_ms"] for r in results if r["outcome"] == "ok"]

    def pct(values, p):
        if not values:
            return None
        values = sorted(values)
        return values[min(len(values) - 1, int(round(p / 100 * (len(values) - 1))))]

    return {
        "requests": len(results),
        "outcomes": outcomes,
        "success_rate": round(len(ok) / len(results), 3) if results else None,
        "latency_ms_ok": {"p50": pct(ok, 50), "p95": pct(ok, 95), "max": max(ok) if ok else None,
                           "mean": int(statistics.mean(ok)) if ok else None},
        "queued": sum(1 for r in results if r["queued_position"]),
        "max_queue_position": max([r["queued_position"] or 0 for r in results] or [0]),
        "heartbeats": sum(r["heartbeats"] for r in results),
    }


class CapacityProbe:
    """每 100ms 读取进程内容量快照，记录执行中与排队数的峰值。"""

    def __init__(self):
        self.max_active = 0
        self.max_waiting = 0
        self._task = None

    async def _run(self):
        from app.services.admission import capacity_snapshot
        while True:
            snap = await capacity_snapshot()
            if snap.get("status") == "ok":
                self.max_active = max(self.max_active, snap["active"])
                self.max_waiting = max(self.max_waiting, snap["waiting"])
            await asyncio.sleep(0.1)

    def __enter__(self):
        self._task = asyncio.create_task(self._run())
        return self

    def __exit__(self, *exc):
        self._task.cancel()


def reset_mock(delay: float, error_rate: float = 0.0, status: int = 503, retry_after=None):
    from app.core import resilience

    MockState.delay, MockState.error_rate, MockState.error_status, MockState.retry_after = delay, error_rate, status, retry_after
    MockState.calls = MockState.errors = MockState.max_in_flight = 0
    resilience._breakers.clear()


# --- 场景 ---

async def scenario_burst(client, args) -> dict:
    """瞬时 N 个不同访客同时提问：前 3 个执行、10 个排队、其余立即 503。"""
    reset_mock(args.delay)
    with CapacityProbe() as probe:
        results = await asyncio.gather(*[
            stream_turn(client, Visitor(), f"10001_burst{i}") for i in range(args.burst)
        ])
    await asyncio.sleep(0.3)
    return {**summarize(results), "concurrent_clients": args.burst, "observed_max_active": probe.max_active,
            "observed_max_waiting": probe.max_waiting, "mock_max_in_flight_llm_calls": MockState.max_in_flight}


async def scenario_same_session(client, args) -> dict:
    """同一会话两个标签页同时提交：只有一个执行，另一个 409。"""
    reset_mock(args.delay)
    visitor = Visitor()
    results = await asyncio.gather(*[stream_turn(client, visitor, "10001_same") for _ in range(2)])
    return summarize(results)


async def scenario_rate_limit(client, args) -> dict:
    """同一访客 1 分钟内连续 12 次提交（不同会话）：第 11 次起 429。"""
    reset_mock(0.05)
    visitor = Visitor()
    results = []
    for i in range(12):
        results.append(await stream_turn(client, visitor, f"10001_rate{i}"))
    return summarize(results)


async def scenario_transient_errors(client, args) -> dict:
    """30% 模型调用返回 503：每次调用最多重试 1 次。"""
    reset_mock(args.delay / 2, error_rate=0.3, status=503)
    results = []
    for batch in range(3):
        results += await asyncio.gather(*[stream_turn(client, Visitor(), f"10001_err{batch}_{i}") for i in range(3)])
    return {**summarize(results), "mock_calls": MockState.calls, "mock_errors": MockState.errors}


async def scenario_outage(client, args) -> dict:
    """模型持续 503：熔断打开后请求快速失败，冷却后放行探测。"""
    reset_mock(0.05, error_rate=1.0, status=503)
    results = []
    for i in range(8):
        results.append(await stream_turn(client, Visitor(), f"10001_out{i}"))
    from app.core.resilience import breaker_states
    return {**summarize(results), "mock_calls": MockState.calls, "circuits": breaker_states(),
            "per_request_ms": [r["total_ms"] for r in results]}


async def scenario_auth_error(client, args) -> dict:
    """模型返回 401：不重试，玩家看到通用提示。"""
    reset_mock(0.05, error_rate=1.0, status=401)
    results = [await stream_turn(client, Visitor(), f"10001_auth{i}") for i in range(2)]
    return {**summarize(results), "mock_calls": MockState.calls}


async def scenario_disconnect(client, args) -> dict:
    """客户端在执行中断开：名额和会话锁在 Agent 任务结束后释放。"""
    from app.services.admission import capacity_snapshot

    reset_mock(max(args.delay, 2.0))
    results = await asyncio.gather(*[
        stream_turn(client, Visitor(), f"10001_disc{i}", cancel_after=0.5) for i in range(3)
    ])
    released_after_ms = None
    start = time.perf_counter()
    while time.perf_counter() - start < 20:
        if (await capacity_snapshot()).get("active") == 0:
            released_after_ms = int((time.perf_counter() - start) * 1000)
            break
        await asyncio.sleep(0.1)
    follow_up = await stream_turn(client, Visitor(), "10001_disc0")
    return {**summarize(results), "slots_released_after_disconnect_ms": released_after_ms,
            "same_session_follow_up": follow_up["outcome"]}


async def scenario_queue_timeout(client, args) -> dict:
    """排队上限缩短为 3 秒、模型很慢：排队者超时并清除等待记录。"""
    from app.core.config import get_settings
    from app.services.admission import capacity_snapshot

    settings = get_settings()
    original = settings.AGENT_QUEUE_TIMEOUT_SECONDS
    settings.AGENT_QUEUE_TIMEOUT_SECONDS = 3
    reset_mock(4.0)
    try:
        results = await asyncio.gather(*[stream_turn(client, Visitor(), f"10001_qt{i}") for i in range(6)])
    finally:
        settings.AGENT_QUEUE_TIMEOUT_SECONDS = original
    return {**summarize(results), "waiting_after": (await capacity_snapshot()).get("waiting")}


SCENARIOS = {
    "burst": scenario_burst,
    "same_session": scenario_same_session,
    "rate_limit": scenario_rate_limit,
    "transient_errors": scenario_transient_errors,
    "outage": scenario_outage,
    "auth_error": scenario_auth_error,
    "disconnect": scenario_disconnect,
    "queue_timeout": scenario_queue_timeout,
}


def configure_env(args, workdir: str) -> None:
    os.environ.update({
        "LLM_BASE_URL": f"http://127.0.0.1:{MOCK_PORT}/v1",
        "DASHSCOPE_API_KEY": "mock-key-not-real",
        "DEBUG": "true",
        "GAME_JWT_SECRET": "",
        "DEMO_ACCESS_PASSWORD_HASH": "",
        "DB_PATH": os.path.join(workdir, "checkpoints.db"),
        "COORDINATION_BACKEND": "redis" if args.redis_url else "memory",
        "REDIS_URL": args.redis_url or "redis://127.0.0.1:1/0",
        "CHAT_RATE_LIMIT_PER_IP_PER_MINUTE": "1000",
        "LANGCHAIN_TRACING_V2": "false",
        "LOG_LEVEL": "WARNING",
        "NO_PROXY": "127.0.0.1,localhost",
    })


async def main(args) -> None:
    import httpx
    import uvicorn

    workdir = tempfile.mkdtemp(prefix="gsa_load_")
    configure_env(args, workdir)
    from app.main import app as agent_app  # 环境变量就绪后再导入
    from agent.tools import mcp_client
    from langchain_core.tools import tool

    @tool
    def lookup_account(user_id: str, fields: str = "") -> dict:
        """查询玩家账号状态（压测桩，模拟模型不会真正调用）。"""
        return {"status": "normal"}

    mcp_client._mcp_tools = [lookup_account]
    from agent.checkpointer import init_checkpointer
    await init_checkpointer()

    servers = [
        uvicorn.Server(uvicorn.Config(build_mock_app(), host="127.0.0.1", port=MOCK_PORT, log_level="warning")),
        # MCP 不在压测范围：关闭 lifespan，Agent 在无 MCP 工具时走「推理 → 生成」两次模型调用
        uvicorn.Server(uvicorn.Config(agent_app, host="127.0.0.1", port=AGENT_PORT, log_level="warning", lifespan="off")),
    ]
    tasks = [asyncio.create_task(s.serve()) for s in servers]
    while not all(s.started for s in servers):
        await asyncio.sleep(0.05)

    selected = args.scenarios.split(",") if args.scenarios else list(SCENARIOS)
    cpu_start, wall_start = time.process_time(), time.perf_counter()
    report = {
        "environment": {
            "type": "simulated cloud (local mock OpenAI-compatible server)",
            "coordination_backend": os.environ["COORDINATION_BACKEND"],
            "mock_llm_delay_s": args.delay,
            "python": sys.version.split()[0],
            "platform": sys.platform,
            "cpu_count": os.cpu_count(),
            "note": "单进程内同时运行模拟模型与 Agent；不包含 MCP、RAG、MySQL 与真实云端延迟。",
        },
        "scenarios": {},
    }
    limits = httpx.Limits(max_connections=200, max_keepalive_connections=50)
    async with httpx.AsyncClient(limits=limits, trust_env=False) as client:
        for name in selected:
            print(f"[load] running {name} ...", flush=True)
            report["scenarios"][name] = await SCENARIOS[name](client, args)
            print(json.dumps(report["scenarios"][name], ensure_ascii=False), flush=True)
            await asyncio.sleep(0.5)

    wall = time.perf_counter() - wall_start
    report["resources"] = {
        "peak_working_set_mb": peak_rss_mb(),
        "cpu_seconds": round(time.process_time() - cpu_start, 2),
        "wall_seconds": round(wall, 1),
        "avg_cpu_utilization_one_core": round((time.process_time() - cpu_start) / wall, 3),
    }
    RESULTS_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[load] results written to {RESULTS_PATH}")

    for s in servers:
        s.should_exit = True
    await asyncio.gather(*tasks, return_exceptions=True)
    from agent.checkpointer import close_checkpointer
    from app.core.llm import close_llm_clients
    await close_checkpointer()
    await close_llm_clients()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--delay", type=float, default=1.0, help="每次模拟模型调用耗时（秒）")
    parser.add_argument("--burst", type=int, default=20, help="burst 场景的同时访客数")
    parser.add_argument("--scenarios", default="", help="逗号分隔的场景名，默认全部")
    parser.add_argument("--redis-url", default="", help="使用真实 Redis 作为协调后端")
    asyncio.run(main(parser.parse_args()))
