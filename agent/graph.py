"""
LangGraph 主图定义
Agent编排核心文件，定义节点顺序和条件边
"""

from typing import Literal, Dict, Any, Optional
from langgraph.graph import StateGraph, END

from .state import AgentState
from .nodes import reasoning_node, tool_exec_node, human_node
from .checkpointer import get_checkpointer
from human_in_loop.detector import InterruptDetector


# 从reasoning节点的返回值，根据need_tool决定是否调用工具
async def route_from_reasoning(state: AgentState) -> Literal["tool_exec", "detector"]:
    """
    从reasoning节点路由
    
    根据推理结果决定是否调用工具：
    - 需要工具 → tool_exec
    - 不需要工具 → detector（直接生成回复）
    """
    metadata = state.get("metadata", {})
    reasoning = metadata.get("reasoning", {})
    
    if reasoning.get("need_tool", False):
        return "tool_exec"
    return "detector"


# 从detector节点的返回值，根据是否需要中断决定是否进入人工审核
async def route_from_detector(state: AgentState) -> Literal["human", "generate"]:
    """
    从detector节点路由
    
    根据中断检测结果决定：
    - 触发中断 → human（进入人工审核）
    - 直接通过 → generate（生成最终回复）
    """
    interrupt_info = state.get("interrupt_info")
    
    if interrupt_info and interrupt_info.get("should_interrupt", False):
        return "human"
    return "generate"


# ============ 节点函数实现 ============

# 中断检测节点，检查是否需要触发human-in-loop
async def detector_node(state: AgentState) -> Dict[str, Any]:
    """
    中断检测节点
    
    检查是否需要触发human-in-loop：
    1. 敏感词检测
    2. 置信度阈值判断
    
    TODO: 接入真实InterruptDetector
    """
    final_response = state.get("final_response", "")
    metadata = state.get("metadata", {})
    reasoning = metadata.get("reasoning", {})
    
    # 初始化检测器，使用内置敏感词列表和置信度阈值
    detector = InterruptDetector(
        sensitive_words=["封号", "退款", "投诉", "举报", "盗号"],
        confidence_threshold=0.6
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
    
    使用LLM结合工具结果生成回复
    
    TODO: 接入真实LLM
    """
    from langchain_core.messages import AIMessage
    
    metadata = state.get("metadata", {})
    knowledge = metadata.get("knowledge_result", {})
    human_review = state.get("human_review")
    
    # 如果有审核结果且是MODIFY/OVERRIDE，使用人工内容
    if human_review and human_review.get("action") in ["MODIFY", "OVERRIDE"]:
        final_response = human_review.get("modified_content", "[人工处理完成]")
    elif knowledge.get("has_answer"):
        # 使用知识库答案
        final_response = knowledge.get("answer", "抱歉，无法回答您的问题。")
    else:
        # 通用回复
        final_response = "抱歉，我暂时无法回答这个问题，建议联系人工客服。"
    
    ai_message = AIMessage(content=final_response)
    
    return {
        "messages": [ai_message],
        "final_response": final_response
    }


async def finish_node(state: AgentState) -> Dict[str, Any]:
    """
    结束节点
    
    清理工作，记录最终状态
    """
    return {
        "metadata": {
            **state.get("metadata", {}),
            "completed": True,
            "finished_at": "2024-01-01T00:00:00"  # TODO: 真实时间
        }
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
workflow.add_conditional_edges(
    "reasoning",
    route_from_reasoning,
    {"tool_exec": "tool_exec", "detector": "detector"},
)
workflow.add_edge("tool_exec", "detector")
workflow.add_conditional_edges(
    "detector",
    route_from_detector,
    {"human": "human", "generate": "generate"},
)
workflow.add_edge("human", "generate")
workflow.add_edge("generate", "finish")
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
        
    TODO:
    - 实现thread_id用于恢复
    - 添加流式输出支持
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
        "metadata": result.get("metadata", {})
    }


# 导出图实例
__all__ = ["graph", "run_agent"]
