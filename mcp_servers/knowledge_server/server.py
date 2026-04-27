"""
SSE 模式 MCP Server
基于 fastmcp 库，暴露 query_knowledge 工具
内部调用 enterprise-rag 服务 (localhost:8000)
"""

import asyncio
import json

import httpx

try:
    from mcp.server.fastmcp import FastMCP, Context
except ImportError:
    FastMCP = None
    Context = None

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from .client import get_rag_client, close_rag_client
from .auth import get_auth_manager


# ── 1. SSE 传输配置 ──────────────────────────────────────────────────────────
# sse_path: 固定 SSE 端点路径；ping_interval: 心跳包间隔（秒），维持长连接
mcp = FastMCP(
    "game-support-knowledge",
    sse_path="/sse",
    ping_interval=15,
)


# ── 2. 安全认证中间件 ─────────────────────────────────────────────────────────
class APIKeyMiddleware(BaseHTTPMiddleware):
    """拦截所有请求，校验 X-MCP-API-Key 请求头"""

    async def dispatch(self, request: Request, call_next) -> Response:
        provided_key = request.headers.get("X-MCP-API-Key")
        auth = get_auth_manager()
        if not auth.verify(provided_key):
            return Response(
                content="无效的MCP API Key",
                status_code=401,
                media_type="text/plain; charset=utf-8",
            )
        return await call_next(request)


# ── 工具定义 ──────────────────────────────────────────────────────────────────

@mcp.tool()
async def query_knowledge(
    question: str,
    ctx: Context = None,
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
    """
    # ── 4. 完善工具日志：调用前阶段 ──
    if ctx:
        await ctx.info(f"[开始] 收到查询请求: {question[:50]}")
        await ctx.info("正在调用 RAG 服务检索知识...")

    client = get_rag_client()

    try:
        result = await client.query_knowledge(question, top_k=3)

        # 调用后阶段日志
        if ctx:
            await ctx.info(
                f"[完成] 检索成功 | 置信度: {result.get('confidence', 0):.2f}"
                f" | 命中片段: {len(result.get('sources', []))} 条"
            )

        return json.dumps(result, ensure_ascii=False)

    except httpx.TimeoutException as e:
        # 网络超时：RAG 服务未在限定时间内响应
        if ctx:
            await ctx.error(f"网络超时：RAG 服务未在规定时间内响应（{e}）")
        return json.dumps(
            {
                "has_answer": False,
                "error": "请求超时",
                "message": "知识服务响应超时，建议稍后重试或转人工",
            },
            ensure_ascii=False,
        )

    except httpx.HTTPStatusError as e:
        # 服务端明确返回了 4xx/5xx
        if ctx:
            await ctx.error(
                f"服务端报错：HTTP {e.response.status_code}"
                f" | 请求路径: {e.request.url}"
            )
        return json.dumps(
            {
                "has_answer": False,
                "error": f"服务端错误 HTTP {e.response.status_code}",
                "message": "知识服务返回异常状态码，请联系运维排查",
            },
            ensure_ascii=False,
        )

    except Exception as e:
        if ctx:
            await ctx.error(f"未知错误 [{type(e).__name__}]: {e}")
        return json.dumps(
            {
                "has_answer": False,
                "error": str(e),
                "message": "知识服务发生未知错误",
            },
            ensure_ascii=False,
        )


@mcp.tool()
async def check_knowledge_health(ctx: Context = None) -> str:
    """
    MCP 工具：检查知识库服务健康状态

    Returns:
        健康状态JSON字符串
    """
    client = get_rag_client()
    health = await client.health_check()

    return json.dumps(
        {
            "status": health.status,
            "version": health.version,
            "latency_ms": health.latency_ms,
        },
        ensure_ascii=False,
    )


# ── 3. 服务启动 + 优雅关闭 ────────────────────────────────────────────────────

async def run_server(host: str = "0.0.0.0", port: int = 8001):
    """
    启动SSE模式MCP服务器

    - 注入 APIKeyMiddleware 认证中间件
    - 使用 try/finally 保证退出时（含 Ctrl+C）清理 RAG 连接

    Args:
        host: 监听地址
        port: 监听端口（默认8001，与RAG的8000区分）
    """
    import uvicorn

    print(f"启动MCP知识服务器: http://{host}:{port}")
    print(f"SSE端点: http://{host}:{port}/sse")

    # 获取底层 Starlette app，注入认证中间件
    # 若 SDK 版本不同导致 sse_app() 不存在，可改为 mcp.get_app() 或 mcp.app
    sse_app = mcp.sse_app()
    sse_app.add_middleware(APIKeyMiddleware)

    config = uvicorn.Config(sse_app, host=host, port=port, log_level="info")
    server = uvicorn.Server(config)

    try:
        await server.serve()
    finally:
        # 无论正常退出还是 Ctrl+C，都确保关闭 RAG 底层 HTTP 连接
        await close_rag_client()
        print("RAG连接已清理，服务器已优雅关闭")


# 测试入口
if __name__ == "__main__":
    async def test():
        result = await query_knowledge("原神如何获得原石？")
        print(result)

    asyncio.run(test())
