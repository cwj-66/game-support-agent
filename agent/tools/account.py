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


def create_lookup_account(uid: str):
    """创建查询账号工具，注入当前玩家的 UID。

    Args:
        uid: 当前玩家 UID，由系统传入，不暴露给 LLM
    """
    @tool
    def lookup_account() -> str:
        """查询当前玩家账号状态，包括封禁情况和充值记录。

        当玩家询问自己的账号状态、是否被封禁、充值记录时调用此工具。
        只能查询当前玩家自己的账号，无法查询其他玩家的信息。

        """
        accounts = _load_accounts()
        record = accounts.get(uid)

        if record is None:
            return json.dumps({
                "_health": {"ok": False, "confidence": 0.0, "message": f"未找到 UID {uid} 的账号信息"},
            }, ensure_ascii=False)

        return json.dumps({
            "_health": {"ok": True, "confidence": 0.9, "message": None},
            **record,
        }, ensure_ascii=False)

    return lookup_account
