"""工单 API。

建单入口受访客频率限制；带 Idempotency-Key 的重试返回首次结果。
/ticket/submit 会运行 Agent，因此同样占用全站问答名额。
"""
import json
import logging
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request

from app.models.ticket import TicketCreate, TicketUpdate, Ticket, TicketListResponse, TicketStats
from app.repositories.database import create_ticket, get_ticket, list_tickets, update_ticket, get_ticket_stats
from app.api.deps import (
    CurrentPlayer,
    get_current_player,
    require_reviewer_token,
    require_ticket_owner,
)
from app.core.blocking import run_blocking
from app.core.exceptions import AppException
from app.services.admission import AdmissionTicket
from app.services.idempotency import load_result, save_result, valid_request_id
from app.services.rate_limit import enforce_chat_rate
from app.services.session_lock import session_guard
from app.services.turn_runner import execute_with_deadline, to_app_exception
from agent.tools import simplify_tool_context

logger = logging.getLogger(__name__)


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
    request: Request,
    player: CurrentPlayer = Depends(get_current_player),
    idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key"),
):
    """创建新工单（player_uid 以 token 为准）"""
    await enforce_chat_rate(request, scope="ticket")
    key = valid_request_id(idempotency_key)
    scope = f"ticket-create:{player.user_id}"
    if key is None:
        ticket = await run_blocking(
            create_ticket, player_uid=player.user_id, title=body.title,
            description=body.description, priority=body.priority,
        )
        return _simplify_ticket_tool_context(ticket)
    async with session_guard(f"{scope}:{key}"):
        cached = await load_result(scope, key)
        if cached:
            return Ticket(**cached)
        ticket = await run_blocking(
            create_ticket, player_uid=player.user_id, title=body.title,
            description=body.description, priority=body.priority,
        )
        await save_result(scope, key, ticket.model_dump())
        return _simplify_ticket_tool_context(ticket)


@router.post("/ticket/submit", response_model=dict, summary="提交工单并触发Agent处理")
async def submit_ticket(
    body: TicketCreate,
    request: Request,
    player: CurrentPlayer = Depends(get_current_player),
    idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key"),
):
    """玩家提交工单 → 取得问答名额 → 创建记录 → 调用 Agent 处理"""
    from agent.graph import run_agent

    await enforce_chat_rate(request, scope="ticket")
    key = valid_request_id(idempotency_key)
    scope = f"ticket-submit:{player.user_id}"

    async with session_guard(f"{scope}:{key or uuid.uuid4().hex}") as guard:
        cached = await load_result(scope, key)
        if cached:
            return cached

        admission = AdmissionTicket()
        try:
            # 决策：先取得名额再建单，队列已满时不会留下一张没有 Agent 处理的工单。
            await admission.wait(cancelled=lambda: guard.cancel_requested)
            ticket = await run_blocking(
                create_ticket, player_uid=player.user_id, title=body.title,
                description=body.description, priority=body.priority,
            )
            session_id = f"ticket_{ticket.ticket_id}"
            result = await execute_with_deadline(
                run_agent(
                    session_id=session_id,
                    user_id=player.user_id,
                    user_query=f"{body.title}\n{body.description}",
                    ticket_id=ticket.ticket_id,
                ),
                guard,
            )
        except AppException:
            raise
        except Exception as exc:
            logger.warning("ticket submit failed: %s", type(exc).__name__)
            raise to_app_exception(exc)
        finally:
            await admission.release()

        final_response = result.get("final_response", "")
        human_offer = result.get("human_offer")
        if human_offer:
            payload = {
                "ticket_id": ticket.ticket_id,
                "status": "human_offer",
                "agent_reply": final_response,
                "human_offer": human_offer,
                "session_id": session_id,
            }
        else:
            payload = {
                "ticket_id": ticket.ticket_id,
                "status": "resolved",
                "agent_reply": final_response,
            }
        await save_result(scope, key, payload)
        return payload


@router.get("/ticket/list", response_model=TicketListResponse, summary="我的工单列表")
async def list_my_tickets(
    status: Optional[str] = Query(default=None, description="按状态筛选"),
    page: int = Query(default=1, ge=1, description="页码"),
    page_size: int = Query(default=20, ge=1, le=100, description="每页数量"),
    player: CurrentPlayer = Depends(get_current_player),
):
    """只返回当前登录玩家的工单"""
    tickets, total = await run_blocking(
        list_tickets,
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
    return await run_blocking(get_ticket_stats)


@router.get("/ticket/admin/list", response_model=TicketListResponse, summary="全部工单（客服）")
async def list_all_tickets(
    status: Optional[str] = Query(default=None, description="按状态筛选"),
    player_uid: Optional[str] = Query(default=None, description="按玩家 UID 筛选"),
    page: int = Query(default=1, ge=1, description="页码"),
    page_size: int = Query(default=20, ge=1, le=100, description="每页数量"),
    _token: str = Depends(require_reviewer_token),
):
    """从数据库列出全部工单，不限玩家。"""
    tickets, total = await run_blocking(
        list_tickets,
        status=status,
        player_uid=player_uid or None,
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


@router.get("/ticket/admin/{ticket_id}", response_model=Ticket, summary="工单详情（客服）")
async def get_admin_ticket_detail(
    ticket_id: str,
    _token: str = Depends(require_reviewer_token),
):
    """客服查看任意工单详情。"""
    ticket = await run_blocking(get_ticket, ticket_id)
    if ticket is None:
        raise HTTPException(status_code=404, detail=f"工单 {ticket_id} 不存在")
    return _simplify_ticket_tool_context(ticket)


@router.get("/ticket/{ticket_id}", response_model=Ticket, summary="查询工单详情")
async def get_ticket_detail(
    ticket_id: str,
    player: CurrentPlayer = Depends(get_current_player),
):
    """根据工单号查询，仅能查看自己的工单"""
    ticket = await run_blocking(get_ticket, ticket_id)
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
    ticket = await run_blocking(get_ticket, ticket_id)
    if ticket is None:
        raise HTTPException(status_code=404, detail=f"工单 {ticket_id} 不存在")

    updated = await run_blocking(
        update_ticket,
        ticket_id,
        status=body.status,
        agent_reply=body.agent_reply,
        category=body.category,
        reviewer_id=body.reviewer_id,
        human_reviewed=True,
    )
    if updated is None:
        raise HTTPException(status_code=500, detail="更新工单失败")
    return _simplify_ticket_tool_context(updated)
