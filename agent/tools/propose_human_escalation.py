"""
转人工提议工具
LLM 调用此工具时不会立即转人工，而是向前端返回「是/否」确认按钮。
tool_exec 会拦截此工具调用，写入 state.human_offer，图继续跑完全程。
"""

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
    # 此工具永远不会真正执行，tool_exec 会在执行前拦截
    return "转人工确认请求已提出"
