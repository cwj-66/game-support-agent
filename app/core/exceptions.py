"""
统一错误处理
定义应用级别的异常类和错误响应格式
"""

import traceback
from typing import Any, Dict, Optional
from fastapi import HTTPException, status
from fastapi.responses import JSONResponse
from fastapi.requests import Request


class AppException(HTTPException):
    """
    应用基础异常类
    
    Attributes:
        status_code: HTTP状态码
        error_code: 业务错误码
        message: 错误消息
        details: 额外详情
    """
    
    def __init__(
        self,
        status_code: int,
        error_code: str,
        message: str,
        details: Optional[Dict[str, Any]] = None
    ):
        super().__init__(status_code=status_code, detail=message)
        self.error_code = error_code
        self.message = message
        self.details = details or {}


# ============ 具体业务异常 ============

class SessionNotFoundException(AppException):
    """会话不存在"""
    def __init__(self, session_id: str):
        super().__init__(
            status_code=status.HTTP_404_NOT_FOUND,
            error_code="SESSION_NOT_FOUND",
            message=f"会话不存在: {session_id}",
            details={"session_id": session_id}
        )


class AgentExecutionException(AppException):
    """Agent执行异常"""
    def __init__(self, message: str, details: Optional[Dict] = None):
        super().__init__(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            error_code="AGENT_EXECUTION_ERROR",
            message=message,
            details=details
        )


class HumanReviewNotPendingException(AppException):
    """没有待审核内容"""
    def __init__(self, session_id: str):
        super().__init__(
            status_code=status.HTTP_400_BAD_REQUEST,
            error_code="NO_PENDING_REVIEW",
            message=f"会话 {session_id} 没有待审核内容",
            details={"session_id": session_id}
        )


# ============ 异常处理器 ============

async def app_exception_handler(request: Request, exc: AppException) -> JSONResponse:
    """
    应用异常统一处理器
    
    将AppException转换为标准JSON响应
    """
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "success": False,
            "error_code": exc.error_code,
            "message": exc.message,
            "details": exc.details,
            "path": request.url.path
        }
    )


async def generic_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """
    通用异常处理器

    捕获所有未处理的异常，打印完整堆栈到控制台
    """
    print(f"\n{'='*60}")
    print(f"[ERROR] {request.method} {request.url.path}")
    print(f"[ERROR] {type(exc).__name__}: {exc}")
    traceback.print_exc()
    print(f"{'='*60}\n")
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "success": False,
            "error_code": "INTERNAL_ERROR",
            "message": "服务器内部错误",
            "details": {"error": str(exc)} if True else {},  # DEBUG时显示详情
            "path": request.url.path
        }
        )


# TODO: 未来扩展
# - 添加错误码国际化
# - 实现错误日志自动上报
# - 添加请求追踪ID
