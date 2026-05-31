from .query_knowledge import create_knowledge_tool

from .account import create_lookup_account
from .ticket import create_ticket
from .ticket_status import create_check_ticket
from .out_of_scope import report_out_of_scope
from .rag_client import get_rag_client, close_rag_client

def get_all_tools(user_id: str = ""):
    """返回所有客服工具列表。

    所有工具都是本地注册的 LangChain tool，其中 lookup_account 和 check_ticket
    的 user_id 由系统注入，不暴露给 LLM 自由传参。

    Args:
        user_id: 当前玩家 UID，传给工厂创建绑定了该用户的工具实例
    """
    tools = [
        create_knowledge_tool(),
        create_lookup_account(user_id),
        create_check_ticket(user_id),
        create_ticket,
        report_out_of_scope,
    ]
    return tools