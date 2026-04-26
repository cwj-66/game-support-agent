"""
SSE 模式 MCP Server
基于 fastmcp 库，暴露 query_knowledge 工具
内部调用 enterprise-rag 服务 (localhost:8000)
"""

import asyncio
import json
from contextlib import asynccontextmanager
from typing import AsyncIterator

# fastmcp 是 MCP 协议的 Python SDK
try:
    from mcp.server.fastmcp import FastMCP, Context
except ImportError:
    # 如果 fastmcp 未安装，提供降级方案
    FastMCP = None
    Context = None

from .client import get_rag_client, close_rag_client
from .auth import get_auth_manager, MCPAuthManager


# 创建 MCP Server 实例
# SSE 模式下，客户端通过 HTTP SSE 连接，支持长会话
mcp = FastMCP(
    "game-support-knowledge",
    # TODO: 配置SSE端点路径
    # TODO: 配置心跳间隔
)


@mcp.tool()
async def query_knowledge(
    question: str,
    ctx: Context = None
) -> str:
    """
    MCP 工具：查询游戏知识库
    
    这是Agent与外部知识交互的主要接口。
    输入用户问题，返回RAG检索到的相关知识。
    
    Args:
        question: 用户问题，例如"原神如何获得原石？"
        ctx: MCP上下文，用于日志和进度报告
        
    Returns:
        知识检索结果（JSON格式字符串）
        
    Example:
        >>> result = await query_knowledge("如何联系客服？")
        >>> # 返回: '{"answer": "您可以拨打...", "sources": [...]}'
    """
    # 记录工具调用（用于审计）
    if ctx:
        await ctx.info(f"查询知识库: {question[:50]}...")
    
    client = get_rag_client()
    
    try:
        # 调用RAG服务
        result = await client.query_knowledge(question, top_k=3)

        if ctx:
            await ctx.info(f"查询完成，置信度: {result.get('confidence', 0)}")

        return json.dumps(result, ensure_ascii=False)

    except Exception as e:
        error_result = {
            "has_answer": False,
            "error": str(e),
            "message": "知识服务暂时不可用",
        }
        if ctx:
            await ctx.error(f"未知错误: {e}")
        return json.dumps(error_result, ensure_ascii=False)


@mcp.tool()
async def check_knowledge_health(ctx: Context = None) -> str:
    """
    MCP 工具：检查知识库服务健康状态
    
    Returns:
        健康状态JSON字符串
    """
    client = get_rag_client()
    health = await client.health_check()
    
    return json.dumps({
        "status": health.status,
        "version": health.version,
        "latency_ms": health.latency_ms
    }, ensure_ascii=False)


# TODO: 实现SSE服务器启动
# TODO: 配置CORS和认证中间件
# TODO: 实现优雅关闭


async def run_server(host: str = "0.0.0.0", port: int = 8001):
    """
    启动SSE模式MCP服务器
    
    Args:
        host: 监听地址
        port: 监听端口（默认8001，与RAG的8000区分）
    """
    # TODO: 配置SSE transport
    # TODO: 配置认证中间件
    # TODO: 配置日志
    
    print(f"启动MCP知识服务器: http://{host}:{port}")
    print(f"SSE端点: http://{host}:{port}/sse")

    await mcp.run_sse_async(host=host, port=port)


# 测试入口
if __name__ == "__main__":
    # 开发测试：直接运行工具
    async def test():
        result = await query_knowledge("原神如何获得原石？")
        print(result)
    
    asyncio.run(test())
