"""
工单查询工具
直接使用 SQLite 查询工单数据，不经过 MCP
"""

import json
from langchain_core.tools import tool


def create_check_ticket(uid: str):
    """创建查询工单工具，注入当前玩家的 UID。

    Args:
        uid: 当前玩家 UID，由系统传入，不暴露给 LLM
    """
    @tool
    async def check_ticket(ticket_id: str = "") -> str:
        """查询工单处理进度和客服回复。

        两种情况使用此工具：
        1. 玩家主动提供了工单号（"查一下TK-xxx""帮我看看工单"）→ 传入 ticket_id
        2. 玩家问"上次的问题处理了吗""我的充值工单怎么样了"→ 不传 ticket_id，自动查该玩家最近的工单

        Args:
            ticket_id: 工单号（格式 TK-YYYYMMDD-XXXX），玩家提供了就传，否则自动查该玩家最近工单
        """
        try:
            from app.core.database import get_ticket, list_tickets

            # 优先用工单号查
            if ticket_id:
                ticket = get_ticket(ticket_id)
                if ticket is None:
                    return json.dumps(
                        {
                            "status": "not_found",
                            "found": False,
                            "message": f"工单 {ticket_id} 不存在，此为最终结果，请勿重复查询",
                            "do_not_retry": True,
                        },
                        ensure_ascii=False,
                    )
                return json.dumps(
                    {
                        "found": True,
                        "ticket_id": ticket.ticket_id,
                        "title": ticket.title,
                        "description": ticket.description,
                        "status": ticket.status,
                        "priority": ticket.priority,
                        "created_at": ticket.created_at,
                        "resolved_at": ticket.resolved_at,
                        "agent_reply": ticket.agent_reply or "",
                        "human_reviewed": ticket.human_reviewed,
                    },
                    ensure_ascii=False,
                )

            # 没有工单号，用当前玩家 UID 查最近工单
            tickets, total = list_tickets(player_uid=uid, page_size=5)
            items = []
            for t in tickets:
                items.append(
                    {
                        "ticket_id": t.ticket_id,
                        "title": t.title,
                        "status": t.status,
                        "priority": t.priority,
                        "created_at": t.created_at,
                        "resolved_at": t.resolved_at,
                        "agent_reply": t.agent_reply or "",
                    }
                )
            return json.dumps(
                {"total": total, "tickets": items}, ensure_ascii=False
            )

        except Exception as e:
            return json.dumps(
                {"found": False, "error": str(e)}, ensure_ascii=False
            )

    return check_ticket
