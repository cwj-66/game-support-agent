from .mcp_adapter import create_knowledge_tool
from .escalate import escalate_to_human
from .account import lookup_account
from .ticket import create_ticket

def get_all_tools():
    return [create_knowledge_tool(), escalate_to_human, lookup_account, create_ticket]