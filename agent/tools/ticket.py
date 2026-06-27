"""
工单创建工具（本地兜底）
业务逻辑在 app/core/ticket_service.py，此处只做 LangChain 包装。
"""

import json
from langchain_core.tools import tool


@tool
async def create_ticket(user_id: str, issue_type: str, description: str) -> str:
    """为玩家创建客服工单，适用于需要后台异步处理的问题（封禁申诉、支付退款、Bug 反馈等）。
    创建工单后直接结束对话，无需同时触发升人工。

    issue_type 枚举值：
    - account_ban：账号封禁申诉
    - payment：充值/退款问题
    - bug：游戏 bug 反馈
    - other：其他问题

    Args:
        user_id: 玩家 UID
        issue_type: 问题类型，见上方枚举值
        description: 问题描述
    """
    from app.core.ticket_service import create_ticket_core
    result = create_ticket_core(user_id, issue_type, description)
    return json.dumps(result, ensure_ascii=False)
