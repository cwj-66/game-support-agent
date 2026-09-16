"""转人工提议工具：由 tool_exec 拦截，向前端展示确认按钮。"""

from langchain_core.tools import tool


@tool
async def propose_human_escalation(summary: str) -> str:
    """向用户提出转人工建议，展示「是/否」确认按钮，用户确认后才进入人工接待。

    以下场景需调用此工具：
    1. 用户强烈负面情绪（着急、愤怒、投诉等）
    2. 用户明确要求转人工（「帮我转人工」「找人工客服」等）

    Args:
        summary: 用户问题的简短总结（≤50字，展示给客服和玩家确认）
    """
    return "转人工确认请求已提出"
