"""MCP 客户端：连接 MCP Server 并缓存工具。"""

import os
from datetime import timedelta
from typing import Optional
from contextlib import AsyncExitStack

from langchain_mcp_adapters.client import MultiServerMCPClient

from app.core.config import get_settings

_exit_stack: Optional[AsyncExitStack] = None
_mcp_client: Optional[MultiServerMCPClient] = None
_mcp_tools: list = []


async def init_mcp_client(url: str = "http://localhost:8001/mcp") -> list:
    """初始化 MCP 客户端，连接 MCP Server 并发现工具。

    Args:
        url: MCP Server 地址（streamable_http）

    Returns:
        MCP 工具列表（LangChain BaseTool 格式）
    """
    global _exit_stack, _mcp_client, _mcp_tools

    # 让本地/Docker 内地址绕过系统代理
    _no_proxy = os.environ.get("NO_PROXY", "")
    for host in ("localhost", "127.0.0.1", "mcp-server"):
        if host not in _no_proxy:
            _no_proxy = f"{_no_proxy},{host}" if _no_proxy else host
    os.environ["NO_PROXY"] = _no_proxy
    os.environ["no_proxy"] = _no_proxy

    _exit_stack = AsyncExitStack()
    await _exit_stack.__aenter__()

    # langchain-mcp-adapters 0.1.0+ 不能把 client 当上下文管理器，
    # 直接 get_tools() 即可；返回的工具每次调用时自动开新 session。
    settings = get_settings()
    # 决策：传输层超时略大于工具层 wait_for，确保由工具层先超时并给出可读的失败记录。
    _mcp_client = MultiServerMCPClient({
        "cs-tools": {
            "url": url,
            "transport": "streamable_http",
            "timeout": timedelta(seconds=10),
            "sse_read_timeout": timedelta(seconds=settings.MCP_KNOWLEDGE_TIMEOUT_SECONDS + 5),
        }
    })
    raw = await _mcp_client.get_tools()
    # 按工具名去重（langchain-mcp-adapters 多 session 并发时会返回重复工具）
    seen: set = set()
    _mcp_tools = []
    for t in raw:
        if t.name not in seen:
            seen.add(t.name)
            _mcp_tools.append(t)
    print(f"[MCP] MCP Server connected, discovered {len(_mcp_tools)} tool(s)")
    for t in _mcp_tools:
        print(f"         - {t.name}")

    return _mcp_tools


def get_mcp_tools() -> list:
    """获取已缓存的 MCP 工具列表（LangChain BaseTool 格式）"""
    return _mcp_tools


async def close_mcp_client():
    """关闭 MCP 客户端连接（应用关闭时调用）"""
    global _exit_stack, _mcp_client, _mcp_tools

    _mcp_client = None
    _mcp_tools = []

    if _exit_stack is not None:
        await _exit_stack.aclose()
        _exit_stack = None
