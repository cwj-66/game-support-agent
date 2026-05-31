"""
系统层转人工节点

当 graph 层检测到用户明确要求转人工（human_requested=True），
但 LLM 未在 ReAct 循环中主动调用 escalate_to_human 工具时，
由此节点自动设置中断信息，路由到 human 节点触发审核。
"""

from typing import Dict, Any
from ..state import AgentState


async def escalate_to_human_node(state: AgentState) -> Dict[str, Any]:
    """设置中断信息，将流程移交 human 节点等待人工审核"""
    ticket_id = state.get("ticket_id")
    reason = "用户明确要求转人工，系统自动升等"
    if ticket_id:
        reason += f"（关联工单：{ticket_id}）"

    return {
        "interrupt_info": {
            "should_interrupt": True,
            "reason": reason,
            "level": "high",
            "sensitive_words": [],
            "pending_content": None,
            "source": "llm_escalate",
        },
        "node_trace": ["escalate_to_human"],
    }
