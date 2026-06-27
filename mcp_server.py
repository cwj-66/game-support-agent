"""
MCP Server — 客服工具服务

职责：注册并暴露客服工具给 MCP Client（LangGraph 侧）。
暴露 4 个工具：create_ticket / check_ticket / lookup_account / query_knowledge

业务逻辑统一在 app/core/ticket_service.py 和 app/core/account_service.py，
此处只做 MCP 注册（@mcp.tool 装饰器）和 Docstring 声明。

核心原则：Server 只管工具的注册和暴露，Client 只管工具的发现和绑定，
interrupt 的控制权始终在 LangGraph 图里，不要把控制流逻辑放进 MCP Server。

启动方式：
    python mcp_server.py
    # 监听 http://127.0.0.1:8001/mcp
"""

import os
import sys

from mcp.server.fastmcp import FastMCP

# 确保项目根目录在 Python 路径，以便 import app.*
_ROOT = os.path.dirname(os.path.abspath(__file__))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

mcp = FastMCP("customer-service")


# ─── 工具 1：创建工单 ────────────────────────────────────────────────

@mcp.tool()
def create_ticket(user_id: str, issue_type: str, description: str) -> dict:
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
    return create_ticket_core(user_id, issue_type, description)


# ─── 工具 2：查询工单 ────────────────────────────────────────────────

@mcp.tool()
def check_ticket(user_id: str, ticket_id: str = "") -> dict:
    """查询工单处理进度和客服回复。

    两种情况使用此工具：
    1. 玩家主动提供了工单号（"查一下TK-xxx""帮我看看工单"）→ 传入 ticket_id
    2. 玩家问"上次的问题处理了吗""我的充值工单怎么样了"→ 不传 ticket_id，自动查该玩家最近的工单

    Args:
        user_id: 玩家 UID
        ticket_id: 工单号（格式 TK-YYYYMMDD-XXXX），玩家提供了就传，否则自动查该玩家最近工单
    """
    from app.core.ticket_service import check_ticket_core
    return check_ticket_core(user_id, ticket_id)


# ─── 工具 3：查询账号状态 ─────────────────────────────────────────────

@mcp.tool()
def lookup_account(user_id: str, fields: str = "") -> dict:
    """查询玩家账号状态。按需传入 fields 只取需要的分类，不要获取不需要的分类。

    只能查询当前玩家自己的账号，无法查询其他玩家的信息。

    Args:
        user_id: 玩家 UID
        fields: 需要返回的分类，逗号分隔，例如 "status,recharge"。
                可用值: status（封禁状态）/ recharge（充值记录）/ login（登录信息）。
                不传时返回全部。
    """
    from app.core.account_service import lookup_account_core
    return lookup_account_core(user_id, fields)


# ─── 工具 4：查询知识库 ───────────────────────────────────────────────

@mcp.tool()
async def query_knowledge(question: str) -> dict:
    """查询内部知识库，获取准确的游戏及客服相关信息。

    覆盖范围：游戏攻略/机制/活动、账号操作（注销/换绑/实名）、封号申诉、充值退款、投诉处理等。
    绝大多数用户问题都应优先使用此工具查询，包括封号、充值、退款等敏感问题。

    Args:
        question: 用户要查询的问题，例如"原神如何获得原石？"
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
        return {"has_answer": False, "message": "知识服务连接失败，建议转人工", "confidence": 0.0}
    except httpx.TimeoutException:
        return {"has_answer": False, "message": "知识服务超时，建议稍后重试或转人工", "confidence": 0.0}
    except Exception as e:
        return {"has_answer": False, "message": f"知识服务发生未知错误，建议转人工", "confidence": 0.0}


if __name__ == "__main__":
    import uvicorn
    # 使用 streamable_http transport（MCP 新标准，端点 /mcp）
    uvicorn.run(mcp.streamable_http_app(), host="127.0.0.1", port=8001)
