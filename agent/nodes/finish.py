"""
结束节点
记录最终状态，压缩本轮对话为一句话摘要供下一轮使用
"""

from datetime import datetime, timezone
from typing import Dict, Any

from langchain_core.messages import HumanMessage, SystemMessage

from ..state import AgentState
from app.core.llm import get_chat_model


async def finish_node(state: AgentState) -> Dict[str, Any]:
    """
    结束节点

    记录最终状态，并将本轮对话压缩为一句话摘要，
    供下一轮对话作为上下文使用。
    """
    user_query = state.get("user_query", "")
    final_response = state.get("final_response", "")

    previous_summary = state.get("session_summary") or ""
    new_summary = None

    if user_query and final_response:
        llm = get_chat_model()
        result = await llm.ainvoke([
            SystemMessage(content="你是一个对话摘要助手。请用一句话总结：用户问了什么问题、客服给出了什么解决方案。不超过50字。只输出摘要，不加任何前缀。格式参考：\"用户询问XX，客服通过XX解决了问题。\""),
            HumanMessage(content=f"用户问题：{user_query}\n客服回复：{final_response}"),
        ])
        new_summary = result.content.strip()

    if new_summary:
        session_summary = f"{previous_summary} | {new_summary}" if previous_summary else new_summary
    else:
        session_summary = previous_summary or None

    # 若有关联工单且仍在 processing，标记为 resolved
    ticket_id = state.get("ticket_id")
    if ticket_id:
        try:
            from app.core.database import update_ticket, get_ticket
            t = get_ticket(ticket_id)
            if t and t.status in ("processing", "pending"):
                update_ticket(ticket_id, status="resolved")
        except Exception:
            pass

    return {
        "session_summary": session_summary,
        "metadata": {
            **state.get("metadata", {}),
            "completed": True,
            "finished_at": datetime.now(timezone.utc).isoformat(),
        },
    }
