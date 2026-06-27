"""
账号查询业务逻辑服务层

将字段分组、JSON 加载、字段过滤逻辑集中在此处，
避免在 agent/tools/account.py（本地兜底）和 mcp_server.py（MCP 暴露）中重复编写。
"""

import json
import os

# 可查询的字段分组（只维护这一份）
FIELD_GROUPS = {
    "status": ["status", "ban_reason"],
    "recharge": ["recharge_total", "abnormal_detail"],
    "login": ["last_login"],
}

_ACCOUNTS_CACHE = None


def _load_accounts() -> dict:
    """加载账号 JSON 数据（带缓存，只读一次）"""
    global _ACCOUNTS_CACHE
    if _ACCOUNTS_CACHE is None:
        path = os.path.join(
            os.path.dirname(__file__), "..", "..", "data", "accounts.json"
        )
        with open(os.path.abspath(path), encoding="utf-8") as f:
            _ACCOUNTS_CACHE = json.load(f)
    return _ACCOUNTS_CACHE


def lookup_account_core(user_id: str, fields: str = "") -> dict:
    """账号查询核心逻辑：加载数据 → 按 fields 过滤 → 返回 dict。

    Args:
        user_id: 玩家 UID
        fields: 逗号分隔的分组名，可选值 status / recharge / login。不传则返回全部。

    Returns:
        字段 dict，找不到用户时返回 {"status": "unknown", "ban_reason": None}
    """
    try:
        accounts = _load_accounts()
    except Exception as e:
        return {"error": f"账号数据读取失败: {e}"}

    record = accounts.get(user_id)
    if record is None:
        return {"status": "unknown", "ban_reason": None}

    groups = [g.strip() for g in fields.split(",") if g.strip()] if fields else []

    if groups:
        result = {}
        for group in groups:
            for f in FIELD_GROUPS.get(group, []):
                if f in record:
                    result[f] = record[f]
        return result

    # 不传 fields → 返回全部字段
    result = {}
    for group_fields in FIELD_GROUPS.values():
        for f in group_fields:
            if f in record:
                result[f] = record[f]
    return result
