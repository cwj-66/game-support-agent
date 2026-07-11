"""
人工接待操作 API
支持客服多轮与玩家对话，以及结束接待（action=close）。
消息直接写入 checkpoint，不经过 LangGraph interrupt。
"""

from datetime import datetime, timezone
from typing import Literal

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

    tasks: list[PendingHumanSession] = []
    for session_id, payload in pending.items():
        created_at = payload.get("timestamp", now.isoformat())
        try:
            elapsed = (now - datetime.fromisoformat(created_at)).total_seconds()
        except (ValueError, TypeError):
            elapsed = 0

        tasks.append(PendingHumanSession(
            session_id=session_id,
            user_query=payload.get("user_query", ""),
            agent_response=payload.get("summary", ""),
            interrupt_reason="转人工",
            risk_level="high",
            created_at=created_at,
            wait_time_seconds=int(elapsed),
            pending_content=payload.get("summary"),
        ))

    return PendingHumanSessionsResponse(total=len(tasks), items=tasks)


class HumanReplyRequest(BaseModel):
    """客服发送消息请求"""
    reply: str = Field(..., description="客服回复内容")
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

    await append_agent_message(session_id, body.reply)

    processed_at = datetime.now(timezone.utc).isoformat()

    if action == "close":
        await close_human_session(session_id)
    else:
        pending_payload = await get_pending(session_id) or {}
        pending_payload["timestamp"] = processed_at
        await add_pending(session_id, pending_payload)

    return HumanReplyResponse(
        success=True,
        session_id=session_id,
        action=action,
        final_response=body.reply,
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

