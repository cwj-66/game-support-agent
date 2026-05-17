"""
Human-in-loop 数据结构定义
审计日志、中断决策、审核操作等核心数据结构
"""

from typing import TypedDict, Optional, List, Dict, Any, Literal
from dataclasses import dataclass, field
from datetime import datetime


# 审核操作类型
ReviewAction = Literal["APPROVE", "MODIFY", "OVERRIDE"]


@dataclass
class InterruptDecision:
    """
    中断决策结果
    
    由InterruptDetector生成，决定是否触发人工审核
    
    Attributes:
        should_interrupt: 是否中断
        reason: 中断原因说明
        level: 风险等级 (low/medium/high)
        sensitive_words: 检测到的敏感词
    """
    should_interrupt: bool
    reason: str
    level: str = "low"  # low/medium/high
    sensitive_words: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典，用于序列化"""
        return {
            "should_interrupt": self.should_interrupt,
            "reason": self.reason,
            "level": self.level,
            "sensitive_words": self.sensitive_words,
        }


@dataclass 
class ReviewOperation:
    """
    审核操作记录
    
    人工审核员执行的操作
    """
    action: ReviewAction
    reviewer_id: str
    timestamp: str
    modified_content: Optional[str] = None
    notes: Optional[str] = None
    approved: bool = False
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "action": self.action,
            "reviewer_id": self.reviewer_id,
            "timestamp": self.timestamp,
            "modified_content": self.modified_content,
            "notes": self.notes,
            "approved": self.approved
        }


@dataclass
class AuditLogEntry:
    """
    审计日志条目
    
    记录完整的Human-in-loop流程，用于事后追溯
    
    Attributes:
        audit_id: 审计记录唯一ID
        session_id: 关联会话ID
        user_query: 用户原始问题
        agent_raw_response: Agent原始输出（审核前）
        interrupt_decision: 中断决策
        review_operation: 人工审核操作
        final_response: 最终发给用户的回复
        timestamps: 各阶段时间戳
    """
    audit_id: str
    session_id: str
    user_query: str
    agent_raw_response: str
    
    # 中断决策
    interrupt_triggered: bool
    interrupt_reason: str
    interrupt_level: str
    
    # 审核操作
    review_action: Optional[str] = None
    reviewer_id: Optional[str] = None
    review_timestamp: Optional[str] = None
    was_modified: bool = False
    
    # 最终结果
    final_response: str = ""
    
    # 时间戳
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    completed_at: Optional[str] = None
    
    # 额外元数据
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为JSON可序列化的字典"""
        return {
            "audit_id": self.audit_id,
            "session_id": self.session_id,
            "user_query": self.user_query,
            "agent_raw_response": self.agent_raw_response,
            "interrupt_triggered": self.interrupt_triggered,
            "interrupt_reason": self.interrupt_reason,
            "interrupt_level": self.interrupt_level,
            "review_action": self.review_action,
            "reviewer_id": self.reviewer_id,
            "review_timestamp": self.review_timestamp,
            "was_modified": self.was_modified,
            "final_response": self.final_response,
            "created_at": self.created_at,
            "completed_at": self.completed_at,
            "metadata": self.metadata
        }
    
    def mark_completed(self):
        """标记审计记录完成"""
        self.completed_at = datetime.utcnow().isoformat()


# TypedDict版本（用于与AgentState兼容）
class AuditLogEntryDict(TypedDict, total=False):
    """审计日志条目的TypedDict版本"""
    audit_id: str
    session_id: str
    user_query: str
    agent_raw_response: str
    interrupt_triggered: bool
    interrupt_reason: str
    interrupt_level: str
    review_action: Optional[str]
    reviewer_id: Optional[str]
    review_timestamp: Optional[str]
    was_modified: bool
    final_response: str
    created_at: str
    completed_at: Optional[str]
    metadata: Dict[str, Any]


# 待审核任务状态
class PendingTaskStatus:
    """待审核任务状态枚举"""
    WAITING = "waiting"           # 等待审核
    IN_PROGRESS = "in_progress"   # 审核中（被某个审核员领取）
    COMPLETED = "completed"       # 已完成
    EXPIRED = "expired"           # 超时过期


@dataclass
class PendingTask:
    """
    待审核任务
    
    存储在等待队列中的任务
    """
    task_id: str
    session_id: str
    user_query: str
    agent_response: str
    interrupt_reason: str
    risk_level: str
    status: str = PendingTaskStatus.WAITING
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    assigned_to: Optional[str] = None
    assigned_at: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "task_id": self.task_id,
            "session_id": self.session_id,
            "user_query": self.user_query,
            "agent_response": self.agent_response,
            "interrupt_reason": self.interrupt_reason,
            "risk_level": self.risk_level,
            "status": self.status,
            "created_at": self.created_at,
            "assigned_to": self.assigned_to,
            "assigned_at": self.assigned_at
        }


# TODO: 未来扩展
# - 添加审核员绩效统计结构
# - 添加审核质量评分结构
# - 添加批量操作支持
