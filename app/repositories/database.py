"""
工单数据库（MySQL support_tickets 表）
"""

import json
import random
import time
from datetime import datetime
from typing import Any, Optional, List

from app.models.ticket import Ticket, TicketStats
from app.core.mysql_db import get_mysql_conn


def _generate_ticket_id() -> str:
    """生成工单号 TK-YYYYMMDD-序号"""
    date_part = time.strftime("%Y%m%d")
    rand_part = random.randint(1000, 9999)
    return f"TK-{date_part}-{rand_part}"


def _dt_to_str(value: Any) -> Optional[str]:
    """将 MySQL DATETIME 转为 ISO 字符串"""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%dT%H:%M:%S")
    return str(value)


def _row_to_ticket(row: dict) -> Ticket:
    """数据库行 → Ticket 模型"""
    tool_ctx = row.get("tool_context")
    if tool_ctx is not None and not isinstance(tool_ctx, str):
        tool_ctx = json.dumps(tool_ctx, ensure_ascii=False)

    return Ticket(
        ticket_id=row["ticket_id"],
        player_uid=row["player_uid"],
        title=row["title"],
        description=row["description"],
        category=row.get("category"),
        priority=row.get("priority") or "P2",
        status=row.get("status") or "pending",
        agent_reply=row.get("agent_reply"),
        human_reviewed=bool(row.get("human_reviewed")),
        reviewer_id=row.get("reviewer_id"),
        interrupt_reason=row.get("interrupt_reason"),
        tool_context=tool_ctx,
        session_id=row.get("session_id"),
        created_at=_dt_to_str(row.get("created_at")) or "",
        resolved_at=_dt_to_str(row.get("resolved_at")),
    )


def init_db() -> None:
    """启动时探测 MySQL（表由 scripts/mysql/init.sql 初始化）"""
    from app.core.mysql_db import ping_mysql

    if not ping_mysql():
        raise RuntimeError(
            "MySQL 不可用，请执行: docker compose up -d mysql"
        )


def create_ticket(
    player_uid: str,
    title: str,
    description: str,
    priority: str = "P2",
    session_id: Optional[str] = None,
    category: Optional[str] = None,
) -> Ticket:
    """创建新工单"""
    ticket_id = _generate_ticket_id()
    with get_mysql_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO support_tickets
                    (ticket_id, player_uid, title, description, category,
                     priority, status, session_id)
                VALUES (%s, %s, %s, %s, %s, %s, 'processing', %s)
                """,
                (ticket_id, player_uid, title, description, category, priority, session_id),
            )
    ticket = get_ticket(ticket_id)
    if ticket is None:
        raise RuntimeError(f"工单创建后读取失败: {ticket_id}")
    return ticket


def get_ticket(ticket_id: str) -> Optional[Ticket]:
    """根据工单号查询"""
    with get_mysql_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM support_tickets WHERE ticket_id = %s",
                (ticket_id,),
            )
            row = cur.fetchone()
    return _row_to_ticket(row) if row else None


def list_tickets(
    status: Optional[str] = None,
    player_uid: Optional[str] = None,
    page: int = 1,
    page_size: int = 20,
) -> tuple[List[Ticket], int]:
    """分页查询工单"""
    conditions: list[str] = []
    params: list[Any] = []

    if status:
        conditions.append("status = %s")
        params.append(status)
    if player_uid:
        conditions.append("player_uid = %s")
        params.append(player_uid)

    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    offset = (page - 1) * page_size

    with get_mysql_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT * FROM support_tickets {where}
                ORDER BY created_at DESC
                LIMIT %s OFFSET %s
                """,
                params + [page_size, offset],
            )
            rows = cur.fetchall()
            cur.execute(
                f"SELECT COUNT(*) AS cnt FROM support_tickets {where}",
                params,
            )
            total = int(cur.fetchone()["cnt"])

    return [_row_to_ticket(r) for r in rows], total


def update_ticket(
    ticket_id: str,
    status: Optional[str] = None,
    priority: Optional[str] = None,
    category: Optional[str] = None,
    agent_reply: Optional[str] = None,
    human_reviewed: Optional[bool] = None,
    reviewer_id: Optional[str] = None,
    interrupt_reason: Optional[str] = None,
    tool_context: Optional[str] = None,
) -> Optional[Ticket]:
    """更新工单字段"""
    sets: list[str] = []
    params: list[Any] = []

    if status is not None:
        sets.append("status = %s")
        params.append(status)
        if status == "resolved":
            sets.append("resolved_at = NOW()")
    if priority is not None:
        sets.append("priority = %s")
        params.append(priority)
    if category is not None:
        sets.append("category = %s")
        params.append(category)
    if agent_reply is not None:
        sets.append("agent_reply = %s")
        params.append(agent_reply)
    if human_reviewed is not None:
        sets.append("human_reviewed = %s")
        params.append(1 if human_reviewed else 0)
    if reviewer_id is not None:
        sets.append("reviewer_id = %s")
        params.append(reviewer_id)
    if interrupt_reason is not None:
        sets.append("interrupt_reason = %s")
        params.append(interrupt_reason)
    if tool_context is not None:
        sets.append("tool_context = %s")
        params.append(tool_context)

    if not sets:
        return get_ticket(ticket_id)

    params.append(ticket_id)
    with get_mysql_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"UPDATE support_tickets SET {', '.join(sets)} WHERE ticket_id = %s",
                params,
            )
    return get_ticket(ticket_id)


def get_ticket_stats() -> TicketStats:
    """工单统计（客服后台用）"""
    with get_mysql_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) AS cnt FROM support_tickets")
            total = cur.fetchone()["cnt"]
            cur.execute(
                "SELECT COUNT(*) AS cnt FROM support_tickets WHERE status='pending'"
            )
            pending = cur.fetchone()["cnt"]
            cur.execute(
                "SELECT COUNT(*) AS cnt FROM support_tickets WHERE status='processing'"
            )
            processing = cur.fetchone()["cnt"]
            cur.execute(
                "SELECT COUNT(*) AS cnt FROM support_tickets WHERE status='resolved'"
            )
            resolved = cur.fetchone()["cnt"]
            cur.execute(
                "SELECT COUNT(*) AS cnt FROM support_tickets WHERE status='escalated'"
            )
            escalated = cur.fetchone()["cnt"]
            cur.execute(
                """
                SELECT COUNT(*) AS cnt FROM support_tickets
                WHERE status='resolved' AND human_reviewed=0
                """
            )
            auto = cur.fetchone()["cnt"]
            cur.execute(
                "SELECT COUNT(*) AS cnt FROM support_tickets WHERE human_reviewed=1"
            )
            human = cur.fetchone()["cnt"]
            cur.execute(
                """
                SELECT category, COUNT(*) AS cnt FROM support_tickets
                WHERE category IS NOT NULL GROUP BY category
                """
            )
            by_category = {r["category"]: r["cnt"] for r in cur.fetchall()}
            cur.execute(
                "SELECT priority, COUNT(*) AS cnt FROM support_tickets GROUP BY priority"
            )
            by_priority = {r["priority"]: r["cnt"] for r in cur.fetchall()}

    return TicketStats(
        total=total,
        pending=pending,
        processing=processing,
        resolved=resolved,
        escalated=escalated,
        auto_resolved=auto,
        human_reviewed=human,
        by_category=by_category,
        by_priority=by_priority,
    )
