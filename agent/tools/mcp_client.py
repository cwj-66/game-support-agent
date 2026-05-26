"""
MCP Client 封装

职责（按启动顺序）：
1. 应用启动时连接 MCP Server
2. 发现并缓存远程工具（MCP → LangChain BaseTool）
3. 提供 get_mcp_tools() 供 get_all_tools() 注入

关键设计：
- escalate_to_human 不经过 MCP（就一个信号，直接在 LangGraph 内部处理）
- Server 只管工具的实现，Client 只管工具的发现和绑定
- interrupt 的控制权始终在 LangGraph 图里
"""
from typing import Optional

from langchain_mcp_adapters.client import MultiServerMCPClient

_mcp_client: Optional[MultiServerMCPClient] = None
_mcp_tools: list = []


async def init_mcp_client(url: str = "http://localhost:8001/sse") -> list:
    """初始化 MCP 客户端，连接 Server 并进行工具发现

    Args:
        url: MCP Server SSE 地址

    Returns:
        已发现的 LangChain BaseTool 列表
    """
    global _mcp_client, _mcp_tools

    _mcp_client = MultiServerMCPClient({
        "cs-tools": {
            "url": url,
            "transport": "sse",
        }
    })
    _mcp_tools = await _mcp_client.get_tools()
    return _mcp_tools


def get_mcp_tools() -> list:
    """获取已缓存的 MCP 工具列表（LangChain BaseTool 格式）"""
    return _mcp_tools


async def close_mcp_client():
    """关闭 MCP 客户端连接（应用关闭时调用）"""
    global _mcp_client, _mcp_tools
    if _mcp_client is not None:
        # TODO: 清理 MCP 连接资源
        _mcp_client = None
    _mcp_tools = []
