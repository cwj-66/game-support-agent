"""
MCP Server — 客服工具服务

暴露 check_ticket / lookup_account / query_knowledge。
工单创建走 propose_ticket → 前端确认 → /chat/ticket-confirm 流程。

启动：python mcp_server.py  →  http://127.0.0.1:8001/mcp
"""

import os
import sys

from mcp.server.fastmcp import FastMCP

_ROOT = os.path.dirname(os.path.abspath(__file__))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

# host 必须在构造时传入：默认 127.0.0.1 会开启 DNS rebinding 保护，
# Docker 内以服务名访问会返回 421 Misdirected Request
_MCP_HOST = os.getenv("MCP_HOST", "0.0.0.0")
_MCP_PORT = int(os.getenv("MCP_PORT", "8001"))
mcp = FastMCP("customer-service", host=_MCP_HOST, port=_MCP_PORT)


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
    from app.services.ticket_service import check_ticket_core
    return check_ticket_core(user_id, ticket_id)


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
    from app.services.account_service import lookup_account_core
    return lookup_account_core(user_id, fields)


@mcp.tool()
async def query_knowledge(question: str) -> dict:
    """查询内部知识库，获取准确的游戏及客服相关信息。

    覆盖范围：游戏攻略/机制/活动、账号操作（注销/换绑/实名）、封号申诉、充值退款、投诉处理等。
    绝大多数用户问题都应优先使用此工具查询，包括封号、充值、退款等敏感问题。

    流程：HTTP 检索片段 → 本服务 LLM 依据片段作答 → 再由 Agent generate 节点润色最终客服话术。

    Args:
        question: 用户要查询的问题，例如"原神如何获得原石？"
    """
    from agent.tools.rag_client import RAGClient

    client = RAGClient()
    try:
        return await client.query_knowledge(question)
    finally:
        await client.close()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(mcp.streamable_http_app(), host=_MCP_HOST, port=_MCP_PORT)
