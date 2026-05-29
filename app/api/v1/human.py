"""
人工审核操作API
审核员对Agent输出进行APPROVE/MODIFY/OVERRIDE操作
"""

from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Path
from langgraph.types import Command

from app.core.exceptions import (
    HumanReviewNotPendingException,
    ValidationException
)
from app.core.pending_store import (
    get_all_pending,
    remove_pending,
    get_pending,
)
from app.models.review import (
    ReviewAction,
    ReviewResponse,
    PendingReviewsResponse,
    ReviewTask,
    ReviewHistoryResponse,
)
from agent.graph import get_graph
from agent.state import HumanReviewResult


router = APIRouter(prefix="/human", tags=["人工审核"])


def _graph_config(session_id: str) -> dict:
    """构建 LangGraph 恢复执行所需的 config"""
    return {
        "configurable": {
            "thread_id": session_id,
            "checkpoint_ns": "game_support_agent",
        }
    }


@router.get("/pending", response_model=PendingReviewsResponse)
async def list_pending_reviews() -> PendingReviewsResponse:
    """
    获取待审核任务列表

    从内存公告板读取所有处于 interrupt 挂起状态的会话
    """
    pending = get_all_pending()
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
        ))

    return PendingReviewsResponse(total=len(tasks), items=tasks)


@router.post("/review/{session_id}", response_model=ReviewResponse)
async def submit_review(
    session_id: str,
    action: ReviewAction,
) -> ReviewResponse:
    """
    提交人工审核操作

    三种操作类型：
    - APPROVE: 原样通过Agent的回复
    - MODIFY: 修改后通过
    - OVERRIDE: 人工完全重写回复

    流程：
    1. 验证 session 处于挂起状态
    2. 调用 graph.ainvoke(Command(resume=...)) 恢复图执行
    3. 从公告板移除该会话
    4. 返回最终结果
    """
    # 校验会话是否在等待审核
    if not get_pending(session_id):
        raise HumanReviewNotPendingException(session_id)

    # MODIFY / OVERRIDE 必须提供修改内容
    if action.action in ("MODIFY", "OVERRIDE") and not action.modified_content:
        raise ValidationException(
            "MODIFY 和 OVERRIDE 操作必须提供 modified_content",
            field="modified_content",
        )

    # 构建恢复数据 —— 必须与 HumanReviewResult 字段一致
    resume_data: HumanReviewResult = {
        "action": action.action,
        "reviewer_id": action.reviewer_id,
        "modified_content": action.modified_content,
        "notes": action.notes,
    }

    # 恢复图执行，human_node 从 interrupt() 处继续运行
    g = await get_graph()
    result = await g.ainvoke(
        Command(resume=resume_data),
        config=_graph_config(session_id),
    )

    # 审核完成，从公告板移除
    remove_pending(session_id)

    final_response = result.get("final_response", "[人工处理完成]")
    processed_at = datetime.now(timezone.utc).isoformat()

    return ReviewResponse(
        success=True,
        review_id=f"rev_{session_id}",
        session_id=session_id,
        action=action.action,
        final_response=final_response,
        processed_at=processed_at,
    )


@router.get("/status/{session_id}")
async def get_review_status(
    session_id: str = Path(..., description="会话ID"),
):
    """
    查询会话的审核状态

    返回：
    - 是否需要审核
    - 当前审核进度
    """
    payload = get_pending(session_id)
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
    reviewer_id: Optional[str] = None,
    limit: int = 50,
) -> ReviewHistoryResponse:
    """
    获取审核历史

    当前返回空列表，等 AuditLogger 支持按审核员查询后接入
    """
    # TODO: 从 AuditLogger 读取审核历史
    return ReviewHistoryResponse(total=0, items=[])
