"""
工单 API 端点
玩家接口需 JWT 鉴权，只能操作自己的工单；统计/更新需审核员 token。
"""
import json
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from app.models.ticket import TicketCreate, TicketUpdate, Ticket, TicketListResponse, TicketStats
from app.repositories.database import create_ticket, get_ticket, list_tickets, update_ticket, get_ticket_stats
from app.api.deps import (
    CurrentPlayer,
    get_current_player,
    require_reviewer_token,
    require_ticket_owner,
)
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
async def create_new_ticket(
    body: TicketCreate,
    player: CurrentPlayer = Depends(get_current_player),
):
    """创建新工单（player_uid 以 token 为准）"""
    ticket = create_ticket(
        player_uid=player.user_id,
        title=body.title,
        description=body.description,
        priority=body.priority,
    )
    return _simplify_ticket_tool_context(ticket)


@router.post("/ticket/submit", response_model=dict, summary="提交工单并触发Agent处理")
async def submit_ticket(
    body: TicketCreate,
    player: CurrentPlayer = Depends(get_current_player),
):
    """玩家提交工单 → 创建记录 → 调用 Agent 处理"""
    from agent.graph import run_agent

    ticket = create_ticket(
        player_uid=player.user_id,
        title=body.title,
        description=body.description,
        priority=body.priority,
    )

    session_id = f"ticket_{ticket.ticket_id}"
    result = await run_agent(
        session_id=session_id,
        user_id=player.user_id,
        user_query=f"{body.title}\n{body.description}",
        ticket_id=ticket.ticket_id,
    )

    final_response = result.get("final_response", "")
    human_offer = result.get("human_offer")

    if human_offer:
        return {
            "ticket_id": ticket.ticket_id,
            "status": "human_offer",
            "agent_reply": final_response,
            "human_offer": human_offer,
            "session_id": session_id,
        }

    return {
        "ticket_id": ticket.ticket_id,
        "status": "resolved",
        "agent_reply": final_response,
    }


@router.get("/ticket/list", response_model=TicketListResponse, summary="我的工单列表")
async def list_my_tickets(
    status: Optional[str] = Query(default=None, description="按状态筛选"),
    page: int = Query(default=1, ge=1, description="页码"),
    page_size: int = Query(default=20, ge=1, le=100, description="每页数量"),
    player: CurrentPlayer = Depends(get_current_player),
):
    """只返回当前登录玩家的工单"""
    tickets, total = list_tickets(
        status=status,
        player_uid=player.user_id,
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


@router.get("/ticket/stats", response_model=TicketStats, summary="工单统计（客服后台）")
async def get_ticket_statistics(
    _token: str = Depends(require_reviewer_token),
):
    """获取工单统计数据（需审核员 token）"""
    return get_ticket_stats()


@router.get("/ticket/{ticket_id}", response_model=Ticket, summary="查询工单详情")
async def get_ticket_detail(
    ticket_id: str,
    player: CurrentPlayer = Depends(get_current_player),
):
    """根据工单号查询，仅能查看自己的工单"""
    ticket = get_ticket(ticket_id)
    if ticket is None:
        raise HTTPException(status_code=404, detail=f"工单 {ticket_id} 不存在")
    require_ticket_owner(ticket.player_uid, player)
    return _simplify_ticket_tool_context(ticket)


@router.patch("/ticket/{ticket_id}", response_model=Ticket, summary="更新工单（客服处理）")
async def update_ticket_detail(
    ticket_id: str,
    body: TicketUpdate,
    _token: str = Depends(require_reviewer_token),
):
    """客服手动更新工单（需审核员 token）"""
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
