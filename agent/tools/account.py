"""查询账号状态（从 data/accounts.json 读取 mock 数据）"""

import json
import os
from langchain_core.tools import tool

_ACCOUNTS_CACHE = None


def _load_accounts() -> dict:
    global _ACCOUNTS_CACHE
    if _ACCOUNTS_CACHE is None:
        path = os.path.join(
            os.path.dirname(__file__), "../../data/accounts.json"
        )
        with open(path, encoding="utf-8") as f:
            _ACCOUNTS_CACHE = json.load(f)
    return _ACCOUNTS_CACHE


@tool
def lookup_account(user_id: str) -> str:
    """查询玩家账号状态，包括封禁情况和充值记录。

    当用户询问自己的账号状态、是否被封禁、充值记录时调用此工具。
    若查到 status 为 banned，请先告知用户封禁原因（ban_reason），
    然后询问是否需要创建申诉工单，待用户确认后再调 create_ticket。

    Args:
        user_id: 玩家 UID（用户提供的数字即为UID，如"221"、"id12345"）
    """
    accounts = _load_accounts()
    record = accounts.get(user_id)

    if record is None:
        return json.dumps({
            "_health": {"ok": False, "confidence": 0.0, "message": f"未找到 UID {user_id} 的账号信息"},
        }, ensure_ascii=False)

    return json.dumps({
        "_health": {"ok": True, "confidence": 0.9, "message": None},
        **record,
    }, ensure_ascii=False)
