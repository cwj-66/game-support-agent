"""应用异常类与统一错误响应。"""

import logging
from typing import Any, Dict, Optional
from fastapi import HTTPException, status
from fastapi.responses import JSONResponse
from fastapi.requests import Request

logger = logging.getLogger(__name__)


class AppException(HTTPException):
    """应用基础异常；retry_after 非空时响应带 Retry-After 头。"""

    def __init__(
        self,
        status_code: int,
        error_code: str,
        message: str,
        details: Optional[Dict[str, Any]] = None,
        retry_after: Optional[int] = None,
    ):
        headers = {"Retry-After": str(retry_after)} if retry_after else None
        super().__init__(status_code=status_code, detail=message, headers=headers)
        self.error_code = error_code
        self.message = message
        self.details = details or {}
        self.retry_after = retry_after

    def public_event(self) -> Dict[str, Any]:
        """SSE error 事件载荷（只含面向玩家的信息）。"""
        event: Dict[str, Any] = {"type": "error", "code": self.error_code, "message": self.message}
        if self.retry_after:
            event["retry_after"] = self.retry_after
        return event


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
    def __init__(self, message: str = "本轮回复未能完成，请稍后重试。", details: Optional[Dict] = None):
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


class ServerBusyException(AppException):
    """全站队列已满"""
    def __init__(self, retry_after: int = 10):
        super().__init__(503, "server_busy", "当前咨询人数较多，服务繁忙，请稍后再试。", retry_after=retry_after)


class QueueTimeoutException(AppException):
    """排队超过等待上限"""
    def __init__(self, retry_after: int = 15):
        super().__init__(503, "queue_timeout", "排队等待超时，请稍后重新发送。", retry_after=retry_after)


class CapacityUnavailableException(AppException):
    """协调存储不可用时拒绝新请求，避免容量限制失效"""
    def __init__(self, retry_after: int = 10):
        super().__init__(503, "capacity_unavailable", "服务暂时无法受理新的问题，请稍后重试。", retry_after=retry_after)


class SessionBusyException(AppException):
    """同一会话已有请求在修改状态"""
    def __init__(self, retry_after: int = 3):
        super().__init__(409, "session_busy", "上一条消息仍在处理，请等待完成后再操作。", retry_after=retry_after)


class TurnCancelledException(AppException):
    """本轮被结束对话等操作取消"""
    def __init__(self):
        super().__init__(409, "turn_cancelled", "本轮对话已结束。")


class RateLimitedException(AppException):
    """访客提问过于频繁"""
    def __init__(self, retry_after: int):
        super().__init__(429, "rate_limited", f"提问太频繁，请 {retry_after} 秒后再试。", retry_after=retry_after)


class AgentTimeoutException(AppException):
    """单个问答超过整体执行上限"""
    def __init__(self):
        super().__init__(504, "agent_timeout", "本轮处理超时，请稍后重试。", retry_after=10)


class UpstreamUnavailableException(AppException):
    """云端模型或下游服务持续故障"""
    def __init__(self, retry_after: int = 30):
        super().__init__(503, "upstream_unavailable", "智能客服暂时繁忙，请稍后重试。", retry_after=retry_after)


async def app_exception_handler(request: Request, exc: AppException) -> JSONResponse:
    """将 AppException 转为标准 JSON 响应。"""
    return JSONResponse(
        status_code=exc.status_code,
        headers=exc.headers,
        content={
            "success": False,
            "error_code": exc.error_code,
            "message": exc.message,
            "details": exc.details,
            "path": request.url.path
        }
    )


async def generic_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """捕获未处理异常，记录堆栈并返回通用错误（不向客户端暴露异常细节）。"""
    logger.exception("Unhandled error on %s %s", request.method, request.url.path)
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
