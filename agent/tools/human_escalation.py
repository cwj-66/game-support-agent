"""
转人工升等工具
LLM 调用此工具后，tool_exec 节点将跳过所有工具执行，直接触发转人工流程
"""

from langchain_core.tools import tool


@tool
async def request_human_escalation(reason: str) -> str:
    """当用户明确要求转人工时调用。调用后将中断当前对话流程，转交人工客服处理。

    Args:
        reason: 用户要求转人工的原因描述
    """
    import json
    return json.dumps({
        "status": "escalated",
        "reason": reason,
        "_health": {"ok": True, "confidence": 0.95},
    }, ensure_ascii=False)
