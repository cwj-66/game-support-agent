"""
账号查询业务逻辑服务层
"""

from typing import Any, Optional

from app.core.mysql_db import get_mysql_conn

# 可查询的字段分组
FIELD_GROUPS = {
    "status": ["status", "ban_reason"],
    "recharge": ["recharge_total", "abnormal_detail"],
    "login": ["last_login"],
    "profile": ["nickname", "server_id", "level", "vip_level"],
}


def _fetch_player_mysql(user_id: str) -> Optional[dict[str, Any]]:
    """从 MySQL game_players 读取一条记录"""
    with get_mysql_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM game_players WHERE uid = %s",
                (user_id,),
            )
            row = cur.fetchone()
    if not row:
        return None

    last_login = row.get("last_login")
    if last_login is not None and hasattr(last_login, "strftime"):
        last_login = last_login.strftime("%Y-%m-%dT%H:%M:%SZ")

    return {
        "uid": row["uid"],
        "nickname": row.get("nickname"),
        "server_id": row.get("server_id"),
        "level": row.get("level"),
        "vip_level": row.get("vip_level"),
        "status": row.get("status"),
        "ban_reason": row.get("ban_reason"),
        "recharge_total": float(row.get("recharge_total") or 0),
        "abnormal_detail": row.get("abnormal_detail"),
        "last_login": last_login,
    }


def _filter_fields(record: dict[str, Any], fields: str) -> dict[str, Any]:
    """按 fields 分组过滤返回字段"""
    groups = [g.strip() for g in fields.split(",") if g.strip()] if fields else []

    if groups:
        result: dict[str, Any] = {}
        for group in groups:
            for f in FIELD_GROUPS.get(group, []):
                if f in record:
                    result[f] = record[f]
        return result

    result = {}
    for group_fields in FIELD_GROUPS.values():
        for f in group_fields:
            if f in record:
                result[f] = record[f]
    return result


def lookup_account_core(user_id: str, fields: str = "") -> dict:
    """账号查询：只读 MySQL。"""
    try:
        record = _fetch_player_mysql(user_id)
    except Exception as e:
        return {"error": f"账号数据库不可用: {e}"}

    if record is None:
        return {"status": "unknown", "ban_reason": None}

    return _filter_fields(record, fields)
