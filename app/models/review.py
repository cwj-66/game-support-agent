"""
人工审核操作模型
定义审核员的操作请求和响应
"""

from typing import Optional, Dict, Any, Literal, List
from pydantic import BaseModel, Field
from datetime import datetime


# 审核操作类型（当前仅实现 APPROVE）
ReviewActionType = Literal["APPROVE"]


class ReviewAction(BaseModel):
    """
    人工审核操作请求

    Attributes:
        session_id: 需要审核的会话ID
        action: 操作类型（仅 APPROVE）
        reviewer_id: 审核员标识
        modified_content: 审核员回复内容
        notes: 审核备注
    """
    session_id: str = Field(..., description="会话ID")
    action: ReviewActionType = Field(
        ...,
        description="审核操作: APPROVE-通过"
    )
    reviewer_id: str = Field(..., description="审核员ID")
    modified_content: Optional[str] = Field(
        default=None,
        description="人工回复内容"
    )
    notes: Optional[str] = Field(
        default=None,
        description="审核备注说明"
    )

    class Config:
        json_schema_extra = {
            "example": {
                "session_id": "sess_12345",
                "action": "APPROVE",
                "reviewer_id": "admin_001",
                "modified_content": "经过确认，您的账号状态正常...",
                "notes": "已核实账号信息"
            }
        }


class ReviewTask(BaseModel):
    """
    待审核任务模型

    展示在审核队列中的任务信息
    """
    review_id: str = Field(..., description="审核任务唯一ID")
    session_id: str = Field(..., description="关联会话ID")
    user_query: str = Field(..., description="用户原始问题")
    agent_response: str = Field(..., description="Agent生成的回复")
    interrupt_reason: str = Field(..., description="触发审核的原因")
    risk_level: str = Field(..., description="风险等级: low/medium/high")
    created_at: str = Field(..., description="任务创建时间")
    wait_time_seconds: int = Field(default=0, description="等待审核的秒数")
    pending_content: Optional[str] = Field(default=None, description="工具执行上下文（审核员参考）")

    class Config:
        json_schema_extra = {
            "example": {
                "review_id": "rev_abc123",
                "session_id": "sess_12345",
                "user_query": "我要投诉你们封号",
                "agent_response": "关于封号问题...",
                "interrupt_reason": "检测到敏感词: 投诉",
                "risk_level": "high",
                "created_at": "2024-01-01T10:00:00",
                "wait_time_seconds": 120
            }
        }


class ReviewResponse(BaseModel):
    """审核操作响应"""
    success: bool = Field(..., description="操作是否成功")
    review_id: str = Field(..., description="审核任务ID")
    session_id: str = Field(..., description="会话ID")
    action: ReviewActionType = Field(..., description="执行的操作")
    final_response: str = Field(..., description="最终发给用户的回复")
    processed_at: str = Field(..., description="处理时间")


class PendingReviewsResponse(BaseModel):
    """待审核任务列表响应"""
    total: int = Field(..., description="待审核任务总数")
    items: list[ReviewTask] = Field(default_factory=list, description="任务列表")


class ReviewHistoryItem(BaseModel):
    """审核历史记录项"""
    review_id: str = Field(..., description="审核ID")
    session_id: str = Field(..., description="会话ID")
    action: ReviewActionType = Field(..., description="操作类型")
    reviewer_id: str = Field(..., description="审核员")
    timestamp: str = Field(..., description="审核时间")
    has_modification: bool = Field(default=False, description="是否有内容修改")


class ReviewHistoryResponse(BaseModel):
    """审核历史响应"""
    total: int = Field(..., description="总记录数")
    items: List[ReviewHistoryItem] = Field(default_factory=list)
