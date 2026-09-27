"""工单业务逻辑：issue_type 映射与数据库调用。"""

TITLE_MAP = {
    "account_ban": "账号封禁申诉",
    "payment": "充值/退款问题",
    "bug": "游戏 Bug 反馈",
    "other": "客服咨询",
}

PRIORITY_MAP = {
    "account_ban": "P0",
    "payment": "P0",
    "bug": "P1",
    "other": "P2",
}

ESTIMATED_MAP = {
    "account_ban": "3-5 个工作日",
    "payment": "1-3 个工作日",
    "bug": "5-7 个工作日",
    "other": "3-5 个工作日",
}


def create_ticket_core(user_id: str, issue_type: str, description: str) -> dict:
    """创建工单：仅在数据库写入并读回工单后返回成功。"""
    title = TITLE_MAP.get(issue_type, "客服工单")
    priority = PRIORITY_MAP.get(issue_type, "P2")
    estimated = ESTIMATED_MAP.get(issue_type, "3-5 个工作日")

    try:
        from app.repositories.database import create_ticket as db_create
        db_ticket = db_create(
            player_uid=user_id,
            title=title,
            description=description,
            priority=priority,
        )
        ticket_id = db_ticket.ticket_id
        if not ticket_id:
            raise RuntimeError("数据库未返回工单号")
    except Exception as e:
        return {
            "user_id": user_id,
            "issue_type": issue_type,
            "status": "failed",
            "error": "工单创建失败，请稍后重试。",
            "_health": {"ok": False, "confidence": 0.0, "message": str(e)},
        }

    return {
        "ticket_id": ticket_id,
        "user_id": user_id,
        "issue_type": issue_type,
        "status": "submitted",
        "estimated_response": estimated,
        "_health": {"ok": True, "confidence": 0.95, "message": None},
    }


def check_ticket_core(user_id: str, ticket_id: str = "") -> dict:
    """查询工单：按 ticket_id 精确查，或按 user_id 查最近 5 条。"""
    try:
        from app.repositories.database import get_ticket, list_tickets

        if ticket_id:
            ticket = get_ticket(ticket_id)
            if ticket is None or ticket.player_uid != user_id:
                return {
                    "found": False,
                    "status": "not_found",
                    "message": f"工单 {ticket_id} 不存在，此为最终结果，请勿重复查询",
                    "do_not_retry": True,
                }
            return {
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
            }

        tickets, total = list_tickets(player_uid=user_id, page_size=5)
        items = [
            {
                "ticket_id": t.ticket_id,
                "title": t.title,
                "status": t.status,
                "priority": t.priority,
                "created_at": t.created_at,
                "resolved_at": t.resolved_at,
                "agent_reply": t.agent_reply or "",
            }
            for t in tickets
        ]
        return {"total": total, "tickets": items}

    except Exception as e:
        return {"found": False, "error": str(e)}
