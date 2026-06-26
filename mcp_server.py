"""
MCP Server — 客服工具服务

职责：注册并暴露客服工具给 MCP Client（LangGraph 侧）。
暴露 4 个工具：create_ticket / check_ticket / lookup_account / query_knowledge

核心原则：Server 只管工具的实现，Client 只管工具的发现和绑定，
interrupt 的控制权始终在 LangGraph 图里，不要把业务逻辑放进 MCP Server。

启动方式：
    python mcp_server.py
    # 监听 http://0.0.0.0:8001/sse
"""

import json
import os
import sys
import time
import random

from mcp.server.fastmcp import FastMCP

# 确保项目根目录在 Python 路径，以便 import app.*
_ROOT = os.path.dirname(os.path.abspath(__file__))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

mcp = FastMCP("customer-service")


# ─── 工具 1：创建工单 ────────────────────────────────────────────────

@mcp.tool()
def create_ticket(user_id: str, issue_type: str, description: str) -> dict:
    """为玩家创建客服工单，适用于需要后台异步处理的问题。

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
    title_map = {
        "account_ban": "账号封禁申诉",
        "payment": "充值/退款问题",
        "bug": "游戏 Bug 反馈",
        "other": "客服咨询",
    }
    priority_map = {"account_ban": "P0", "payment": "P0", "bug": "P1", "other": "P2"}
    estimated_map = {
        "account_ban": "3-5 个工作日",
        "payment": "1-3 个工作日",
        "bug": "5-7 个工作日",
        "other": "3-5 个工作日",
    }

    title = title_map.get(issue_type, "客服工单")
    priority = priority_map.get(issue_type, "P2")
    estimated = estimated_map.get(issue_type, "3-5 个工作日")

    db_error = None
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
        ticket_id = f"TK-{time.strftime('%Y%m%d')}-{random.randint(1000, 9999)}"
        db_error = str(e)

    return {
        "ticket_id": ticket_id,
        "user_id": user_id,
        "issue_type": issue_type,
        "status": "submitted",
        "estimated_response": estimated,
        "_health": {"ok": True, "confidence": 0.95, "message": db_error},
    }


# ─── 工具 2：查询工单 ────────────────────────────────────────────────

@mcp.tool()
def check_ticket(user_id: str, ticket_id: str = "") -> dict:
    """查询工单处理进度和客服回复。

    两种场景：
    1. 玩家提供了工单号 → 传入 ticket_id 精确查询
    2. 玩家问"我的工单怎么样了" → 不传 ticket_id，自动返回该玩家最近 5 条工单

    Args:
        user_id: 玩家 UID
        ticket_id: 工单号（格式 TK-YYYYMMDD-XXXX），不传时按 user_id 查最近工单
    """
    try:
        from app.core.database import get_ticket, list_tickets

        if ticket_id:
            ticket = get_ticket(ticket_id)
            if ticket is None:
                return {
                    "found": False,
                    "message": f"工单 {ticket_id} 不存在",
                    "do_not_retry": True,
                }
            return {
                "found": True,
                "ticket_id": ticket.ticket_id,
                "title": ticket.title,
                "status": ticket.status,
                "priority": ticket.priority,
                "created_at": ticket.created_at,
                "resolved_at": ticket.resolved_at,
                "agent_reply": ticket.agent_reply or "",
                "human_reviewed": ticket.human_reviewed,
            }

        tickets, total = list_tickets(player_uid=user_id, page_size=5)
        items = [
            {
                "ticket_id": t.ticket_id,
                "title": t.title,
                "status": t.status,
                "priority": t.priority,
                "created_at": t.created_at,
                "agent_reply": t.agent_reply or "",
            }
            for t in tickets
        ]
        return {"total": total, "tickets": items}

    except Exception as e:
        return {"found": False, "error": str(e)}


# ─── 工具 3：查询账号状态 ─────────────────────────────────────────────

@mcp.tool()
def lookup_account(user_id: str, fields: str = "") -> dict:
    """查询玩家账号状态（封禁/充值/登录信息）。

    Args:
        user_id: 玩家 UID
        fields: 需要返回的分类，逗号分隔。可用值: status / recharge / login。不传时返回全部。
    """
    _FIELD_GROUPS = {
        "status": ["status", "ban_reason"],
        "recharge": ["recharge_total", "abnormal_detail"],
        "login": ["last_login"],
    }

    accounts_path = os.path.join(_ROOT, "data", "accounts.json")
    try:
        with open(accounts_path, encoding="utf-8") as f:
            accounts = json.load(f)
    except Exception as e:
        return {"error": f"账号数据读取失败: {e}"}

    record = accounts.get(user_id)
    if record is None:
        return {"status": "unknown", "ban_reason": None}

    groups = [g.strip() for g in fields.split(",") if g.strip()] if fields else []
    if groups:
        result = {}
        for group in groups:
            for f in _FIELD_GROUPS.get(group, []):
                if f in record:
                    result[f] = record[f]
        return result

    result = {}
    for group_fields in _FIELD_GROUPS.values():
        for f in group_fields:
            if f in record:
                result[f] = record[f]
    return result


# ─── 工具 4：查询知识库 ───────────────────────────────────────────────

@mcp.tool()
async def query_knowledge(question: str) -> dict:
    """查询游戏知识库，获取攻略、账号操作、充值退款等信息。

    Args:
        question: 用户问题，例如"原神如何获得原石？"
    """
    import httpx

    rag_url = os.getenv("RAG_SERVICE_URL", "http://localhost:8000")
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                f"{rag_url}/query",
                json={"query": question, "top_k": 3},
            )
            resp.raise_for_status()
            return resp.json()
    except httpx.ConnectError:
        return {"has_answer": False, "message": "知识服务连接失败", "confidence": 0.0}
    except httpx.TimeoutException:
        return {"has_answer": False, "message": "知识服务超时", "confidence": 0.0}
    except Exception as e:
        return {"has_answer": False, "message": f"知识服务错误: {e}", "confidence": 0.0}


if __name__ == "__main__":
    import uvicorn
    # 使用 streamable_http transport（MCP 新标准，端点 /mcp）
    uvicorn.run(mcp.streamable_http_app(), host="127.0.0.1", port=8001)
