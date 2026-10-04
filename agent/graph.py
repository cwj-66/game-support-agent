"""LangGraph 主图：路由、编译与执行入口。"""

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
import time
from .events import emit_event
from app.services.execution_trace import STAGES, public_execution_trace


def tracked_node(name, function):
    async def execute(state):
        start = time.perf_counter()
        emit_event({"type": "stage", "name": name, "label": STAGES[name], "status": "running"})
        result = await function(state)
        emit_event({"type": "stage", "name": name, "label": STAGES[name], "status": "completed", "duration_ms": int((time.perf_counter() - start) * 1000)})
        return result
    return execute


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


workflow = StateGraph(AgentState)

workflow.add_node("reasoning", tracked_node("reasoning", reasoning_node))
workflow.add_node("tool_exec", tracked_node("tool_exec", tool_exec_node))
workflow.add_node("generate", tracked_node("generate", generate_response_node))
workflow.add_node("finish", tracked_node("finish", finish_node))

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
        "tool_calls": result.get("tool_calls", []),
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


async def stream_agent_events(session_id: str, user_id: str, user_query: str):
    """Stream only public custom events and an authoritative final result."""
    from app.services.session_store import expire_session_if_needed
    await expire_session_if_needed(session_id)
    config = {"configurable": {"thread_id": session_id, "checkpoint_ns": "game_support_agent", "public_stream": True}}
    g = await get_graph()
    result = {"node_trace": [], "metadata": {}, "tool_calls": []}
    completed_stages = []
    start = time.perf_counter()
    async for mode, chunk in g.astream(create_turn_input(session_id, user_id, user_query), config, stream_mode=["updates", "custom"]):
        if mode == "custom":
            if chunk.get("type") == "stage" and chunk.get("status") == "completed":
                completed_stages.append({key: chunk[key] for key in ("name", "label", "status", "duration_ms")})
            yield chunk
            continue
        for name, update in chunk.items():
            if not isinstance(update, dict):
                continue
            result["node_trace"].append(name)
            for key in ("metadata", "tool_calls", "final_response", "ticket_offer", "human_offer"):
                if key in update:
                    result[key] = update[key]
    trace = public_execution_trace(result)
    trace["stages"] = completed_stages
    yield {
        "type": "done", "status": "ok", "response": result.get("final_response") or "",
        "ticket_offer": result.get("ticket_offer"), "human_offer": result.get("human_offer"),
        "metadata": {"execution_time_ms": int((time.perf_counter() - start) * 1000), "execution_trace": trace},
    }
