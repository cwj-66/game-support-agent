"""
LangGraph 主图定义
Agent 编排核心文件：路由函数 + 图结构 + 执行入口
"""

from typing import Literal, Dict, Any, Optional, AsyncGenerator

from langgraph.graph import StateGraph, END

from .state import AgentState, create_turn_input
from .nodes import (
    reasoning_node,
    tool_exec_node,
    generate_response_node,
    finish_node,
)
from .checkpointer import get_checkpointer


# ============ 路由函数 ============

async def route_from_reasoning(state: AgentState) -> Literal["tool_exec", "generate"]:
    """reasoning 节点路由：有 tool_calls → tool_exec，否则 → generate"""
    from langchain_core.messages import AIMessage

    messages = state.get("messages", [])
    for msg in reversed(messages):
        if isinstance(msg, AIMessage):
            if getattr(msg, "tool_calls", None):
                return "tool_exec"
            break
    return "generate"


# ============ 图构建（懒加载） ============

workflow = StateGraph(AgentState)

workflow.add_node("reasoning", reasoning_node)
workflow.add_node("tool_exec", tool_exec_node)
workflow.add_node("generate", generate_response_node)
workflow.add_node("finish", finish_node)

workflow.set_entry_point("reasoning")

workflow.add_conditional_edges(
    "reasoning",
    route_from_reasoning,
    {"tool_exec": "tool_exec", "generate": "generate"},
)

workflow.add_edge("tool_exec", "reasoning")
workflow.add_edge("generate", "finish")
workflow.add_edge("finish", END)

_compiled_graph = None


async def get_graph():
    """获取已编译的 LangGraph 实例（懒加载，异步 checkpointer）"""
    global _compiled_graph
    if _compiled_graph is None:
        cp = await get_checkpointer()
        _compiled_graph = workflow.compile(checkpointer=cp)
    return _compiled_graph


# ============ 执行入口 ============

async def run_agent(
    session_id: str,
    user_id: str,
    user_query: str,
    thread_id: Optional[str] = None,
    ticket_id: Optional[str] = None,
) -> Dict[str, Any]:
    """运行 Agent 主入口，图每轮跑完全程（reasoning → finish）"""
    from app.services.session_store import expire_session_if_needed

    thread = thread_id or session_id
    await expire_session_if_needed(thread)

    turn_input = create_turn_input(
        session_id, user_id, user_query,
        ticket_id=ticket_id,
    )

    config = {
        "configurable": {
            "thread_id": thread,
            "checkpoint_ns": "game_support_agent",
        }
    }

    g = await get_graph()
    result = await g.ainvoke(turn_input, config)

    return {
        "session_id": session_id,
        "final_response": result.get("final_response") or "",
        "messages": result.get("messages", []),
        "metadata": result.get("metadata", {}),
        "node_trace": result.get("node_trace", []),
        "ticket_offer": result.get("ticket_offer"),
        "human_offer": result.get("human_offer"),
    }


async def stream_agent(
    session_id: str,
    user_id: str,
    user_query: str,
    thread_id: Optional[str] = None,
    ticket_id: Optional[str] = None,
) -> AsyncGenerator[Dict[str, Any], None]:
    """流式运行 Agent，逐节点产出状态更新"""
    from app.services.session_store import expire_session_if_needed

    thread = thread_id or session_id
    await expire_session_if_needed(thread)

    turn_input = create_turn_input(
        session_id, user_id, user_query,
        ticket_id=ticket_id,
    )

    config = {
        "configurable": {
            "thread_id": thread,
            "checkpoint_ns": "game_support_agent",
        }
    }

    g = await get_graph()
    async for chunk in g.astream(turn_input, config, stream_mode="updates"):
        yield chunk


__all__ = ["get_graph", "run_agent", "stream_agent"]
