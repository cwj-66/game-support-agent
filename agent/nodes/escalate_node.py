"""
系统层转人工节点（handoff）

当 graph 层检测到用户明确要求转人工（human_requested=True），
但 LLM 未在 ReAct 循环中主动调用 escalate_to_human 工具时，
由此节点整理对话上下文为结构化 payload，然后移交 human 节点处理。
"""

from typing import Dict, Any
from langchain_core.messages import ToolMessage
from ..state import AgentState


async def human_handoff_node(state: AgentState) -> Dict[str, Any]:
    """整理对话上下文和工具执行记录，构建 interrupt_info payload，路由到 human_node"""
    user_query = state.get("user_query", "")
    tool_records = state.get("tool_calls", [])

    # 构建结构化上下文摘要
    context_parts = [f"用户问题：{user_query}"]

    if tool_records:
        context_parts.append("\n工具执行记录：")
        for r in tool_records:
            tool = r.get("tool", "")
            inp = r.get("input", {})
            status = r.get("status", "")
            error = r.get("error", "")
            if status == "failed":
                context_parts.append(f"  [{tool}] 失败：{error}")
            elif status == "completed":
                context_parts.append(f"  [{tool}] 成功")
            elif status == "started":
                context_parts.append(f"  [{tool}] 执行中")

    # 遍历对话历史，提取工具执行结果
    tool_msgs = [m for m in state.get("messages", []) if isinstance(m, ToolMessage)]
    if tool_msgs:
        context_parts.append("\n已收集信息：")
        for tm in tool_msgs:
            content = tm.content
            if isinstance(content, str) and len(content) > 200:
                content = content[:200] + "..."
            context_parts.append(f"  [{tm.name}] {content}")

    context = "\n".join(context_parts)

    return {
        "interrupt_info": {
            "should_interrupt": True,
            "reason": "用户要求转人工，系统层拦截",
            "level": "high",
            "sensitive_words": [],
            "pending_content": context,
            "source": "llm_escalate",
        },
        "node_trace": ["human_handoff"],
    }
