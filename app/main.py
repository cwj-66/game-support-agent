"""FastAPI 入口。"""

from dotenv import load_dotenv
load_dotenv()

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import get_settings

logging.basicConfig(
    level=get_settings().LOG_LEVEL,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
# 第三方库的请求日志可能带完整 URL 或头部，统一降到 WARNING。
for _noisy in ("httpx", "httpcore", "openai"):
    logging.getLogger(_noisy).setLevel(logging.WARNING)
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

    try:
        await init_mcp_client(settings.MCP_SERVER_URL + "/mcp")
    except Exception as e:
        raise RuntimeError(f"MCP 连接失败: {e}") from e

    from agent.checkpointer import close_checkpointer, init_checkpointer

    try:
        await init_checkpointer()
        print("[STARTUP] SQLite checkpointer OK")
    except Exception as e:
        raise RuntimeError(f"SQLite checkpointer 初始化失败: {e}") from e

    try:
        from app.core.blocking import run_blocking
        from app.repositories.database import init_db
        await run_blocking(init_db)
        print("[STARTUP] MySQL OK")
    except Exception as e:
        print(f"[STARTUP] MySQL 失败: {type(e).__name__}")
        print("[STARTUP] 请执行: docker compose up -d mysql")

    print(
        f"[STARTUP] capacity: concurrency={settings.AGENT_MAX_CONCURRENCY} "
        f"queue={settings.AGENT_MAX_QUEUE} queue_timeout={settings.AGENT_QUEUE_TIMEOUT_SECONDS}s "
        f"backend={settings.COORDINATION_BACKEND}"
    )

    yield

    print("[SHUTDOWN] stopped")
    from app.core.blocking import shutdown_blocking
    from app.core.llm import close_llm_clients
    from app.core.mysql_db import close_pool
    from app.services.admission import release_all_held
    from app.services.coordination import close_coordination

    await release_all_held()
    await close_coordination()
    await close_checkpointer()
    await close_mcp_client()
    await close_llm_clients()
    shutdown_blocking()
    close_pool()


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

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    from app.core.client_ip import VisitorCookieMiddleware
    from app.services.demo_access import DemoAccessMiddleware, router as access_router
    app.add_middleware(DemoAccessMiddleware)
    app.add_middleware(VisitorCookieMiddleware)
    app.include_router(access_router)

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

    from app.core.resilience import breaker_states
    from app.services.admission import capacity_snapshot

    rag_status = rag.get("status", "down")
    capacity = await capacity_snapshot()
    overall = "healthy" if rag_status == "healthy" and capacity["status"] == "ok" else "degraded"
    return {
        "status": overall,
        "version": settings.APP_VERSION,
        "checks": {"rag_service": rag_status, "capacity": capacity, "circuits": breaker_states()},
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
