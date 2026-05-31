"""
SQLite 工单数据库
应用启动时自动建表，提供工单 CRUD 操作
"""
import sqlite3
import os
import time
import random
from typing import Optional, List, Dict, Any
from contextlib import contextmanager

from app.models.ticket import Ticket, TicketStats

# 数据库文件路径，优先从 Settings 读取
def _resolve_db_path() -> str:
    try:
        from app.core.config import get_settings
        return get_settings().DB_PATH
    except Exception:
        return os.path.abspath(
            os.path.join(os.path.dirname(__file__), "..", "..", "data", "game_support.db")
        )


DB_PATH = _resolve_db_path()


def _ensure_data_dir():
    """确保 data 目录存在"""
    data_dir = os.path.dirname(DB_PATH)
    os.makedirs(data_dir, exist_ok=True)


def _generate_ticket_id() -> str:
    """生成工单号 TK-YYYYMMDD-序号"""
    date_part = time.strftime("%Y%m%d")
    rand_part = random.randint(1000, 9999)
    return f"TK-{date_part}-{rand_part}"


@contextmanager
def _get_conn():
    """获取数据库连接（上下文管理器，自动提交/关闭）"""
    _ensure_data_dir()
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db():
    """初始化数据库，创建工单表"""
    _ensure_data_dir()
    with _get_conn() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS tickets (
                ticket_id TEXT PRIMARY KEY,
                player_uid TEXT NOT NULL,
                title TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                category TEXT,
                priority TEXT DEFAULT 'P2',
                status TEXT DEFAULT 'pending',
                agent_reply TEXT,
                human_reviewed INTEGER DEFAULT 0,
                human_action TEXT,
                reviewer_id TEXT,
                interrupt_reason TEXT,
                session_id TEXT,
                tool_context TEXT,
                created_at TEXT NOT NULL,
                resolved_at TEXT
            )
        """)
        # 迁移：新增 tool_context 列（兼容已有数据库）
        try:
            conn.execute("ALTER TABLE tickets ADD COLUMN tool_context TEXT")
        except Exception:
            pass
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_tickets_status ON tickets(status)
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_tickets_player ON tickets(player_uid)
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_tickets_created ON tickets(created_at DESC)
        """)

        # 迁移：将旧版优先级值映射到 P0/P1/P2
        conn.execute("""
            UPDATE tickets SET priority = 'P0' WHERE priority IN ('urgent', 'high')
        """)
        conn.execute("""
            UPDATE tickets SET priority = 'P1' WHERE priority = 'medium'
        """)
        conn.execute("""
            UPDATE tickets SET priority = 'P2' WHERE priority IN ('low', '')
        """)


def create_ticket(
    player_uid: str,
    title: str,
    description: str,
    priority: str = "P2",
    session_id: Optional[str] = None,
) -> Ticket:
    """创建新工单，返回工单对象"""
    ticket_id = _generate_ticket_id()
    now = time.strftime("%Y-%m-%dT%H:%M:%S")
    with _get_conn() as conn:
        conn.execute(
            """INSERT INTO tickets (ticket_id, player_uid, title, description, priority, status, session_id, created_at)
               VALUES (?, ?, ?, ?, ?, 'processing', ?, ?)""",
            (ticket_id, player_uid, title, description, priority, session_id, now),
        )
    return get_ticket(ticket_id)


def get_ticket(ticket_id: str) -> Optional[Ticket]:
    """根据工单号查询工单"""
    with _get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM tickets WHERE ticket_id = ?", (ticket_id,)
        ).fetchone()
    if row is None:
        return None
    return _row_to_ticket(row)


def list_tickets(
    status: Optional[str] = None,
    player_uid: Optional[str] = None,
    page: int = 1,
    page_size: int = 20,
) -> tuple[List[Ticket], int]:
    """分页查询工单列表"""
    conditions = []
    params = []

    if status:
        conditions.append("status = ?")
        params.append(status)
    if player_uid:
        conditions.append("player_uid = ?")
        params.append(player_uid)

    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    offset = (page - 1) * page_size

    with _get_conn() as conn:
        rows = conn.execute(
            f"SELECT * FROM tickets {where} ORDER BY created_at DESC LIMIT ? OFFSET ?",
            params + [page_size, offset],
        ).fetchall()
        total_row = conn.execute(
            f"SELECT COUNT(*) as cnt FROM tickets {where}", params
        ).fetchone()
        total = total_row["cnt"] if total_row else 0

    return [_row_to_ticket(r) for r in rows], total


