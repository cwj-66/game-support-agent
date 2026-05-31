"""查询账号状态（从 data/accounts.json 读取 mock 数据）"""

import json
import os
from langchain_core.tools import tool

_ACCOUNTS_CACHE = None

# 可查询的分类，每种对应一组字段
_FIELD_GROUPS = {
    "status":  ["status", "ban_reason"],
    "recharge": ["recharge_total", "abnormal_detail"],
    "login":   ["last_login"],
}


def _load_accounts() -> dict:
    global _ACCOUNTS_CACHE
    if _ACCOUNTS_CACHE is None:
        path = os.path.join(
            os.path.dirname(__file__), "../../data/accounts.json"
        )
        with open(path, encoding="utf-8") as f:
            _ACCOUNTS_CACHE = json.load(f)
    return _ACCOUNTS_CACHE


def create_lookup_account(uid: str):
    """创建查询账号工具，注入当前玩家的 UID。

    Args:
        uid: 当前玩家 UID，由系统传入，不暴露给 LLM
    """
    def _parse_fields(raw: str) -> list[str]:
        """兼容 LLM 传 '["status","login"]' 和 "status,login" 两种格式"""
        raw = raw.strip()
        if not raw:
            return []
        if raw.startswith("["):
            try:
                return json.loads(raw)
            except json.JSONDecodeError:
                pass
        return [g.strip() for g in raw.split(",") if g.strip()]


    @tool
    def lookup_account(fields: str = "") -> str:
        """查询当前玩家账号状态。按需传入 fields 只取需要的分类，不要获取不需要的分类。

        只能查询当前玩家自己的账号，无法查询其他玩家的信息。

        Args:
            fields: 需要返回的分类，逗号分隔，例如 "status,recharge"。可用值: status（封禁状态）, recharge（充值记录）, login（登录信息）。不传时返回全部。
        """
        accounts = _load_accounts()
        record = accounts.get(uid)

        if record is None:
            return json.dumps({"status": "unknown", "ban_reason": None}, ensure_ascii=False)

        groups = _parse_fields(fields)
        if groups:
            result = {}
            for group in groups:
                for f in _FIELD_GROUPS.get(group.strip(), []):
                    if f in record:
                        result[f] = record[f]
            return json.dumps(result, ensure_ascii=False)

        # 不传 fields 时返回全部
        result = {}
        for group_fields in _FIELD_GROUPS.values():
            for f in group_fields:
                if f in record:
                    result[f] = record[f]
        return json.dumps(result, ensure_ascii=False)

    return lookup_account
