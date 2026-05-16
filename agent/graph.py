"""
LangGraph 主图定义
Agent 编排核心文件：路由函数 + 图结构 + 执行入口
"""

from typing import Literal, Dict, Any, Optional, AsyncGenerator

from langgraph.graph import StateGraph, END

from .state import AgentState, create_initial_state
from .nodes import (
    reasoning_node,
    tool_exec_node,
    generate_response_node,
    detector_node,
    finish_node,
    human_node,
)
from .checkpointer import get_checkpointer


# ============ 路由函数 ============

async def route_from_reasoning(state: AgentState) -> Literal["tool_exec", "generate"]:
    """
    reasoning 节点路由
    - 最后一条 AIMessage 含 tool_calls → tool_exec
    - 其余 → generate
    """
    from langchain_core.messages import AIMessage

    messages = state.get("messages", [])
    for msg in reversed(messages):
        if isinstance(msg, AIMessage):
            if getattr(msg, "tool_calls", None):
                return "tool_exec"
            break
    return "generate"


async def route_from_tool_exec(state: AgentState) -> Literal["human", "reasoning"]:
    """
    tool_exec 节点路由
    - escalate_to_human / auto_escalate → human
    - 普通工具结果 → 回到 reasoning 继续决策
    """
    interrupt_info = state.get("interrupt_info")
    if interrupt_info and interrupt_info.get("source") in ("llm_escalate", "auto_escalate"):
        return "human"
    return "reasoning"


async def route_from_detector(state: AgentState) -> Literal["human", "finish"]:
    """
    detector 节点路由（generate 之后的兜底）
    - 规则触发中断 → human
    - 通过 → finish
    """
    interrupt_info = state.get("interrupt_info")
    if interrupt_info and interrupt_info.get("should_interrupt", False):
        return "human"
    return "finish"


# ============ 图构建 ============

workflow = StateGraph(AgentState)

workflow.add_node("reasoning", reasoning_node)
workflow.add_node("tool_exec", tool_exec_node)
workflow.add_node("detector", detector_node)
workflow.add_node("generate", generate_response_node)
workflow.add_node("human", human_node)
workflow.add_node("finish", finish_node)

workflow.set_entry_point("reasoning")

workflow.add_conditional_edges(
    "reasoning",
    route_from_reasoning,
    {"tool_exec": "tool_exec", "generate": "generate"},
)

workflow.add_conditional_edges(
    "tool_exec",
    route_from_tool_exec,
    {"human": "human", "reasoning": "reasoning"},
)

workflow.add_edge("generate", "detector")

workflow.add_conditional_edges(
    "detector",
    route_from_detector,
    {"human": "human", "finish": "finish"},
)

workflow.add_edge("human", "generate")
workflow.add_edge("finish", END)

graph = workflow.compile(checkpointer=get_checkpointer())


# ============ 执行入口 ============

async def run_agent(
    session_id: str,
    user_query: str,
    thread_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    运行 Agent 主入口

    Args:
        session_id: 会话ID
        user_query: 用户问题
        thread_id: 可选的线程ID（用于断点恢复）

    Returns:
        最终执行结果
    """
    initial_state = create_initial_state(session_id, user_query)

    config = {
        "configurable": {
            "thread_id": thread_id or session_id,
            "checkpoint_ns": "game_support_agent",
        }
    }

    result = await graph.ainvoke(initial_state, config)

    # LangGraph interrupt() 在某些版本中不抛异常，而是正常返回带 __interrupt__ 的结果
    raw_interrupt = result.get("__interrupt__")
    interrupt_payload = None
    if raw_interrupt is not None:
        # 不同版本可能返回 Interrupt 对象、元组、或列表
        if hasattr(raw_interrupt, "value"):
            # LangGraph Interrupt 对象，取 .value 属性
            interrupt_payload = raw_interrupt.value
        elif isinstance(raw_interrupt, (tuple, list)) and len(raw_interrupt) > 0:
            item = raw_interrupt[0]
            interrupt_payload = item.value if hasattr(item, "value") else item
        elif isinstance(raw_interrupt, dict):
            interrupt_payload = raw_interrupt
        else:
            interrupt_payload = raw_interrupt

    return {
        "session_id": session_id,
        "final_response": result.get("final_response") or "",
        "messages": result.get("messages", []),
        "metadata": result.get("metadata", {}),
        "interrupt_info": result.get("interrupt_info"),
        "has_interrupt": raw_interrupt is not None,
        "__interrupt__": interrupt_payload,
    }


async def stream_agent(
    session_id: str,
    user_query: str,
    thread_id: Optional[str] = None,
) -> AsyncGenerator[Dict[str, Any], None]:
    """
    流式运行 Agent，逐节点产出状态更新

    每个 chunk 格式：{"node_name": {state_updates}}
    供 SSE 接口逐步推送给前端
    """
    initial_state = create_initial_state(session_id, user_query)

    config = {
        "configurable": {
            "thread_id": thread_id or session_id,
            "checkpoint_ns": "game_support_agent",
        }
    }

    async for chunk in graph.astream(initial_state, config, stream_mode="updates"):
        yield chunk


__all__ = ["graph", "run_agent", "stream_agent"]