def update_ticket(
    ticket_id: str,
    status: Optional[str] = None,
    priority: Optional[str] = None,
    category: Optional[str] = None,
    agent_reply: Optional[str] = None,
    human_reviewed: Optional[bool] = None,
    human_action: Optional[str] = None,
    reviewer_id: Optional[str] = None,
    interrupt_reason: Optional[str] = None,
    tool_context: Optional[str] = None,
) -> Optional[Ticket]:
    """更新工单字段，只更新传入的非 None 字段"""
    sets = []
    params = []

    if status is not None:
        sets.append("status = ?")
        params.append(status)
        if status == "resolved":
            sets.append("resolved_at = ?")
            params.append(time.strftime("%Y-%m-%dT%H:%M:%S"))
    if priority is not None:
        sets.append("priority = ?")
        params.append(priority)
    if category is not None:
        sets.append("category = ?")
        params.append(category)
    if agent_reply is not None:
        sets.append("agent_reply = ?")
        params.append(agent_reply)
    if human_reviewed is not None:
        sets.append("human_reviewed = ?")
        params.append(1 if human_reviewed else 0)
    if human_action is not None:
        sets.append("human_action = ?")
        params.append(human_action)
    if reviewer_id is not None:
        sets.append("reviewer_id = ?")
        params.append(reviewer_id)
    if interrupt_reason is not None:
        sets.append("interrupt_reason = ?")
        params.append(interrupt_reason)
    if tool_context is not None:
        sets.append("tool_context = ?")
        params.append(tool_context)

    if not sets:
        return get_ticket(ticket_id)

    params.append(ticket_id)
    with _get_conn() as conn:
        conn.execute(
            f"UPDATE tickets SET {', '.join(sets)} WHERE ticket_id = ?",
            params,
        )
    return get_ticket(ticket_id)


def get_ticket_stats() -> TicketStats:
    """获取工单统计数据"""
    with _get_conn() as conn:
        total = conn.execute("SELECT COUNT(*) as cnt FROM tickets").fetchone()["cnt"]
        pending = conn.execute(
            "SELECT COUNT(*) as cnt FROM tickets WHERE status='pending'"
        ).fetchone()["cnt"]
        processing = conn.execute(
            "SELECT COUNT(*) as cnt FROM tickets WHERE status='processing'"
        ).fetchone()["cnt"]
        resolved = conn.execute(
            "SELECT COUNT(*) as cnt FROM tickets WHERE status='resolved'"
        ).fetchone()["cnt"]
        escalated = conn.execute(
            "SELECT COUNT(*) as cnt FROM tickets WHERE status='escalated'"
        ).fetchone()["cnt"]
        auto = conn.execute(
            "SELECT COUNT(*) as cnt FROM tickets WHERE status='resolved' AND human_reviewed=0"
        ).fetchone()["cnt"]
        human = conn.execute(
            "SELECT COUNT(*) as cnt FROM tickets WHERE human_reviewed=1"
        ).fetchone()["cnt"]

        # 按分类统计
        cat_rows = conn.execute(
            "SELECT category, COUNT(*) as cnt FROM tickets WHERE category IS NOT NULL GROUP BY category"
        ).fetchall()
        by_category = {r["category"]: r["cnt"] for r in cat_rows}

        # 按优先级统计
        pri_rows = conn.execute(
            "SELECT priority, COUNT(*) as cnt FROM tickets GROUP BY priority"
        ).fetchall()
        by_priority = {r["priority"]: r["cnt"] for r in pri_rows}

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


def _row_to_ticket(row: sqlite3.Row) -> Ticket:
    """将数据库行转换为 Ticket 对象"""
    # 旧版优先级向后兼容映射
    _legacy_priority_map = {"urgent": "P0", "high": "P0", "medium": "P1", "low": "P2"}
    raw_priority = row["priority"]
    priority = _legacy_priority_map.get(raw_priority, raw_priority)

    return Ticket(
        ticket_id=row["ticket_id"],
        player_uid=row["player_uid"],
        title=row["title"],
        description=row["description"],
        category=row["category"],
        priority=priority,
        status=row["status"],
        agent_reply=row["agent_reply"],
        human_reviewed=bool(row["human_reviewed"]),
        human_action=row["human_action"],
        reviewer_id=row["reviewer_id"],
        interrupt_reason=row["interrupt_reason"],
        tool_context=row["tool_context"],
        session_id=row["session_id"],
        created_at=row["created_at"],
        resolved_at=row["resolved_at"],
    )
