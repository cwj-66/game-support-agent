"""
工单创建工具
通过 MCP 协议写入 SQLite 数据库，不再直接 import sqlite3
"""

import json
import time
import random
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

    如果后续仍需要升人工，必须先调 create_ticket 创建工单，再调
    escalate_to_human 并在 reason 参数中带上工单号，方便客服交接。

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

    # 生成工单号（与 app.core.database 逻辑保持一致）
    ticket_id = f"TK-{time.strftime('%Y%m%d')}-{random.randint(1000, 9999)}"
    now = time.strftime("%Y-%m-%dT%H:%M:%S")

    # 通过 MCP 写入 SQLite
    try:
        from agent.tools.mcp_client import mcp_write_query, _sqlesc

        await mcp_write_query(
            f"INSERT INTO tickets "
            f"(ticket_id, player_uid, title, description, priority, status, created_at) "
            f"VALUES ("
            f"'{_sqlesc(ticket_id)}', "
            f"'{_sqlesc(user_id)}', "
            f"'{_sqlesc(title)}', "
            f"'{_sqlesc(description)}', "
            f"'{_sqlesc(priority)}', "
            f"'processing', "
            f"'{_sqlesc(now)}')"
        )
    except Exception as e:
        # MCP 不可用时降级为直接写 SQLite（通过 app.core.database）
        print(f"[ticket] MCP unavailable, falling back to direct DB write: {e}")
        from app.core.database import create_ticket
        db_ticket = create_ticket(
            player_uid=user_id,
            title=title,
            description=description,
            priority=priority,
        )
        ticket_id = db_ticket.ticket_id

    result = {
        "_health": {"ok": True, "confidence": 0.95, "message": None},
        "ticket_id": ticket_id,
        "user_id": user_id,
        "issue_type": issue_type,
        "status": "submitted",
        "estimated_response": estimated,
    }

    return json.dumps(result, ensure_ascii=False)
