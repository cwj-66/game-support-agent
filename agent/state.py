"""LangGraph Agent 状态定义。"""

import operator
from typing import TypedDict, Annotated, List, Optional, Dict, Any
from langchain_core.messages import BaseMessage, HumanMessage
from langgraph.graph.message import add_messages
from datetime import datetime, timezone


class AgentState(TypedDict):
    """Agent 执行状态，由 checkpointer 持久化。"""
    messages: Annotated[List[BaseMessage], add_messages]
    user_query: str
    user_id: str
    session_id: str
    human_mode: bool
    tool_calls: List[Dict[str, Any]]
    final_response: Optional[str]
    ticket_id: Optional[str]
    metadata: Dict[str, Any]
    node_trace: Annotated[List[str], operator.add]
    ticket_offer: Optional[Dict[str, Any]]
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
        "ticket_offer": None,
        "human_offer": None,
        "final_response": None,
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
