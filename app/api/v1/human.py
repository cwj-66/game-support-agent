"""
人工接待操作API
支持客服多轮与玩家对话，以及结束接待（action=close）。
"""

from datetime import datetime, timezone
from typing import Optional


from fastapi import APIRouter, Depends, Header, HTTPException, Path
from pydantic import BaseModel, Field

from app.core.config import get_settings
from app.core.exceptions import (
    HumanReviewNotPendingException,
)
from app.core.pending_store import (
    get_all_pending,
    remove_pending,
    get_pending,
    add_pending,
)
from app.models.review import (
    ReviewResponse,
    PendingReviewsResponse,
    ReviewTask,
    ReviewHistoryResponse,
)
from app.core.human_invoke import invoke_human_resume


router = APIRouter(prefix="/human", tags=["人工审核"])


# ── 审核鉴权 ──────────────────────────────────────────────────────
# 简化版：X-Reviewer-Token 与配置文件密钥比对
# 生产应替换为 JWT + RBAC 方案


async def require_reviewer_token(x_reviewer_token: str = Header(...)) -> str:
    """校验审核员身份（依赖注入）"""
    settings = get_settings()
    if not settings.REVIEWER_API_KEY:
        # 未配置密钥 → 跳过鉴权（开发模式）
        return "dev_reviewer"
    if x_reviewer_token != settings.REVIEWER_API_KEY:
        raise HTTPException(
            status_code=403,
            detail="Invalid reviewer token",
        )
    return x_reviewer_token


@router.get("/pending", response_model=PendingReviewsResponse)
async def list_pending_reviews(
    _token: str = Depends(require_reviewer_token),
) -> PendingReviewsResponse:
    """
    获取待审核任务列表

    从内存公告板读取所有处于 interrupt 挂起状态的会话
    """
    pending = await get_all_pending()
    now = datetime.now(timezone.utc)

    tasks: list[ReviewTask] = []
    for session_id, payload in pending.items():
        created_at = payload.get("timestamp", now.isoformat())
        try:
            elapsed = (now - datetime.fromisoformat(created_at)).total_seconds()
        except (ValueError, TypeError):
            elapsed = 0

        tasks.append(ReviewTask(
            review_id=session_id,
            session_id=session_id,
            user_query=payload.get("user_query", ""),
            agent_response=payload.get("content", ""),
            interrupt_reason=payload.get("interrupt_reason", "未知"),
            risk_level=payload.get("interrupt_level", "medium"),
            created_at=created_at,
            wait_time_seconds=int(elapsed),
            pending_content=payload.get("pending_content"),
        ))

    return PendingReviewsResponse(total=len(tasks), items=tasks)


class HumanReplyRequest(BaseModel):
    """客服发送消息请求"""
    reply: str = Field(..., description="客服回复内容")
    reviewer_id: str = Field(..., description="审核员标识")
    action: str = Field(default="continue", description="接待操作: continue（继续）/ close（结束接待）")


@router.post("/review/{session_id}", response_model=ReviewResponse)
async def send_agent_message(
    session_id: str,
    body: HumanReplyRequest,
    _token: str = Depends(require_reviewer_token),
) -> ReviewResponse:
    """
    客服向玩家发送消息（支持多轮）

    流程：
    1. 验证 session 处于挂起状态
    2. 以 Command(resume={source, message, action}) 唤醒 human_node
    3. human_node 追加消息到 messages 历史后：
       - action=continue → 图再次 interrupt 挂起，客服可继续发消息
       - action=close   → 图走向 finish，接待结束
    4. action=close 时从公告板移除；continue 时保留（图仍处于挂起）
    """
    if not await get_pending(session_id):
        raise HumanReviewNotPendingException(session_id)

    action = body.action if body.action in ("continue", "close") else "continue"

    resume_payload = {
        "source": "agent",
        "message": body.reply,
        "action": action,
    }

    result = await invoke_human_resume(session_id, resume_payload) or {}

    processed_at = datetime.now(timezone.utc).isoformat()

    if action == "close":
        # 接待结束，从公告板移除
        await remove_pending(session_id)
        final_response = result.get("final_response", body.reply)
    else:
        # 接待继续，图已再次挂起；更新公告板时间戳
        final_response = body.reply
        pending_payload = await get_pending(session_id) or {}
        pending_payload["timestamp"] = processed_at
        await add_pending(session_id, pending_payload)

    return ReviewResponse(
        success=True,
        review_id=f"rev_{session_id}",
        session_id=session_id,
        action="APPROVE",
        final_response=final_response,
        processed_at=processed_at,
    )


@router.post("/join/{session_id}")
async def join_session(
    session_id: str,
    _token: str = Depends(require_reviewer_token),
):
    """
    客服进入会话，发送「客服已接入」提示。
    每个会话只发送一次。
    """
    payload = await get_pending(session_id)
    if not payload:
        return {"success": False, "message": "会话不在待接待状态"}

    if payload.get("joined"):
        return {"success": True, "message": "already joined"}

    # 标记已接入
    payload["joined"] = True
    await add_pending(session_id, payload)

    # 发送接入提示
    resume_payload = {
        "source": "agent",
        "message": "【系统提示】客服已接入，请问有什么可以帮您？",
        "action": "continue",
    }
    await invoke_human_resume(session_id, resume_payload)

    return {"success": True}


@router.get("/status/{session_id}")
async def get_review_status(
    session_id: str = Path(..., description="会话ID"),
    _token: str = Depends(require_reviewer_token),
):
    """
    查询会话的审核状态

    返回：
    - 是否需要审核
    - 当前审核进度
    """
    payload = await get_pending(session_id)
    if payload:
        return {
            "session_id": session_id,
            "has_pending_review": True,
            "interrupt_reason": payload.get("interrupt_reason"),
            "interrupt_level": payload.get("interrupt_level"),
            "waiting_since": payload.get("timestamp"),
        }
    return {
        "session_id": session_id,
        "has_pending_review": False,
        "pending_review_id": None,
    }


@router.get("/history", response_model=ReviewHistoryResponse)
async def get_review_history(
    _token: str = Depends(require_reviewer_token),
    reviewer_id: Optional[str] = None,
    limit: int = 50,
) -> ReviewHistoryResponse:
    """
    获取审核历史

    当前返回空列表，等 AuditLogger 支持按审核员查询后接入
    """
    # TODO: 从 AuditLogger 读取审核历史
    return ReviewHistoryResponse(total=0, items=[])
