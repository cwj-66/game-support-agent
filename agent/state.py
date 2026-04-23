"""
AgentState 定义
LangGraph图的状态结构，包含消息、中断标记、人工审核结果等
"""

from typing import TypedDict, Annotated, List, Optional, Dict, Any, Literal
from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages
from datetime import datetime


# 人工审核操作类型
ReviewAction = Literal["APPROVE", "MODIFY", "OVERRIDE"]


class InterruptInfo(TypedDict, total=False):
    """
    中断信息结构
    
    当触发human-in-loop时，记录中断原因和上下文
    """
    # 是否触发中断
    should_interrupt: bool
    # 中断原因：敏感词/置信度低/其他
    reason: str
    # 风险等级：low/medium/high
    level: str
    # 检测到的敏感词（如果有）
    sensitive_words: List[str]
    # 置信度分数（0-1）
    confidence: Optional[float]
    # 原始节点输出需要审核
    pending_content: Optional[str]


class HumanReviewResult(TypedDict, total=False):
    """
    人工审核结果
    
    人工操作员对Agent输出的审核决定
    """
    # 操作类型
    action: ReviewAction
    # 操作员ID
    reviewer_id: str
    # 审核时间
    timestamp: str
    # 修改后的内容（MODIFY时使用）
    modified_content: Optional[str]
    # 备注说明
    notes: Optional[str]
    # 是否通过审核
    approved: bool


class AgentState(TypedDict):
    """
    LangGraph 主状态定义
    
    这是贯穿整个Agent执行流程的状态容器，
    会被checkpointer持久化，支持断点恢复。
    
    Attributes:
        messages: 对话历史（使用add_messages reducer自动追加）
        user_query: 当前用户原始查询
        session_id: 会话唯一标识
        interrupt_info: 中断触发信息
        human_review: 人工审核结果
        tool_calls: 已执行的MCP工具调用记录
        final_response: 最终回复内容（待审核或直接发送）
        metadata: 额外运行时元数据
    """
    # 核心对话历史，使用add_messages自动合并
    messages: Annotated[List[BaseMessage], add_messages]
    
    # 当前用户查询
    user_query: str
    
    # 会话ID，用于状态隔离
    session_id: str
    
    # 中断触发信息（由detector节点设置）
    interrupt_info: Optional[InterruptInfo]
    
    # 人工审核结果（由human_node等待设置）
    human_review: Optional[HumanReviewResult]
    
    # 工具调用记录，用于审计
    tool_calls: List[Dict[str, Any]]
    
    # Agent生成的最终回复（审核前）
    final_response: Optional[str]
    
    # 运行时元数据
    metadata: Dict[str, Any]


def create_initial_state(session_id: str, user_query: str) -> AgentState:
    """
    创建初始状态
    
    Args:
        session_id: 会话ID
        user_query: 用户初始问题
        
    Returns:
        初始化的AgentState
    """
    return {
        "messages": [],
        "user_query": user_query,
        "session_id": session_id,
        "interrupt_info": None,
        "human_review": None,
        "tool_calls": [],
        "final_response": None,
        "metadata": {
            "created_at": datetime.utcnow().isoformat(),
            "version": "1.0.0"
        }
    }


# TODO: 未来扩展
# - 添加多轮对话的token计数
# - 添加用户画像（VIP等级等）
# - 添加上下文窗口管理（截断策略）
