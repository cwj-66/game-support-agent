"""
MCP Server — 客服工具服务

职责：注册并暴露客服工具给 MCP Client（LangGraph 侧）。
当前为骨架实现，create_ticket 返回 mock 数据。

MCP Client 端拿到工具结果后，insert 判断：
    if tool_result.get("action") == "interrupt":
        graph.update_state(config, {"pending_approval": tool_result})
        interrupt("等待人工审批")

核心原则：Server 只管工具的实现，Client 只管工具的发现和绑定，
interrupt 的控制权始终在 LangGraph 图里，不要把业务逻辑放进 MCP Server。
"""
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("customer-service")


@mcp.tool()
def create_ticket(user_id: str, issue: str, priority: str) -> dict:
    """为玩家创建客服工单，适用于需要后台人工处理的问题。

    priority 枚举值：high（紧急，如账号被盗）/ medium（普通）/ low（低优，如建议反馈）

    Args:
        user_id: 玩家 UID
        issue: 问题描述
        priority: 优先级，high / medium / low
    """
    # TODO: 写入数据库，返回真实 ticket_id
    return {
        "ticket_id": "TK" + str(hash(user_id + issue))[-8:],
        "user_id": user_id,
        "issue": issue,
        "priority": priority,
        "status": "submitted",
    }


if __name__ == "__main__":
    mcp.run(transport="sse", host="0.0.0.0", port=8001)
