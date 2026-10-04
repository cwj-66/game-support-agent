"""Pytest 共享 fixture。"""

import os

# 测试默认使用单进程内存协调后端；Redis 语义测试见 test_coordination_redis.py。
os.environ.setdefault("COORDINATION_BACKEND", "memory")

import pytest
import pytest_asyncio
from typing import Generator, AsyncGenerator
import tempfile
import shutil
from pathlib import Path


@pytest.fixture(autouse=True)
def fresh_coordination():
    """每个用例使用全新的内存协调状态与熔断器。"""
    from app.core import resilience
    from app.services import coordination

    coordination.set_coordination(coordination.MemoryCoordination())
    resilience._breakers.clear()
    yield
    coordination.set_coordination(None)
    resilience._breakers.clear()


def make_request(ip: str = "203.0.113.10", visitor: str = "a" * 32, headers: dict | None = None):
    """构造带客户端地址与访客 cookie 的 starlette Request。"""
    from starlette.requests import Request

    raw = [(b"cookie", f"gsa_visitor={visitor}".encode())]
    raw += [(k.lower().encode(), v.encode()) for k, v in (headers or {}).items()]
    return Request({"type": "http", "method": "POST", "path": "/", "headers": raw,
                    "client": (ip, 12345), "query_string": b""})


@pytest.fixture(scope="session")
def test_data_dir() -> Generator[Path, None, None]:
    """创建临时测试数据目录"""
    temp_dir = Path(tempfile.mkdtemp(prefix="game_support_test_"))
    yield temp_dir
    shutil.rmtree(temp_dir, ignore_errors=True)


@pytest.fixture
def sample_faq_data() -> list:
    """示例FAQ数据"""
    return [
        {
            "question": "如何获得原石？",
            "answer": "可以通过完成每日委托、开启宝箱、参与活动、充值等方式获得原石。"
        },
        {
            "question": "怎么提升冒险等级？",
            "answer": "通过完成任务、开启传送点、收集神瞳、参与活动等方式获取冒险阅历。"
        }
    ]


@pytest.fixture
def mock_agent_state():
    """模拟Agent状态"""
    return {
        "messages": [],
        "user_query": "测试问题",
        "session_id": "test_session_001",
        "human_mode": False,
        "human_offer": None,
        "tool_calls": [],
        "final_response": None,
        "metadata": {}
    }


# Async fixtures
@pytest_asyncio.fixture
async def async_http_client():
    """异步HTTP客户端"""
    import httpx
    async with httpx.AsyncClient() as client:
        yield client


pytest.SLOW = pytest.mark.slow


def pytest_configure(config):
    """配置pytest"""
    config.addinivalue_line("markers", "slow: marks tests as slow")
    config.addinivalue_line("markers", "integration: marks tests as integration tests")
    config.addinivalue_line("markers", "unit: marks tests as unit tests")
