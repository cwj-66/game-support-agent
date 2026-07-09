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
    detector_node,
    finish_node,
    human_node,
    human_handoff_node,
)
from .checkpointer import get_checkpointer, get_sync_checkpointer


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


def route_from_human(state: AgentState) -> Literal["human", "finish"]:
    """
    human 节点路由
    - human_action == "close" → finish（客服结束接待）
    - 其余（continue 或玩家消息）→ human（再次挂起等待）
    """
    if state.get("human_action") == "close":
        return "finish"
    return "human"


async def route_from_tool_exec(state: AgentState) -> Literal["reasoning", "human_handoff"]:
    """
    tool_exec 节点路由
    - interrupt_info 存在 → human_handoff（转人工）
    - 其余 → reasoning（继续 ReAct 循环）
    """
    if state.get("interrupt_info"):
        return "human_handoff"
    return "reasoning"


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
    {"tool_exec": "tool_exec", "generate": "generate"},
)

workflow.add_conditional_edges(
    "tool_exec",
    route_from_tool_exec,
    {"reasoning": "reasoning", "human_handoff": "human_handoff"},
)

workflow.add_edge("generate", "detector")

workflow.add_edge("detector", "finish")

workflow.add_conditional_edges(
    "human",
    route_from_human,
    {"human": "human", "finish": "finish"},
)
workflow.add_edge("human_handoff", "human")
workflow.add_edge("finish", END)

# 编译后的图（懒加载，因为 checkpointer 初始化需要异步）
_compiled_graph = None


async def get_graph():
    """获取已编译的 LangGraph 实例（懒加载，异步 checkpointer）"""
    global _compiled_graph
    if _compiled_graph is None:
        cp = await get_checkpointer()
        _compiled_graph = workflow.compile(checkpointer=cp)
    return _compiled_graph


# 编译后的图（同步 checkpointer，用于 Command resume）
_sync_compiled_graph = None


def get_sync_graph():
    """获取已编译的 LangGraph 实例（同步 checkpointer）

    LangGraph 的 Command(resume=...) 恢复路径内部使用同步方法调用
    checkpointer，因此需要同步 saver + 同步 invoke。
    """
    global _sync_compiled_graph
    if _sync_compiled_graph is None:
        cp = get_sync_checkpointer()
        _sync_compiled_graph = workflow.compile(checkpointer=cp)
    return _sync_compiled_graph


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
    from app.core.session_store import expire_session_if_needed

    thread = thread_id or session_id
    # 2 小时无活动 → 清除 checkpoint，等同新会话
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
        "ticket_offer": result.get("ticket_offer"),
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
    from app.core.session_store import expire_session_if_needed

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


__all__ = ["get_graph", "get_sync_graph", "run_agent", "stream_agent"]
