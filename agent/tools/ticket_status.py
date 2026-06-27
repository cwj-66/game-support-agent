"""
工单查询工具（本地兜底）
业务逻辑在 app/core/ticket_service.py，此处只做 LangChain 包装。
"""

import json
from langchain_core.tools import tool


def create_check_ticket(uid: str):
    """创建查询工单工具，注入当前玩家的 UID。

    Args:
        uid: 当前玩家 UID，由系统传入，不暴露给 LLM
    """
    @tool
    async def check_ticket(ticket_id: str = "") -> str:
        """查询工单处理进度和客服回复。

        两种情况使用此工具：
        1. 玩家主动提供了工单号（"查一下TK-xxx""帮我看看工单"）→ 传入 ticket_id
        2. 玩家问"上次的问题处理了吗""我的充值工单怎么样了"→ 不传 ticket_id，自动查该玩家最近的工单

        Args:
            ticket_id: 工单号（格式 TK-YYYYMMDD-XXXX），玩家提供了就传，否则自动查该玩家最近工单
        """
        from app.core.ticket_service import check_ticket_core
        result = check_ticket_core(uid, ticket_id)
        return json.dumps(result, ensure_ascii=False)

    return check_ticket
