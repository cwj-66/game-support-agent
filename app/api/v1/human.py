"""
人工审核操作API
审核员对Agent输出进行审核（reply 字符串恢复图执行）
"""

from datetime import datetime, timezone
from typing import Optional

import asyncio

from fastapi import APIRouter, Depends, Header, HTTPException, Path
from langgraph.types import Command
from pydantic import BaseModel, Field

from app.core.config import get_settings
from app.core.exceptions import (
    HumanReviewNotPendingException,
)
from app.core.pending_store import (
    get_all_pending,
    remove_pending,
    get_pending,
)
from app.models.review import (
    ReviewResponse,
    PendingReviewsResponse,
    ReviewTask,
    ReviewHistoryResponse,
)
from agent.graph import get_sync_graph


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


def _graph_config(session_id: str) -> dict:
    """构建 LangGraph 恢复执行所需的 config"""
    return {
        "configurable": {
            "thread_id": session_id,
            "checkpoint_ns": "game_support_agent",
        }
    }


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
    """人工审核回复请求：简化版，审核员直接输入回复内容"""
    reply: str = Field(..., description="人工回复内容")
    reviewer_id: str = Field(..., description="审核员标识")


@router.post("/review/{session_id}", response_model=ReviewResponse)
async def submit_review(
    session_id: str,
    body: HumanReplyRequest,
    _token: str = Depends(require_reviewer_token),
) -> ReviewResponse:
    """
    提交人工审核结果

    流程：
    1. 验证 session 处于挂起状态
    2. 将审核员的回复字符串传给 graph.invoke(Command(resume=...))
       （RedisSaver 支持同步操作，通过线程池避免阻塞事件循环）
    3. 从公告板移除该会话
    4. 返回最终结果
    """
    # 校验会话是否在等待审核
    if not await get_pending(session_id):
        raise HumanReviewNotPendingException(session_id)

    # 恢复图执行，human_node 从 interrupt() 处继续运行
    # RedisSaver 支持同步 invoke，通过线程池避免阻塞事件循环
    g = get_sync_graph()
    result = await asyncio.to_thread(
        g.invoke,
        Command(resume=body.reply),
        _graph_config(session_id),
    )

    # 审核完成，从公告板移除
    await remove_pending(session_id)

    final_response = result.get("final_response", body.reply)
    processed_at = datetime.now(timezone.utc).isoformat()

    return ReviewResponse(
        success=True,
        review_id=f"rev_{session_id}",
        session_id=session_id,
        action="APPROVE",
        final_response=final_response,
        processed_at=processed_at,
    )


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
