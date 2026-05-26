"""
工单查询工具
供 LLM 在用户询问工单进度时查询
"""

import json
from langchain_core.tools import tool


@tool
def check_ticket(ticket_id: str = "", user_id: str = "") -> str:
    """查询工单处理进度和客服回复。

    两种情况使用此工具：
    1. 用户主动提供了工单号（"查一下TK-xxx""帮我看看工单"）→ 传入 ticket_id
    2. 用户问"上次的问题处理了吗""我的充值工单怎么样了"→ 先在对话历史中找工单号传入；
       如果历史中找不到，传入 user_id 查询该用户最近的工单。

    Args:
        ticket_id: 工单号（格式 TK-YYYYMMDD-XXXX），用户提供了就传，否则从历史中找
        user_id: 玩家 UID，找不到工单号时用此查该用户所有工单
    """
    try:
        from app.core.database import get_ticket, list_tickets

        # 优先用工单号查
        if ticket_id:
            ticket = get_ticket(ticket_id)
            if ticket is None:
                return json.dumps(
                    {"found": False, "message": f"工单 {ticket_id} 不存在"},
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

        # 没有工单号，用用户 ID 查最近工单
        if user_id:
            tickets, total = list_tickets(player_uid=user_id, page_size=5)
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

        return json.dumps(
            {"found": False, "message": "请提供工单号或用户ID"},
            ensure_ascii=False,
        )

    except Exception as e:
        return json.dumps(
            {"found": False, "error": str(e)}, ensure_ascii=False
        )
