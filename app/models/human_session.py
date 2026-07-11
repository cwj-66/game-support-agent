"""
人工接待会话模型
定义待接待列表与客服回复的请求/响应
"""

from typing import Optional, Literal
from pydantic import BaseModel, Field


HumanSessionAction = Literal["continue", "close"]


class PendingHumanSession(BaseModel):
    """待接待会话（展示在客服工作台）"""
    session_id: str = Field(..., description="会话ID")
    user_query: str = Field(..., description="用户原始问题")
    agent_response: str = Field(..., description="Agent 最后回复或问题摘要")
    interrupt_reason: str = Field(..., description="转人工原因")
    risk_level: str = Field(..., description="风险等级: low/medium/high")
    created_at: str = Field(..., description="进入待接待队列的时间")
    wait_time_seconds: int = Field(default=0, description="等待接待的秒数")
    pending_content: Optional[str] = Field(default=None, description="上下文摘要（客服参考）")
    last_user_at: Optional[str] = Field(default=None, description="用户最后发言时间 ISO8601")
    last_agent_at: Optional[str] = Field(default=None, description="客服最后发言时间 ISO8601")


class HumanReplyResponse(BaseModel):
    """客服回复操作响应"""
    success: bool = Field(..., description="操作是否成功")
    session_id: str = Field(..., description="会话ID")
    action: HumanSessionAction = Field(..., description="接待操作: continue / close")
    final_response: str = Field(..., description="本次发送给玩家的消息")
    processed_at: str = Field(..., description="处理时间")


class PendingHumanSessionsResponse(BaseModel):
    """待接待会话列表响应"""
    total: int = Field(..., description="待接待会话总数")
    items: list[PendingHumanSession] = Field(default_factory=list, description="会话列表")
