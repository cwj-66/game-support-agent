"""
FastAPI 入口
整合所有API路由和全局配置

注意：LangSmith 环境变量必须在所有 LangChain 导入之前生效。
最稳方案是在进程启动前导出，或在此处用 load_dotenv 加载 .env 到 os.environ。
"""

# 在所有 import 之前，先把 .env 加载到 os.environ
# 这样 LangChain 导入时就能读到 LANGCHAIN_TRACING_V2 等变量
from dotenv import load_dotenv
load_dotenv()

import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import get_settings, Settings

from app.core.exceptions import (
    AppException,
    app_exception_handler,
    generic_exception_handler
)
from app.api.v1 import chat, human, ticket
from agent.tools.mcp_client import init_mcp_client, close_mcp_client


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    应用生命周期管理
    
    启动时：
    - 检查外部服务连接（RAG、MCP）
    - 初始化全局资源
    
    关闭时：
    - 清理资源
    - 关闭连接
    """
    settings = get_settings()

    # 启动逻辑
    print(f"[STARTUP] {settings.APP_NAME} v{settings.APP_VERSION}")
    print(f"[STARTUP] Access at http://127.0.0.1:{settings.PORT}")
    print(f"[STARTUP] API docs at http://127.0.0.1:{settings.PORT}/docs")
    if settings.LANGCHAIN_TRACING_V2 and settings.LANGCHAIN_API_KEY:
        print(f"[STARTUP] LangSmith tracing enabled (project: {settings.LANGCHAIN_PROJECT})")

    # 初始化 MCP 客户端（连接 Server + 工具发现）
    try:
        mcp_tools = await init_mcp_client(settings.MCP_SERVER_URL + "/sse")
        print(f"[STARTUP] MCP client connected, discovered {len(mcp_tools)} tool(s)")
        for t in mcp_tools:
            print(f"         - {t.name}")
    except Exception as e:
        print(f"[STARTUP] MCP client init skipped: {e}")
        print("[STARTUP] Local mock tools will be used as fallback")

    # 初始化 RedisSaver（Agent 状态持久化）
    try:
        from agent.checkpointer import init_checkpointer
        await init_checkpointer()
        print(f"[STARTUP] RedisSaver initialized")
    except Exception as e:
        print(f"[STARTUP] RedisSaver init failed: {e}")
        print(f"[STARTUP] Agent will not work without Redis — start it with: docker compose up -d redis")

    # 初始化 SQLite 数据库（工单表）
    try:
        from app.core.database import init_db
        init_db()
        print(f"[STARTUP] SQLite database initialized")
    except Exception as e:
        print(f"[STARTUP] SQLite init failed: {e}")

    # TODO: 检查RAG服务健康状态
    # TODO: 加载敏感词库

    yield

    # 关闭逻辑
    print("[SHUTDOWN] Application stopped")

    # 清理 MCP 连接
    await close_mcp_client()


def create_application() -> FastAPI:
    """
    创建FastAPI应用实例
    
    工厂函数，便于测试时创建独立实例
    """
    settings = get_settings()
    
    app = FastAPI(
        title=settings.APP_NAME,
        version=settings.APP_VERSION,
        description="基于LangGraph的游戏客服Agent，支持Human-in-loop",
        docs_url="/docs",
        redoc_url="/redoc",
        lifespan=lifespan
    )
    
    # 注册CORS中间件
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],  # TODO: 生产环境限制具体域名
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    
    # 注册异常处理器
    app.add_exception_handler(AppException, app_exception_handler)
    app.add_exception_handler(Exception, generic_exception_handler)

    # 注册API路由
    app.include_router(
        chat.router,
        prefix=f"{settings.API_V1_PREFIX}",
        tags=["对话"]
    )
    app.include_router(
        human.router,
        prefix=f"{settings.API_V1_PREFIX}",
        tags=["人工审核"]
    )
    app.include_router(
        ticket.router,
        prefix=f"{settings.API_V1_PREFIX}",
        tags=["工单"]
    )

    return app


# 创建应用实例
app = create_application()


@app.get("/")
async def root():
    """根路径，返回服务信息"""
    settings = get_settings()
    return {
        "service": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "docs": "/docs",
        "health": "/health"
    }


@app.get("/health")
async def health_check():
    """健康检查端点"""
    return {
        "status": "healthy",
        "version": get_settings().APP_VERSION,
        "checks": {
            "rag_service": "unknown",  # TODO: 真实检查
        }
    }


# 启动入口（开发时使用）
if __name__ == "__main__":
    import uvicorn
    
    settings = get_settings()
    uvicorn.run(
        "app.main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=settings.DEBUG
    )
