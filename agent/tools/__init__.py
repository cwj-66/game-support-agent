
from .query_knowledge import create_knowledge_tool
from .escalate import escalate_to_human
from .account import lookup_account
from .ticket import create_ticket
from .ticket_status import check_ticket
from .rag_client import get_rag_client, close_rag_client


def get_all_tools():
    """返回所有客服工具列表。

    所有工具都是本地注册的 LangChain tool，其中 create_ticket 和 check_ticket
    内部通过 MCP 协议访问 SQLite 数据库。
    """
    tools = [
        create_knowledge_tool(),
        escalate_to_human,
        lookup_account,
        check_ticket,
        create_ticket,
    ]
    return tools