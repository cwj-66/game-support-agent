"""
Human-in-loop 核心节点
使用LangGraph的interrupt()实现真正的断点暂停
保存完整状态到checkpointer，支持人工操作后恢复
"""

from datetime import datetime, timezone
from typing import Dict, Any, Optional
from langgraph.types import interrupt

from ..state import AgentState, HumanReviewResult
from human_in_loop.reviewer import HumanReviewer, ReviewContext, ReviewActionType


# 人工审核节点，触发中断并等待人工介入
async def human_node(state: AgentState) -> Dict[str, Any]:
    """
    人工审核节点：触发中断并等待人工介入

    这是Human-in-loop机制的核心实现：
    1. 使用LangGraph的interrupt()暂停图执行
    2. 保存完整AgentState到checkpointer
    3. 等待人工操作（APPROVE/MODIFY/OVERRIDE）
    4. 恢复执行后由 HumanReviewer 引擎处理审核逻辑与日志

    节点流程：
    - 进入 → 触发interrupt → 状态持久化 → 等待人工操作
    - 人工操作 → 读取状态 → HumanReviewer.review() → 返回状态更新

    Args:
        state: 当前Agent状态（包含final_response等待审核）

    Returns:
        应用人工审核结果后的状态更新

    TODO:
    - 实现状态恢复时的校验逻辑
    - 添加超时处理（人工长时间未响应）
    """
    session_id = state["session_id"]
    user_query = state.get("user_query", "")
    final_response = state.get("final_response", "")
    interrupt_info = state.get("interrupt_info") or {}

    # 如果从 escalate 路径进入（未经过 generate），final_response 为空
    # 优先用对话历史中最后一条纯文本 AIMessage，否则用中断原因兜底
    if not final_response:
        from langchain_core.messages import AIMessage
        for msg in reversed(state.get("messages", [])):
            if isinstance(msg, AIMessage):
                content = getattr(msg, "content", "")
                if content and isinstance(content, str) and not getattr(msg, "tool_calls", None):
                    final_response = content
                    break
        if not final_response:
            final_response = f"[Agent未生成回复] 中断原因：{interrupt_info.get('reason', '未知')}"

    # 准备中断载荷，推送给前端展示
    interrupt_payload = {
        "session_id": session_id,
        "user_query": user_query,
        "content": final_response,
        "interrupt_reason": interrupt_info.get("reason"),
        "interrupt_level": interrupt_info.get("level"),
        "source": interrupt_info.get("source"),
        "waiting_for": "human_review",
        "options": ["APPROVE", "MODIFY", "OVERRIDE"],
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    # 触发 LangGraph interrupt，图执行在此挂起
    # 外部通过 graph.ainvoke(Command(resume=...)) 恢复时传入人工审核数据
    print(f"[Human Node] 触发中断，等待人工审核: {session_id}")
    human_result: HumanReviewResult = interrupt(interrupt_payload)

    # ── 组装 ReviewContext ─────────────────────────────────────
    context = ReviewContext(
        session_id=session_id,
        user_query=user_query,
        agent_response=final_response,
        interrupt_reason=interrupt_info.get("reason", ""),
        risk_level=interrupt_info.get("level", "medium"),
        metadata=state.get("metadata", {}),
    )

    # ── 解析人工传回的操作参数 ─────────────────────────────────
    action_str = human_result.get("action", "APPROVE")
    try:
        action = ReviewActionType(action_str)
    except ValueError:
        action = ReviewActionType.APPROVE

    reviewer_id = human_result.get("reviewer_id", "unknown")
    modified_content = human_result.get("modified_content")
    notes = human_result.get("notes")

    # ── 调用 HumanReviewer 引擎（含审计日志）──────────────────
    reviewer = HumanReviewer()
    review_result = await reviewer.review(
        context=context,
        action=action,
        reviewer_id=reviewer_id,
        modified_content=modified_content,
        notes=notes,
    )

    # ── 若有关联工单，回写审核结果 ────────────────────────────
    ticket_id = state.get("ticket_id")
    if ticket_id:
        try:
            from app.core.database import update_ticket
            update_ticket(
                ticket_id,
                status="resolved",
                human_reviewed=True,
                human_action=action_str,
                reviewer_id=reviewer_id,
                interrupt_reason=interrupt_info.get("reason"),
            )
        except Exception:
            pass

    # ── 打包 LangGraph 状态更新 ────────────────────────────────
    return {
        "human_review": human_result,
        "final_response": review_result["final_response"],
        "messages": [],
        "node_trace": ["human"],
        "metadata": {
            **state.get("metadata", {}),
            "human_review_applied": True,
            "review_action": review_result["action"],
            "was_modified": review_result.get("was_modified", False),
            "processed_at": review_result.get("timestamp"),
            "reviewer_id": reviewer_id,
        },
    }


def check_resume_state(state: AgentState) -> Optional[Dict[str, Any]]:
    """
    检查是否需要从断点恢复

    在图重新启动时调用，检查是否存在待恢复的中断状态

    Args:
        state: 当前传入的状态

    Returns:
        如果是恢复状态，返回恢复数据；否则None

    TODO:
    - 实现与checkpointer的集成
    - 添加状态完整性校验
    """
    metadata = state.get("metadata", {})
    if metadata.get("resuming_from_interrupt"):
        return {
            "resumed": True,
            "previous_checkpoint": metadata.get("checkpoint_id"),
        }
    return None


# TODO: 未来扩展
# - 实现超时自动拒绝机制
# - 添加多轮人工审核支持
# - 实现审核结果的事后分析
