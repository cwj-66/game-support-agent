"""
AgentState 定义
LangGraph图的状态结构，包含消息、人工接待标记、工单提议等
"""

import operator
from typing import TypedDict, Annotated, List, Optional, Dict, Any
from langchain_core.messages import BaseMessage, HumanMessage
from langgraph.graph.message import add_messages
from datetime import datetime, timezone


# LangGraph主状态定义
class AgentState(TypedDict):
    """
    LangGraph 主状态定义

    这是贯穿整个Agent执行流程的状态容器，
    会被checkpointer持久化，支持断点恢复。
    """
    # 对话历史，add_messages reducer 自动追加
    messages: Annotated[List[BaseMessage], add_messages]
    # 本轮用户原始问题
    user_query: str
    # 玩家游戏UID
    user_id: str
    # 会话唯一标识，也是 checkpointer 的 thread_id
    session_id: str
    # 当前是否处于人工接待模式（玩家确认转人工后由 API 设为 True）
    human_mode: bool
    # 全部轮次的工具调用审计记录
    tool_calls: List[Dict[str, Any]]
    # 最终回复
    final_response: Optional[str]
    # 关联的工单 ID（可选）
    ticket_id: Optional[str]
    # 运行时元数据
    metadata: Dict[str, Any]
    # 节点执行路径追踪
    node_trace: Annotated[List[str], operator.add]
    # 待确认的工单 offer
    ticket_offer: Optional[Dict[str, Any]]
    # 待确认的转人工 offer
    human_offer: Optional[Dict[str, Any]]


def create_turn_input(
    session_id: str,
    user_id: str,
    user_query: str,
    ticket_id: Optional[str] = None,
) -> Dict[str, Any]:
    """构造本轮 Agent 输入（增量 patch，非全量重置）"""
    return {
        "messages": [HumanMessage(content=user_query)],
        "user_query": user_query,
        "user_id": user_id,
        "session_id": session_id,
        "ticket_id": ticket_id,
        "tool_calls": [],
        "metadata": {},
    }


def create_initial_state(
    session_id: str,
    user_id: str,
    user_query: str,
    ticket_id: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> AgentState:
    """创建完整初始状态（测试 / 无 checkpointer 场景用）"""
    return {
        "messages": [],
        "user_query": user_query,
        "user_id": user_id,
        "session_id": session_id,
        "ticket_id": ticket_id,
        "human_mode": False,
        "tool_calls": [],
        "final_response": None,
        "ticket_offer": None,
        "human_offer": None,
        "node_trace": [],
        "metadata": metadata or {
            "created_at": datetime.now(timezone.utc).isoformat(),
            "version": "1.0.0"
        },
    }
