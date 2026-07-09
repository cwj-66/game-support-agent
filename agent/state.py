"""
AgentState 定义
LangGraph图的状态结构，包含消息、中断标记、人工审核结果等
"""

import operator
from typing import TypedDict, Annotated, List, Optional, Dict, Any, Literal
from langchain_core.messages import BaseMessage, HumanMessage
from langgraph.graph.message import add_messages
from datetime import datetime, timezone


# 人工审核操作类型
ReviewAction = Literal["APPROVE", "MODIFY", "OVERRIDE"]


class InterruptInfo(TypedDict, total=False):
    """
    中断信息结构

    由 tool_exec（escalate 两路）或 detector_node（安全兜底）写入，
    供 human_node 读取做审核展示，route_from_reasoning / route_from_detector 拿它做路由判断
    """
    # 是否触发中断
    should_interrupt: bool
    # 中断原因，例如 '检测到敏感词: 私下转账'
    reason: str
    # 风险等级: low / medium / high
    level: str
    # 检测到的敏感词列表，没有则为空
    sensitive_words: List[str]
    # 待审核的原始内容，审核员看到的就是这个
    pending_content: Optional[str]
    # 中断来源: llm_escalate（LLM主动升等）/ auto_escalate（系统兜底）/ detector（安全检测）
    source: Optional[str]


class HumanReviewResult(TypedDict, total=False):
    """
    人工审核结果 —— 全链路唯一标准

    流向：human.py 构建 → Command(resume=...) → interrupt() 返回
         → human_node 写入 state.human_review → generate_response_node 读取

    total=False 表示所有字段均可选，但 action 和 reviewer_id 实际必有
    """
    # 审核操作: APPROVE=通过原文 / MODIFY=修改后通过 / OVERRIDE=完全重写
    action: ReviewAction
    # 审核员标识，例如 "admin_001"
    reviewer_id: str
    # MODIFY 或 OVERRIDE 时必填，人工编写的新回复内容；APPROVE 时为 None
    modified_content: Optional[str]
    # 审核备注，审核员可选的文字说明
    notes: Optional[str]


# LangGraph主状态定义
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
        tool_calls: 已执行的工具调用记录
        final_response: 最终回复内容（待审核或直接发送）
        metadata: 额外运行时元数据
    """
    # 对话历史，add_messages reducer 自动追加，HumanMessage / AIMessage / ToolMessage 都在这
    messages: Annotated[List[BaseMessage], add_messages]
    # 本轮用户原始问题，整个执行过程中不变
    user_query: str
    # 玩家游戏UID，由API层传入，整个执行过程中不变
    user_id: str
    # 会话唯一标识，也是 checkpointer 的 thread_id
    session_id: str
    # 中断触发信息，由 tool_exec（escalate）或 detector_node（安全兜底）设置
    interrupt_info: Optional[InterruptInfo]
    # 人工审核结果，human_node 从 interrupt() 获取并写入，generate_response_node 读取
    human_review: Optional[HumanReviewResult]
    # 人工回复内容（简化版），human_node 写入，finish_node 读取为最终回复
    human_reply: Optional[str]
    # 当前是否处于人工接待模式（转人工后设为 True，客服关闭后设为 False）
    human_mode: bool
    # 人工接待操作：continue（继续聊）/ close（结束接待）
    human_action: Optional[str]
    # 全部轮次的工具调用审计记录，tool_exec_node 每轮追加（非覆盖）
    tool_calls: List[Dict[str, Any]]
    # 最终回复，generate_response_node 生成，可能是 LLM 写的也可能是人工覆盖的
    final_response: Optional[str]
    # 关联的工单 ID（可选），从 API 层传入
    ticket_id: Optional[str]
    # 运行时元数据，各节点以读-改-写模式往里塞东西，同一个 key 后来者覆盖前者
    metadata: Dict[str, Any]
    # 节点执行路径追踪，每个节点进入时 append 自己的名字，按执行顺序记录
    node_trace: Annotated[List[str], operator.add]
    # 待确认的工单 offer，由 propose_ticket 工具触发，用户点「是」后才真正创建
    ticket_offer: Optional[Dict[str, Any]]

# 创建每轮对话输入（增量更新，配合 checkpointer 使用）
def create_turn_input(
    session_id: str,
    user_id: str,
    user_query: str,
    ticket_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    构造本轮 Agent 输入（增量 patch，非全量重置）

    只更新本轮变化的字段，其余字段由 checkpointer 从上一 checkpoint 继承。
    会话过期后 checkpoint 已被清除，此时等同全新会话。

    Args:
        session_id: 会话 ID（= checkpointer thread_id）
        user_id: 玩家 UID
        user_query: 本轮用户原话
        ticket_id: 关联工单 ID（可选）

    Returns:
        本轮 state patch
    """
    return {
        # 玩家原话写入 messages，供同会话多轮 LLM 上下文使用
        "messages": [HumanMessage(content=user_query)],
        "user_query": user_query,
        "user_id": user_id,
        "session_id": session_id,
        "ticket_id": ticket_id,
        # 每轮 ReAct 工具审计重新开始
        "tool_calls": [],
        # 每轮运行时 metadata 重置，不跨轮携带
        "metadata": {},
    }


# 创建对话初始状态（仅用于测试或无 checkpointer 的场景）
def create_initial_state(
    session_id: str,
    user_id: str,
    user_query: str,
    ticket_id: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> AgentState:
    """
    创建完整初始状态（测试 / 无 checkpointer 场景用）

    生产路径请用 create_turn_input + checkpointer。
    """
    return {
        "messages": [],
        "user_query": user_query,
        "user_id": user_id,
        "session_id": session_id,
        "ticket_id": ticket_id,
        "interrupt_info": None,
        "human_review": None,
        "human_reply": None,
        "human_mode": False,
        "human_action": None,
        "tool_calls": [],
        "final_response": None,
        "ticket_offer": None,
        "node_trace": [],
        "metadata": metadata or {
            "created_at": datetime.now(timezone.utc).isoformat(),
            "version": "1.0.0"
        },
    }


# TODO: 未来扩展
# - 添加上下文窗口截断（同会话 messages 过长时）
