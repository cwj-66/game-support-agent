"""
Human-in-loop 核心节点（简化版）
使用 LangGraph 的 interrupt() 实现断点暂停
挂起后等待人工输入，恢复后直接将人工回复写入 state.human_reply
"""

from datetime import datetime, timezone
from typing import Dict, Any

from langgraph.types import interrupt

from ..state import AgentState


async def human_node(state: AgentState) -> Dict[str, Any]:
    """
    人工审核节点：触发中断，等待人工输入，恢复后写入 human_reply

    简化版流程：
    1. 构建中断载荷（含当前上下文、原因等）
    2. 调用 interrupt() 挂起图执行，等待人工介入
    3. 恢复后直接将人工输入字符串写入 state.human_reply
    """
    session_id = state["session_id"]
    user_query = state.get("user_query", "")
    interrupt_info = state.get("interrupt_info") or {}

    final_response = state.get("final_response", "")
    if not final_response:
        final_response = f"[Agent未生成回复] 中断原因：{interrupt_info.get('reason', '未知')}"

    # 准备中断载荷，推送给前端展示
    interrupt_payload = {
        "session_id": session_id,
        "user_query": user_query,
        "content": final_response,
        "pending_content": interrupt_info.get("pending_content"),  # 工具执行上下文
        "interrupt_reason": interrupt_info.get("reason"),
        "interrupt_level": interrupt_info.get("level"),
        "source": interrupt_info.get("source"),
        "waiting_for": "human_review",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    print(f"[Human Node] 触发中断，等待人工审核: {session_id}")
    human_reply: str = interrupt(interrupt_payload)

    return {
        "human_reply": human_reply,
        "node_trace": ["human"],
    }
