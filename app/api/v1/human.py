"""
人工接待操作 API
支持客服多轮与玩家对话，以及结束接待（action=close）。
消息直接写入 checkpoint，不经过 LangGraph interrupt。
"""

import asyncio
from datetime import datetime, timezone
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Path
from pydantic import BaseModel, Field
from langchain_core.messages import AIMessage, HumanMessage

from app.api.deps import require_reviewer_token
from app.core.exceptions import HumanReviewNotPendingException
from app.services.pending_store import (
    get_all_pending,
    get_pending,
    add_pending,
)
from app.models.human_session import (
    HumanReplyResponse,
    PendingHumanSessionsResponse,
    PendingHumanSession,
    HumanSessionAction,
)
from app.services.human_chat import (
    append_agent_message,
    close_human_session,
    get_thread_messages,
)


router = APIRouter(prefix="/human", tags=["人工接待"])


@router.get("/pending", response_model=PendingHumanSessionsResponse)
async def list_pending_sessions(
    _token: str = Depends(require_reviewer_token),
) -> PendingHumanSessionsResponse:
    """获取待接待会话列表"""
    pending = await get_all_pending()
    now = datetime.now(timezone.utc)

    from app.core.config import get_settings
    idle_limit = get_settings().HUMAN_USER_IDLE_SECONDS

    tasks: list[PendingHumanSession] = []
    expired_sessions: list[str] = []

    for session_id, payload in pending.items():
        created_at = payload.get("timestamp", now.isoformat())
        try:
            elapsed = (now - datetime.fromisoformat(created_at)).total_seconds()
        except (ValueError, TypeError):
            elapsed = 0

        # 检查用户空闲超时
        last_user_at_str = payload.get("last_user_at")
        if last_user_at_str:
            try:
                idle_secs = (now - datetime.fromisoformat(last_user_at_str)).total_seconds()
                if idle_secs > idle_limit:
                    expired_sessions.append(session_id)
                    continue
            except (ValueError, TypeError):
                pass

        tasks.append(PendingHumanSession(
            session_id=session_id,
            user_query=payload.get("user_query", ""),
            agent_response=payload.get("summary", ""),
            interrupt_reason="转人工",
            risk_level="high",
            created_at=created_at,
            wait_time_seconds=int(elapsed),
            pending_content=payload.get("summary"),
            last_user_at=payload.get("last_user_at"),
            last_agent_at=payload.get("last_agent_at"),
        ))

    # 异步清理超时会话（不阻塞响应）
    if expired_sessions:
        asyncio.create_task(_auto_close_idle_sessions(expired_sessions))

    return PendingHumanSessionsResponse(total=len(tasks), items=tasks)


async def _auto_close_idle_sessions(session_ids: list[str]) -> None:
    """空闲超时：发送结束通知给玩家并清除接待状态"""
    for sid in session_ids:
        try:
            await append_agent_message(
                sid,
                "您好，由于长时间未收到您的回复，本次客服接待已自动结束。如需帮助请重新发起会话。",
            )
            await close_human_session(sid)
        except Exception:
            pass


class HumanReplyRequest(BaseModel):
    """客服发送消息请求"""
    reply: Optional[str] = Field(default=None, description="客服回复内容（close 时可为空）")
    reviewer_id: str = Field(..., description="客服标识")
    action: HumanSessionAction = Field(default="continue", description="接待操作: continue / close")


@router.post("/review/{session_id}", response_model=HumanReplyResponse)
async def send_agent_message(
    session_id: str,
    body: HumanReplyRequest,
    _token: str = Depends(require_reviewer_token),
) -> HumanReplyResponse:
    """
    客服向玩家发送消息（支持多轮）

    - action=continue → 消息写入 checkpoint，会话保持接待中
    - action=close   → 写入最后一条消息后结束接待
    """
    if not await get_pending(session_id):
        raise HumanReviewNotPendingException(session_id)

    action: HumanSessionAction = body.action if body.action in ("continue", "close") else "continue"
    processed_at = datetime.now(timezone.utc).isoformat()
    reply_text = (body.reply or "").strip()

    if action == "close":
        # 结束接待：有回复就写入，没有就只发结束通知
        if reply_text:
            await append_agent_message(session_id, reply_text)
        await append_agent_message(session_id, "本次接待已结束，感谢您的耐心等候。")
        await close_human_session(session_id)
    else:
        if not reply_text:
            raise HTTPException(status_code=422, detail="继续接待时回复内容不能为空")
        await append_agent_message(session_id, reply_text)
        pending_payload = await get_pending(session_id) or {}
        pending_payload["timestamp"] = processed_at
        pending_payload["last_agent_at"] = processed_at
        await add_pending(session_id, pending_payload)

    return HumanReplyResponse(
        success=True,
        session_id=session_id,
        action=action,
        final_response=reply_text,
        processed_at=processed_at,
    )


@router.post("/join/{session_id}")
async def join_session(
    session_id: str,
    _token: str = Depends(require_reviewer_token),
):
    """客服进入会话，发送「客服已接入」提示（每个会话只发一次）"""
    payload = await get_pending(session_id)
    if not payload:
        return {"success": False, "message": "会话不在待接待状态"}

    if payload.get("joined"):
        return {"success": True, "message": "already joined"}

    payload["joined"] = True
    await add_pending(session_id, payload)

    await append_agent_message(
        session_id,
        "【系统提示】客服已接入，请问有什么可以帮您？",
    )

    return {"success": True}


@router.get("/history/{session_id}")
async def get_human_history(
    session_id: str,
    _token: str = Depends(require_reviewer_token),
):
    """客服查看线程完整短期对话"""
    messages = await get_thread_messages(session_id)
    items = []
    for msg in messages:
        if isinstance(msg, HumanMessage):
            role = "user"
        elif isinstance(msg, AIMessage):
            role = "agent"
            if (msg.additional_kwargs or {}).get("human_source"):
                role = "human_agent"
        else:
            continue
        items.append({
            "role": role,
            "content": msg.content if isinstance(msg.content, str) else str(msg.content),
            "timestamp": (msg.additional_kwargs or {}).get("timestamp"),
        })
    return {"session_id": session_id, "messages": items, "total": len(items)}


@router.get("/status/{session_id}")
async def get_human_session_status(
    session_id: str = Path(..., description="会话ID"),
    _token: str = Depends(require_reviewer_token),
):
    """查询会话是否在人工接待中"""
    payload = await get_pending(session_id)
    if payload:
        return {
            "session_id": session_id,
            "has_pending_human": True,
            "interrupt_reason": "转人工",
            "waiting_since": payload.get("timestamp"),
        }
    return {
        "session_id": session_id,
        "has_pending_human": False,
    }

