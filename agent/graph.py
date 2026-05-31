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
    human_handoff_node,
)
from .checkpointer import get_checkpointer


# ============ 路由函数 ============

async def route_from_reasoning(state: AgentState) -> Literal["tool_exec", "generate", "human_handoff"]:
    """
    reasoning 节点路由
    - 最后一条 AIMessage 含 tool_calls → tool_exec
    - 无 tool_calls 且 human_requested=True → human_handoff（系统层转人工）
    - 其余 → generate
    """
    from langchain_core.messages import AIMessage

    messages = state.get("messages", [])
    for msg in reversed(messages):
        if isinstance(msg, AIMessage):
            if getattr(msg, "tool_calls", None):
                return "tool_exec"
            break
    # LLM 决策结束但用户要求转人工 → 系统层拦截转人工
    if state.get("human_requested"):
        return "human_handoff"
    return "generate"


# ============ 图构建（懒加载） ============

workflow = StateGraph(AgentState)

workflow.add_node("reasoning", reasoning_node)
workflow.add_node("tool_exec", tool_exec_node)
workflow.add_node("detector", detector_node)
workflow.add_node("generate", generate_response_node)
workflow.add_node("human", human_node)
workflow.add_node("finish", finish_node)
workflow.add_node("human_handoff", human_handoff_node)

workflow.set_entry_point("reasoning")

workflow.add_conditional_edges(
    "reasoning",
    route_from_reasoning,
    {"tool_exec": "tool_exec", "generate": "generate", "human_handoff": "human_handoff"},
)

workflow.add_edge("tool_exec", "reasoning")

workflow.add_edge("generate", "detector")

workflow.add_edge("detector", "finish")

workflow.add_edge("human", "finish")
workflow.add_edge("human_handoff", "human")
workflow.add_edge("finish", END)

# 编译后的图（懒加载，因为 checkpointer 初始化需要异步）
_compiled_graph = None


async def get_graph():
    """获取已编译的 LangGraph 实例（懒加载）"""
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
    """
    运行 Agent 主入口

    Args:
        session_id: 会话ID
        user_id: 玩家游戏UID
        user_query: 用户问题
        thread_id: 可选的线程ID（用于断点恢复）
        ticket_id: 关联的工单ID（可选）

    Returns:
        最终执行结果
    """
    # 尝试读取上一轮的 metadata，保留给下一轮
    prev_metadata: dict | None = None
    try:
        cp = await get_checkpointer()
        cfg = {
            "configurable": {
                "thread_id": thread_id or session_id,
                "checkpoint_ns": "game_support_agent",
            }
        }
        checkpoint_tuple = await cp.aget_tuple(cfg)
        if checkpoint_tuple is not None:
            cv = checkpoint_tuple.checkpoint.get("channel_values", {})
            prev_metadata = cv.get("metadata")
    except Exception:
        pass  # 首次对话或无 checkpoint 时静默跳过

    initial_state = create_initial_state(
        session_id, user_id, user_query,
        ticket_id=ticket_id,
        metadata=prev_metadata,
    )

    config = {
        "configurable": {
            "thread_id": thread_id or session_id,
            "checkpoint_ns": "game_support_agent",
        }
    }

    g = await get_graph()
    result = await g.ainvoke(initial_state, config)

    # 提取节点执行路径
    node_trace = result.get("node_trace", [])

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
        "node_trace": node_trace,
    }


async def stream_agent(
    session_id: str,
    user_id: str,
    user_query: str,
    thread_id: Optional[str] = None,
    ticket_id: Optional[str] = None,
) -> AsyncGenerator[Dict[str, Any], None]:
    """
    流式运行 Agent，逐节点产出状态更新

    每个 chunk 格式：{"node_name": {state_updates}}
    供 SSE 接口逐步推送给前端
    """
    # 尝试读取上一轮的 metadata，保留给下一轮
    prev_metadata: dict | None = None
    try:
        cp = await get_checkpointer()
        cfg = {
            "configurable": {
                "thread_id": thread_id or session_id,
                "checkpoint_ns": "game_support_agent",
            }
        }
        checkpoint_tuple = await cp.aget_tuple(cfg)
        if checkpoint_tuple is not None:
            cv = checkpoint_tuple.checkpoint.get("channel_values", {})
            prev_metadata = cv.get("metadata")
    except Exception:
        pass

    initial_state = create_initial_state(
        session_id, user_id, user_query,
        ticket_id=ticket_id,
        metadata=prev_metadata,
    )

    config = {
        "configurable": {
            "thread_id": thread_id or session_id,
            "checkpoint_ns": "game_support_agent",
        }
    }

    g = await get_graph()
    async for chunk in g.astream(initial_state, config, stream_mode="updates"):
        yield chunk


__all__ = ["get_graph", "run_agent", "stream_agent"]
