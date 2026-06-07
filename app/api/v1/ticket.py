"""
工单 API 端点
工单创建、查询、统计
"""
import json
from typing import Optional
from fastapi import APIRouter, HTTPException, Query

from app.models.ticket import TicketCreate, TicketUpdate, Ticket, TicketListResponse, TicketStats
from app.core.database import create_ticket, get_ticket, list_tickets, update_ticket, get_ticket_stats
from agent.tools import simplify_tool_context


def _simplify_ticket_tool_context(ticket: Ticket) -> Ticket:
    """精简工单的 tool_context 字段"""
    if not ticket.tool_context:
        return ticket
    try:
        records = json.loads(ticket.tool_context)
        simplified = simplify_tool_context(records)
        ticket.tool_context = json.dumps(simplified, ensure_ascii=False)
    except (json.JSONDecodeError, TypeError):
        pass
    return ticket

router = APIRouter()


@router.post("/ticket/create", response_model=Ticket, summary="创建工单")
async def create_new_ticket(body: TicketCreate):
    """创建新工单，返回完整工单对象"""
    ticket = create_ticket(
        player_uid=body.player_uid,
        title=body.title,
        description=body.description,
        priority=body.priority,
    )
    return _simplify_ticket_tool_context(ticket)


@router.post("/ticket/submit", response_model=dict, summary="提交工单并触发Agent处理")
async def submit_ticket(body: TicketCreate):
    """
    玩家提交工单 → 创建工单记录 → 调用 Agent 处理 → 返回结果

    这是完整的"工单进来"入口，串联了工单创建和 Agent 处理。
    """
    from agent.graph import run_agent
    from app.core.pending_store import add_pending

    ticket = create_ticket(
        player_uid=body.player_uid,
        title=body.title,
        description=body.description,
        priority=body.priority,
    )

    session_id = f"ticket_{ticket.ticket_id}"
    result = await run_agent(
        session_id=session_id,
        user_id=body.player_uid,
        user_query=f"{body.title}\n{body.description}",
        ticket_id=ticket.ticket_id,
    )

    final_response = result.get("final_response", "")
    interrupt_info = result.get("interrupt_info")
    has_interrupt = result.get("has_interrupt")

    if has_interrupt:
        interrupt_payload = result.get("__interrupt__") or {}
        await add_pending(session_id, interrupt_payload)
        update_ticket(
            ticket.ticket_id,
            status="escalated",
            agent_reply=final_response,
            interrupt_reason=interrupt_info.get("reason", "") if interrupt_info else "",
        )
        return {
            "ticket_id": ticket.ticket_id,
            "status": "escalated",
            "agent_reply": final_response,
            "interrupt_reason": interrupt_info.get("reason", "") if interrupt_info else "",
            "requires_review": True,
            "session_id": session_id,
        }

    return {
        "ticket_id": ticket.ticket_id,
        "status": "resolved",
        "agent_reply": final_response,
        "requires_review": False,
    }


@router.get("/ticket/list", response_model=TicketListResponse, summary="工单列表")
async def list_all_tickets(
    status: Optional[str] = Query(default=None, description="按状态筛选"),
    player_uid: Optional[str] = Query(default=None, description="按玩家UID筛选"),
    page: int = Query(default=1, ge=1, description="页码"),
    page_size: int = Query(default=20, ge=1, le=100, description="每页数量"),
):
    """分页查询工单列表"""
    tickets, total = list_tickets(
        status=status,
        player_uid=player_uid,
        page=page,
        page_size=page_size,
    )
    tickets = [_simplify_ticket_tool_context(t) for t in tickets]
    return TicketListResponse(
        tickets=tickets,
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/ticket/stats", response_model=TicketStats, summary="工单统计")
async def get_ticket_statistics():
    """获取工单统计数据"""
    return get_ticket_stats()


@router.get("/ticket/{ticket_id}", response_model=Ticket, summary="查询工单详情")
async def get_ticket_detail(ticket_id: str):
    """根据工单号查询完整工单信息"""
    ticket = get_ticket(ticket_id)
    if ticket is None:
        raise HTTPException(status_code=404, detail=f"工单 {ticket_id} 不存在")
    return _simplify_ticket_tool_context(ticket)


@router.patch("/ticket/{ticket_id}", response_model=Ticket, summary="更新工单（客服处理）")
async def update_ticket_detail(ticket_id: str, body: TicketUpdate):
    """客服手动更新工单状态和处理结果"""
    ticket = get_ticket(ticket_id)
    if ticket is None:
        raise HTTPException(status_code=404, detail=f"工单 {ticket_id} 不存在")

    updated = update_ticket(
        ticket_id,
        status=body.status,
        agent_reply=body.agent_reply,
        category=body.category,
        reviewer_id=body.reviewer_id,
    )
    if updated is None:
        raise HTTPException(status_code=500, detail="更新工单失败")
    return _simplify_ticket_tool_context(updated)
