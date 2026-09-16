"""应用异常类与统一错误响应。"""

import traceback
from typing import Any, Dict, Optional
from fastapi import HTTPException, status
from fastapi.responses import JSONResponse
from fastapi.requests import Request


class AppException(HTTPException):
    """应用基础异常。"""

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


async def app_exception_handler(request: Request, exc: AppException) -> JSONResponse:
    """将 AppException 转为标准 JSON 响应。"""
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
    """捕获未处理异常，记录堆栈并返回通用错误。"""
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
            "details": {},
            "path": request.url.path
        }
    )
