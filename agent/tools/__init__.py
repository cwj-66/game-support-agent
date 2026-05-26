
from .query_knowledge import create_knowledge_tool
from .escalate import escalate_to_human
from .account import lookup_account
from .ticket_status import check_ticket
from .rag_client import get_rag_client, close_rag_client


def get_all_tools():
    tools = [create_knowledge_tool(), escalate_to_human, lookup_account, check_ticket]

    # MCP 工具注入：若已连接 MCP，用远程 create_ticket；否则本地 mock 兜底
    from .mcp_client import get_mcp_tools
    mcp_tools = get_mcp_tools()
    found = False
    for t in mcp_tools:
        if t.name == "create_ticket":
            tools.append(t)
            found = True
            break

    if not found:
        from .ticket import create_ticket
        tools.append(create_ticket)

    return tools