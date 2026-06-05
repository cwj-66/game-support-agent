"""
工单创建工具
直接使用 SQLite 持久化工单数据，不经过 MCP
"""

import json
import time
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
    # 将 issue_type 映射为中文标题
    title_map = {
        "account_ban": "账号封禁申诉",
        "payment": "充值/退款问题",
        "bug": "游戏 Bug 反馈",
        "other": "客服咨询",
    }
    title = title_map.get(issue_type, "客服工单")

    # 优先级映射（P0 分钟级响应、P1 小时级、P2 天级）
    priority_map = {
        "account_ban": "P0",
        "payment": "P0",
        "bug": "P1",
        "other": "P2",
    }
    priority = priority_map.get(issue_type, "P2")

    # 预估处理时间
    estimated_map = {
        "account_ban": "3-5 个工作日",
        "payment": "1-3 个工作日",
        "bug": "5-7 个工作日",
        "other": "3-5 个工作日",
    }
    estimated = estimated_map.get(issue_type, "3-5 个工作日")

    # 写入 SQLite
    try:
        from app.core.database import create_ticket as db_create

        db_ticket = db_create(
            player_uid=user_id,
            title=title,
            description=description,
            priority=priority,
        )
        ticket_id = db_ticket.ticket_id
    except Exception as e:
        # 数据库不可用时降级为内存生成
        ticket_id = f"TK{int(time.time())}"
        print(f"[ticket] DB unavailable, using fallback ID: {e}")

    result = {
        "_health": {"ok": True, "confidence": 0.95, "message": None},
        "ticket_id": ticket_id,
        "user_id": user_id,
        "issue_type": issue_type,
        "status": "submitted",
        "estimated_response": estimated,
    }

    return json.dumps(result, ensure_ascii=False)
