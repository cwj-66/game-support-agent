"""
对话请求/响应模型
"""

from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field


class TicketOffer(BaseModel):
    """工单创建确认请求，前端展示「是/否」按钮"""
    summary: str = Field(..., description="问题摘要，展示给用户确认")
    issue_type: str = Field(..., description="问题类型：account_ban/payment/bug/other")
    display_text: str = Field(default="是否为您生成工单？", description="展示文案")


class HumanOffer(BaseModel):
    """转人工确认请求，前端展示「是/否」按钮"""
    summary: str = Field(..., description="问题摘要，展示给用户和客服")
    display_text: str = Field(default="是否为你转人工？", description="展示文案")


class ChatRequest(BaseModel):
    """对话请求"""
    session_id: str = Field(
        ...,
        description="会话ID，用于关联同一用户的多次对话",
        min_length=1,
        max_length=64
    )
    user_id: Optional[str] = Field(
        default=None,
        description="兼容旧客户端；实际 UID 由 JWT 鉴权提供",
        max_length=64,
    )
    message: str = Field(
        ...,
        description="用户消息内容",
        min_length=1,
        max_length=2000
    )
    context: Optional[Dict[str, Any]] = Field(
        default=None,
        description="额外上下文，如用户等级、VIP状态等"
    )


class ChatResponse(BaseModel):
    """对话响应"""
    session_id: str = Field(..., description="会话ID")
    status: str = Field(default="ok", description="响应状态: ok 正常 / human_chat 人工接待中")
    response: str = Field(..., description="回复内容")
    sources: Optional[List[Dict[str, Any]]] = Field(
        default=None,
        description="知识来源引用"
    )
    ticket_offer: Optional[TicketOffer] = Field(
        default=None,
        description="工单确认请求，非 None 时前端展示「是/否」按钮"
    )
    human_offer: Optional[HumanOffer] = Field(
        default=None,
        description="转人工确认请求，非 None 时前端展示「是/否」按钮"
    )
    metadata: Dict[str, Any] = Field(
        default_factory=dict,
        description="额外元数据，如执行时间等"
    )


class ChatHistoryItem(BaseModel):
    """单条对话历史记录"""
    role: str = Field(..., description="角色: user/assistant")
    content: str = Field(..., description="消息内容")
    timestamp: str = Field(..., description="时间戳ISO格式")
    is_human: bool = Field(default=False, description="是否为人工客服消息")


class ChatHistoryResponse(BaseModel):
    """对话历史响应"""
    session_id: str = Field(..., description="会话ID")
    messages: List[ChatHistoryItem] = Field(default_factory=list, description="消息列表")
    total: int = Field(..., description="总消息数")

