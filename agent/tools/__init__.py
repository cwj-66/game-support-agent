from .mcp_adapter import create_knowledge_tool
from .escalate import escalate_to_human

def get_all_tools():
    return [create_knowledge_tool(), escalate_to_human]