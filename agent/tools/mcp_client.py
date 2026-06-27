"""
MCP Client 封装

连接本项目的 MCP Server（mcp_server.py，streamable_http transport），
发现并缓存工具，转成 LangChain BaseTool 供 Agent 使用。

连接失败自动降级：返回空列表，get_all_tools() 改用本地工具兜底，不影响核心功能。
"""

import os
from typing import Optional
from contextlib import AsyncExitStack

from langchain_mcp_adapters.client import MultiServerMCPClient

_exit_stack: Optional[AsyncExitStack] = None
_mcp_client: Optional[MultiServerMCPClient] = None
_mcp_tools: list = []


async def init_mcp_client(url: str = "http://localhost:8001/mcp") -> list:
    """初始化 MCP 客户端，连接 MCP Server 并发现工具。

    Args:
        url: MCP Server 地址（streamable_http，连接失败自动降级为空列表）

    Returns:
        MCP 工具列表（LangChain BaseTool 格式）
    """
    global _exit_stack, _mcp_client, _mcp_tools

    # 让本地地址绕过系统代理（避免 VPN/代理拦截 localhost 导致连接失败）
    _no_proxy = os.environ.get("NO_PROXY", "")
    for host in ("localhost", "127.0.0.1"):
        if host not in _no_proxy:
            _no_proxy = f"{_no_proxy},{host}" if _no_proxy else host
    os.environ["NO_PROXY"] = _no_proxy
    os.environ["no_proxy"] = _no_proxy

    _exit_stack = AsyncExitStack()
    await _exit_stack.__aenter__()

    # langchain-mcp-adapters 0.1.0+ 不能把 client 当上下文管理器，
    # 直接 get_tools() 即可；返回的工具每次调用时自动开新 session。
    _mcp_client = MultiServerMCPClient({
        "cs-tools": {
            "url": url,
            "transport": "streamable_http",
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
