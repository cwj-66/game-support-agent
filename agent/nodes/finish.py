"""
结束节点
记录最终状态
"""

from datetime import datetime, timezone
from typing import Dict, Any

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

    return {
        "metadata": {
            **state.get("metadata", {}),
            "completed": True,
            "finished_at": datetime.now(timezone.utc).isoformat(),
        },
    }
