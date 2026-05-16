"""
FastAPI 入口
整合所有API路由和全局配置
"""

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
from app.api.v1 import chat, human


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
    
    # TODO: 检查RAG服务健康状态
    # TODO: 加载敏感词库
    
    yield
    
    # 关闭逻辑
    print("[SHUTDOWN] Application stopped")
    
    # TODO: 清理其他资源


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
