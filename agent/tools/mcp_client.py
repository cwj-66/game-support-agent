"""
MCP Client 封装

支持两种 transport：
- stdio：应用启动时自动 spawn SQLite MCP Server（npx @modelcontextprotocol/server-sqlite）
- sse：可选连接远程 MCP Server（降级不影响核心功能）

工具函数（ticket.py / ticket_status.py）通过 mcp_read_query / mcp_write_query
访问 SQLite 数据库，不再直接 import sqlite3。
"""

import json
import os
from typing import Optional
from contextlib import AsyncExitStack

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from langchain_mcp_adapters.client import MultiServerMCPClient

_sqlite_session: Optional[ClientSession] = None
_exit_stack: Optional[AsyncExitStack] = None
_mcp_client: Optional[MultiServerMCPClient] = None
_mcp_tools: list = []


def _resolve_db_path() -> str:
    """获取 SQLite 数据库路径，与 app.core.database 保持一致"""
    try:
        from app.core.config import get_settings
        return os.path.abspath(get_settings().DB_PATH)
    except Exception:
        return os.path.abspath(
            os.path.join(
                os.path.dirname(__file__), "..", "..", "data", "game_support.db"
            )
        )


async def init_mcp_client(url: str = "http://localhost:8001/sse") -> list:
    """初始化 MCP 客户端

    1. 启动 SQLite MCP Server（stdio，自动 spawn npx 进程）
    2. 可选连接远程 SSE MCP Server

    Args:
        url: SSE MCP Server 地址（连接失败自动降级）

    Returns:
        SSE MCP 工具列表（兼容 main.py 的日志逻辑）
    """
    global _sqlite_session, _exit_stack, _mcp_client, _mcp_tools

    _exit_stack = AsyncExitStack()
    await _exit_stack.__aenter__()

    # === 1. SQLite MCP Server（stdio） ===
    db_path = _resolve_db_path()
    os.makedirs(os.path.dirname(db_path), exist_ok=True)

    sqlite_params = StdioServerParameters(
        command="npx",
        args=["-y", "@modelcontextprotocol/server-sqlite", db_path],
    )

    stdio_transport = await _exit_stack.enter_async_context(
        stdio_client(sqlite_params)
    )
    read_stream, write_stream = stdio_transport
    _sqlite_session = await _exit_stack.enter_async_context(
        ClientSession(read_stream, write_stream)
    )
    await _sqlite_session.initialize()
    print(f"[MCP] SQLite MCP Server connected, DB: {db_path}")

    # === 2. SSE MCP Server（可选） ===
    try:
        _mcp_client = MultiServerMCPClient({
            "cs-tools": {
                "url": url,
                "transport": "sse",
            }
        })
        _mcp_tools = await _mcp_client.get_tools()
        print(
            f"[MCP] SSE MCP Server connected, "
            f"discovered {len(_mcp_tools)} tool(s)"
        )
        for t in _mcp_tools:
            print(f"         - {t.name}")
    except Exception as e:
        _mcp_tools = []
        print(f"[MCP] SSE MCP Server skip (optional): {e}")

    return _mcp_tools


def _sqlesc(val: str) -> str:
    """SQLite 字符串转义，防止工具参数中的单引号破坏 SQL"""
    return val.replace("'", "''")


async def mcp_read_query(query: str) -> list[dict]:
    """执行 SELECT 查询

    Args:
        query: SELECT SQL 语句

    Returns:
        行列表，每行为 {column_name: value, ...}

    Raises:
        RuntimeError: MCP 客户端未初始化
    """
    if _sqlite_session is None:
        raise RuntimeError("MCP client not initialized, call init_mcp_client() first")

    result = await _sqlite_session.call_tool("read_query", {"query": query})

    text = ""
    for content in result.content:
        if hasattr(content, "text"):
            text += content.text

    if not text.strip():
        return []
    return json.loads(text)


async def mcp_write_query(query: str) -> dict:
    """执行 INSERT / UPDATE / DELETE

    Args:
        query: 写 SQL 语句

    Returns:
        执行结果

    Raises:
        RuntimeError: MCP 客户端未初始化
    """
    if _sqlite_session is None:
        raise RuntimeError("MCP client not initialized, call init_mcp_client() first")

    result = await _sqlite_session.call_tool("write_query", {"query": query})

    text = ""
    for content in result.content:
        if hasattr(content, "text"):
            text += content.text

    return {"result": text}


def get_mcp_tools() -> list:
    """获取已缓存的 SSE MCP 工具列表（LangChain BaseTool 格式）"""
    return _mcp_tools


async def close_mcp_client():
    """关闭 MCP 客户端连接（应用关闭时调用）"""
    global _sqlite_session, _exit_stack, _mcp_client, _mcp_tools

    _sqlite_session = None
    _mcp_client = None
    _mcp_tools = []

    if _exit_stack is not None:
        await _exit_stack.aclose()
        _exit_stack = None
