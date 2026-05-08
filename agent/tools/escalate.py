from langchain_core.tools import tool

@tool
def escalate_to_human(reason: str) -> str:
    """当遇到以下情况时调用此工具，将对话移交人工客服：
    - 用户涉及账号封禁、实名认证、退款等敏感操作
    - 问题超出知识库范围，无法给出可信答复
    - 用户情绪激动或多次表达不满
    
    Args:
        reason: 说明为何需要人工介入
    """
    return f"ESCALATE:{reason}"