"""
LangGraph 主图定义
Agent编排核心文件，定义节点顺序和条件边
"""

from datetime import datetime, timezone
from typing import Literal, Dict, Any, Optional, AsyncGenerator

from langgraph.graph import StateGraph, END

from .state import AgentState
from .nodes import reasoning_node, tool_exec_node, human_node
from .checkpointer import get_checkpointer
from human_in_loop.detector import InterruptDetector
from app.core.llm import get_chat_model
from app.core.config import get_settings


# reasoning 出口：AIMessage 带 tool_calls → tool_exec，否则 → generate
async def route_from_reasoning(state: AgentState) -> Literal["tool_exec", "generate"]:
    """
    reasoning 节点路由

    - 最后一条 AIMessage 含 tool_calls → tool_exec
    - 兜底：metadata.reasoning.need_tool 为 True → tool_exec
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


# tool_exec 出口：最后一条 ToolMessage 以 "ESCALATE:" 开头 → human，否则回 reasoning
async def route_from_tool_exec(state: AgentState) -> Literal["human", "reasoning"]:
    """
    tool_exec 节点路由

    - escalate_to_human 工具返回 "ESCALATE:..." → human
    - 普通工具结果 → 回到 reasoning 继续决策
    """
    from langchain_core.messages import ToolMessage
    messages = state.get("messages", [])
    for msg in reversed(messages):
        if isinstance(msg, ToolMessage):
            if msg.content.startswith("ESCALATE:"):
                return "human"
            break
    return "reasoning"


# detector 兜底出口：generate 之后最后一道防线
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


# ============ 节点函数实现 ============

# 中断检测节点，检查是否需要触发human-in-loop
async def detector_node(state: AgentState) -> Dict[str, Any]:
    """
    中断检测节点
    
    检查是否需要触发human-in-loop：
    1. 敏感词检测
    2. 置信度阈值判断
    
    """
    final_response = state.get("final_response", "")
    metadata = state.get("metadata", {})
    reasoning = metadata.get("reasoning", {})
    
    # 从配置中读取敏感词和阈值，避免硬编码
    settings = get_settings()
    detector = InterruptDetector(
        sensitive_words=settings.SENSITIVE_WORDS,
        confidence_threshold=settings.HIL_CONFIDENCE_THRESHOLD,
    )
    
    # 执行检测，检查是否需要触发human-in-loop
    decision = detector.detect(
        content=final_response,
        confidence=reasoning.get("confidence", 0.5),
        metadata={"tool_calls": state.get("tool_calls", [])}
    )
    
    return {
        "interrupt_info": {
            "should_interrupt": decision.should_interrupt,
            "reason": decision.reason,
            "level": decision.level,
            "sensitive_words": decision.sensitive_words,
            "confidence": decision.confidence,
            "pending_content": final_response
        } if decision.should_interrupt else None
    }


# 生成最终回复节点，使用LLM结合工具结果生成回复
async def generate_response_node(state: AgentState) -> Dict[str, Any]:
    """
    生成最终回复节点

    结合用户问题和完整对话历史，用客服提示词生成最终回复
    """
    from langchain_core.messages import SystemMessage, HumanMessage, AIMessage
    from agent.prompts.system import CUSTOMER_SERVICE_PROMPT

    human_review = state.get("human_review")
    user_query = state.get("user_query", "")
    messages = state.get("messages", [])

    # ── 人工干预优先：OVERRIDE 或 MODIFY 直接使用人工内容 ──
    if human_review and human_review.get("action") in ["OVERRIDE", "MODIFY"]:
        final_response = human_review.get("modified_content", "[人工处理完成]")

    elif messages:
        # ── 把完整对话历史喂给 LLM，让它综合生成回复 ──
        llm = get_chat_model()
        
        # 如果有上一轮的摘要，作为上下文补充（不占用大量token）
        session_summary = state.get("session_summary")
        summary_messages = []
        if session_summary:
            summary_messages = [SystemMessage(content=f"【上一轮对话摘要】{session_summary}")]
        
        ai_result = await llm.ainvoke([
            SystemMessage(content=CUSTOMER_SERVICE_PROMPT),
            *summary_messages,
            HumanMessage(content=user_query),
            *messages,
        ])
        final_response = ai_result.content

    else:
        final_response = "抱歉，我暂时无法回答这个问题，建议联系人工客服。"

    ai_message = AIMessage(content=final_response)

    return {
        "messages": [ai_message],
        "final_response": final_response,
    }


async def finish_node(state: AgentState) -> Dict[str, Any]:
    """
    结束节点

    记录最终状态，并将本轮对话压缩为一句话摘要，
    供下一轮对话作为上下文使用。
    """
    from langchain_core.messages import HumanMessage as HM, SystemMessage as SM

    user_query = state.get("user_query", "")
    final_response = state.get("final_response", "")
    session_summary = None

    # 用LLM把本轮对话压缩成一句话
    if user_query and final_response:
        llm = get_chat_model()
        result = await llm.ainvoke([
            SM(content="你是一个对话摘要助手。请用一句话总结以下对话的核心内容，不超过50字。只输出摘要本身，不要加任何前缀。"),
            HM(content=f"用户问题：{user_query}\nAgent回复：{final_response}"),
        ])
        session_summary = result.content.strip()

    return {
        "session_summary": session_summary,
        "metadata": {
            **state.get("metadata", {}),
            "completed": True,
            "finished_at": datetime.now(timezone.utc).isoformat(),
        },
    }


# ============ 图执行入口 ============

# 创建图构建器
workflow = StateGraph(AgentState)

# 注册节点
workflow.add_node("reasoning", reasoning_node)
workflow.add_node("tool_exec", tool_exec_node)
workflow.add_node("detector", detector_node)
workflow.add_node("generate", generate_response_node)
workflow.add_node("human", human_node)
workflow.add_node("finish", finish_node)

# 定义边
workflow.set_entry_point("reasoning")

# reasoning → tool_exec（有工具调用）| generate（无工具调用）
workflow.add_conditional_edges(
    "reasoning",
    route_from_reasoning,
    {"tool_exec": "tool_exec", "generate": "generate"},
)

# tool_exec → human（LLM主动触发escalate）| reasoning（普通工具结果，ReAct循环）
workflow.add_conditional_edges(
    "tool_exec",
    route_from_tool_exec,
    {"human": "human", "reasoning": "reasoning"},
)

# generate → detector（最后兜底规则检测）
workflow.add_edge("generate", "detector")

# detector → human（规则兜底触发）| finish（正常结束）
workflow.add_conditional_edges(
    "detector",
    route_from_detector,
    {"human": "human", "finish": "finish"},
)

# 人工审核后重新生成回复
workflow.add_edge("human", "generate")
workflow.add_edge("finish", END)

# 配置带有checkpointer图的workflow实例
graph = workflow.compile(checkpointer=get_checkpointer())

# 运行Agent主入口
async def run_agent(
    session_id: str,
    user_query: str,
    thread_id: Optional[str] = None
) -> Dict[str, Any]:
    """
    运行Agent主入口
    
    Args:
        session_id: 会话ID
        user_query: 用户问题
        thread_id: 可选的线程ID（用于断点恢复）
        
    Returns:
        最终执行结果
    """
    from .state import create_initial_state
    
    # 创建初始状态，一个AgentState实例
    initial_state = create_initial_state(session_id, user_query)
    
    # 配置执行（包含thread_id用于checkpointer）
    config = {
        "configurable": {
            "thread_id": thread_id or session_id,
            "checkpoint_ns": "game_support_agent"
        }
    }
    
    # 执行workflow实例，返回最终结果
    result = await graph.ainvoke(initial_state, config)
    
    return {
        "session_id": session_id,
        "final_response": result.get("final_response"),
        "messages": result.get("messages", []),
        "metadata": result.get("metadata", {}),
        "interrupt_info": result.get("interrupt_info"),
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
    from .state import create_initial_state

    initial_state = create_initial_state(session_id, user_query)
    config = {
        "configurable": {
            "thread_id": thread_id or session_id,
            "checkpoint_ns": "game_support_agent",
        }
    }

    async for chunk in graph.astream(initial_state, config, stream_mode="updates"):
        yield chunk


# 导出图实例
__all__ = ["graph", "run_agent", "stream_agent"]
