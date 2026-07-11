"""
FastAPI 入口
整合所有 API 路由和全局配置

环境变量必须提前导入。
"""

from dotenv import load_dotenv
load_dotenv()

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import get_settings
from app.core.exceptions import (
    AppException,
    app_exception_handler,
    generic_exception_handler,
)
from app.api.v1.router import router as v1_router
from agent.tools.mcp_client import init_mcp_client, close_mcp_client


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期：启动时初始化资源，关闭时清理连接。"""
    settings = get_settings()

    print(
        f"[STARTUP] {settings.APP_NAME} v{settings.APP_VERSION} "
        f"→ http://127.0.0.1:{settings.PORT} (/docs)"
    )
    if settings.LANGCHAIN_TRACING_V2 and settings.LANGCHAIN_API_KEY:
        print(f"[STARTUP] LangSmith: {settings.LANGCHAIN_PROJECT}")

    # MCP 连接失败则启动中止
    try:
        await init_mcp_client(settings.MCP_SERVER_URL + "/mcp")
    except Exception as e:
        raise RuntimeError(f"MCP 连接失败: {e}") from e

    # 初始化 RedisSaver（Agent 状态持久化）
    try:
        from agent.checkpointer import init_checkpointer
        await init_checkpointer()
        print("[STARTUP] Redis OK")
    except Exception as e:
        print(f"[STARTUP] Redis 失败: {e}")
        print("[STARTUP] 请执行: docker compose up -d redis")

    # 初始化 MySQL（玩家 + 工单）
    try:
        from app.repositories.database import init_db
        init_db()
        print("[STARTUP] MySQL OK")
    except Exception as e:
        print(f"[STARTUP] MySQL 失败: {e}")
        print("[STARTUP] 请执行: docker compose up -d mysql")

    yield

    print("[SHUTDOWN] stopped")
    await close_mcp_client()


def create_application() -> FastAPI:
    """创建 FastAPI 应用实例（工厂函数，便于测试）。"""
    settings = get_settings()

    app = FastAPI(
        title=settings.APP_NAME,
        version=settings.APP_VERSION,
        description="基于LangGraph的游戏客服Agent，支持Human-in-loop",
        docs_url="/docs",
        redoc_url="/redoc",
        lifespan=lifespan,
    )

    # 注册 CORS 中间件（供浏览器端小程序/管理后台跨域访问）
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.add_exception_handler(AppException, app_exception_handler)
    app.add_exception_handler(Exception, generic_exception_handler)
    app.include_router(v1_router)

    return app


app = create_application()


@app.get("/")
async def root():
    """根路径，返回服务信息。"""
    settings = get_settings()
    return {
        "service": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "docs": "/docs",
        "health": "/health",
    }


@app.get("/health")
async def health_check():
    """健康检查端点。"""
    from agent.tools.rag_client import RAGClient

    settings = get_settings()
    client = RAGClient(base_url=settings.RAG_SERVICE_URL)
    try:
        rag = await client.health_check()
    finally:
        await client.close()

    rag_status = rag.get("status", "down")
    overall = "healthy" if rag_status == "healthy" else "degraded"
    return {
        "status": overall,
        "version": settings.APP_VERSION,
        "checks": {"rag_service": rag_status},
    }


if __name__ == "__main__":
    import uvicorn

    settings = get_settings()
    uvicorn.run(
        "app.main:app",
        host="127.0.0.1",
        port=settings.PORT,
        reload=settings.DEBUG,
    )
