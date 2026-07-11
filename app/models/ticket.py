"""
工单数据模型
"""
from typing import Optional, List, Literal
from pydantic import BaseModel, Field
from datetime import datetime


TicketStatus = Literal["pending", "processing", "resolved", "escalated"]
TicketPriority = Literal["P0", "P1", "P2"]
TicketCategory = Literal["gameplay", "account", "payment", "bug", "complaint", "other"]


class TicketCreate(BaseModel):
    """创建工单请求（player_uid 由 JWT 提供，无需传入）"""
    player_uid: Optional[str] = Field(
        default=None,
        description="（已废弃）由 JWT 鉴权自动填充",
        max_length=64,
    )
    title: str = Field(..., description="工单标题", min_length=1, max_length=200)
    description: str = Field(..., description="问题描述", min_length=1, max_length=2000)
    priority: TicketPriority = Field(default="P2", description="优先级：P0 分钟级响应、P1 小时级、P2 天级")


class TicketUpdate(BaseModel):
    """更新工单请求（客服手动处理工单时使用）"""
    status: Optional[TicketStatus] = Field(default=None, description="工单状态")
    agent_reply: Optional[str] = Field(default=None, max_length=2000, description="客服处理结果/回复")
    category: Optional[TicketCategory] = Field(default=None, description="分类")
    reviewer_id: Optional[str] = Field(default=None, description="处理人ID")


class Ticket(BaseModel):
    """工单完整模型"""
    ticket_id: str = Field(..., description="工单号")
    player_uid: str
    title: str
    description: str
    category: Optional[TicketCategory] = Field(default=None, description="Agent分类结果")
    priority: TicketPriority = "P2"
    status: TicketStatus = "pending"
    agent_reply: Optional[str] = Field(default=None, description="Agent自动回复")
    human_reviewed: bool = Field(default=False, description="是否经人工处理")
    reviewer_id: Optional[str] = None
    interrupt_reason: Optional[str] = Field(default=None, description="转人工原因")
    tool_context: Optional[str] = Field(default=None, description="工具调用上下文（JSON）")
    session_id: Optional[str] = Field(default=None, description="关联的Agent会话ID")
    created_at: str = Field(default_factory=lambda: datetime.now().isoformat())
    resolved_at: Optional[str] = None


class TicketListResponse(BaseModel):
    """工单列表响应"""
    tickets: List[Ticket]
    total: int
    page: int = 1
    page_size: int = 20


class TicketStats(BaseModel):
    """工单统计"""
    total: int
    pending: int
    processing: int
    resolved: int
    escalated: int
    auto_resolved: int = Field(description="Agent自动解决数")
    human_reviewed: int = Field(description="人工处理数")
    by_category: dict = Field(default_factory=dict)
    by_priority: dict = Field(default_factory=dict)
