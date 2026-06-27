"""
账号查询工具（本地兜底）
业务逻辑在 app/core/account_service.py，此处只做 LangChain 包装。
"""

import json
from langchain_core.tools import tool


def create_lookup_account(uid: str):
    """创建查询账号工具，注入当前玩家的 UID。

    Args:
        uid: 当前玩家 UID，由系统传入，不暴露给 LLM
    """
    @tool
    def lookup_account(fields: str = "") -> str:
        """查询当前玩家账号状态。按需传入 fields 只取需要的分类，不要获取不需要的分类。

        只能查询当前玩家自己的账号，无法查询其他玩家的信息。

        Args:
            fields: 需要返回的分类，逗号分隔，例如 "status,recharge"。
                    可用值: status（封禁状态）/ recharge（充值记录）/ login（登录信息）。
                    不传时返回全部。
        """
        from app.core.account_service import lookup_account_core
        result = lookup_account_core(uid, fields)
        return json.dumps(result, ensure_ascii=False)

    return lookup_account
