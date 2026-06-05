"""
结束节点
记录最终状态
"""

from datetime import datetime, timezone
from typing import Dict, Any

from langchain_core.messages import AIMessage

from ..state import AgentState


async def finish_node(state: AgentState) -> Dict[str, Any]:
    """
    结束节点
    """
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

    metadata = dict(state.get("metadata", {}))
    metadata.pop("tool_repeated_call", None)
    metadata["completed"] = True
    metadata["finished_at"] = datetime.now(timezone.utc).isoformat()

    result: Dict[str, Any] = {
        "metadata": metadata,
        "node_trace": ["finish"],
    }

    # 如果存在 human_reply（人工输入），将其作为最终回复并标记来源
    human_reply = state.get("human_reply")
    if human_reply:
        result["final_response"] = human_reply
        result["messages"] = [AIMessage(
            content=human_reply,
            additional_kwargs={"human_source": True},
        )]

    return result
