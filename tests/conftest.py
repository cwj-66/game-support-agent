"""
Pytest 配置和共享fixture
"""

import pytest
import pytest_asyncio
from typing import Generator, AsyncGenerator
import tempfile
import shutil
from pathlib import Path


@pytest.fixture(scope="session")
def test_data_dir() -> Generator[Path, None, None]:
    """创建临时测试数据目录"""
    temp_dir = Path(tempfile.mkdtemp(prefix="game_support_test_"))
    yield temp_dir
    # 测试结束后清理
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
def sensitive_words() -> list:
    """测试用敏感词列表"""
    return ["封号", "退款", "投诉", "举报"]


@pytest.fixture
def mock_agent_state():
    """模拟Agent状态"""
    return {
        "messages": [],
        "user_query": "测试问题",
        "session_id": "test_session_001",
        "interrupt_info": None,
        "human_review": None,
        "tool_calls": [],
        "final_response": None,
        "metadata": {}
    }


@pytest.fixture
def mock_interrupt_decision():
    """模拟中断决策"""
    return {
        "should_interrupt": True,
        "reason": "检测到敏感词",
        "level": "high",
        "sensitive_words": ["投诉"]
    }


# Async fixtures
@pytest_asyncio.fixture
async def async_http_client():
    """异步HTTP客户端"""
    import httpx
    async with httpx.AsyncClient() as client:
        yield client


# 标记慢测试
pytest.SLOW = pytest.mark.slow


# 自定义标记
def pytest_configure(config):
    """配置pytest"""
    config.addinivalue_line("markers", "slow: marks tests as slow")
    config.addinivalue_line("markers", "integration: marks tests as integration tests")
    config.addinivalue_line("markers", "unit: marks tests as unit tests")
