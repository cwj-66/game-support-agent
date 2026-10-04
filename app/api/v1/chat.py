"""对话 API：发送消息、历史、SSE 流式。

所有修改会话状态的入口都按「鉴权与归属 → 频率限制 → 会话锁 → 幂等 → 容量排队（仅模型调用）」执行。
"""

import json
import logging
import time
from datetime import datetime, timezone
from typing import AsyncIterator, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from langchain_core.messages import HumanMessage, AIMessage

from app.core.blocking import run_blocking
from app.core.exceptions import AgentExecutionException, AppException, SessionNotFoundException
from app.api.deps import CurrentPlayer, get_current_player, require_session_owner
from app.models.chat import (
    ChatRequest,
    ChatResponse,
    ChatHistoryResponse,
    ChatHistoryItem,
    TicketOffer,
    HumanOffer,
)
from agent.graph import run_agent, stream_agent_events
from agent.checkpointer import get_checkpointer
from app.services.admission import AdmissionTicket
from app.services.idempotency import load_result, save_result, valid_request_id
from app.services.pending_store import add_pending, get_pending
from app.services.execution_trace import public_execution_trace
from app.services.human_chat import (
    append_user_message,
    append_agent_message,
    enter_human_mode,
    close_human_session,
    is_human_mode,
)
from app.services.rate_limit import enforce_chat_rate
from app.services.session_lock import (
    acquire_session_lock,
    clear_cancel,
    request_cancel,
    session_guard,
    try_session_lock,
)
from app.services.turn_runner import StreamTurn, execute_with_deadline, sse, to_app_exception

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/chat", tags=["对话"])

_END_WAIT_SECONDS = 8  # 结束对话时等待进行中的问答退出的上限
_SSE_HEADERS = {"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no"}


def _normalize_response(
    final_response: str,
    ticket_offer: dict | None = None,
    human_offer: dict | None = None,
) -> str:
    """空回复时返回委婉兜底文案，避免前端显示「（无回复内容）」"""
    text = (final_response or "").strip()
    if text:
        return text
    if human_offer:
        return (
            "很抱歉没能为您解决问题。您可通过下方按钮确认是否转接人工客服，"
            "也可以继续向我求助。"
        )
    if ticket_offer:
        return (
            "很抱歉没能为您解决问题。您可通过下方按钮确认是否创建工单，"
            "也可以继续向我求助。"
        )
    return "很抱歉没能为您解决问题，您可以继续向我求助。"


async def _human_mode_active(session_id: str) -> bool:
    return bool(await get_pending(session_id) or await is_human_mode(session_id))


async def _send_human_message(session_id: str, message: str, start: float) -> ChatResponse:
    """人工接待中：消息直接写入 checkpoint，不调用模型，不占全站问答名额。"""
    try:
        await append_user_message(session_id, message)
        pending = await get_pending(session_id)
        if pending:
            pending["last_user_at"] = datetime.now(timezone.utc).isoformat()
            await add_pending(session_id, pending)
    except Exception:
        logger.exception("human message append failed for %s", session_id)
        raise AgentExecutionException("人工接待消息发送失败，请稍后重试")
    return ChatResponse(
        session_id=session_id,
        status="human_chat",
        response="消息已发送，等待客服回复...",
        metadata={"execution_time_ms": int((time.perf_counter() - start) * 1000), "human_mode": True},
    )


def _build_chat_response(session_id: str, result: dict, start: float) -> ChatResponse:
    raw_ticket = result.get("ticket_offer")
    raw_human = result.get("human_offer")
    final_response = _normalize_response(
        result.get("final_response") or "",
        ticket_offer=raw_ticket if isinstance(raw_ticket, dict) else None,
        human_offer=raw_human if isinstance(raw_human, dict) else None,
    )
    ticket_offer_obj = None
    if raw_ticket and isinstance(raw_ticket, dict):
        ticket_offer_obj = TicketOffer(
            summary=raw_ticket.get("summary", ""),
            issue_type=raw_ticket.get("issue_type", "other"),
        )
    human_offer_obj = None
    if raw_human and isinstance(raw_human, dict):
        human_offer_obj = HumanOffer(summary=raw_human.get("summary", ""))
    return ChatResponse(
        session_id=session_id,
        response=final_response,
        sources=result.get("metadata", {}).get("sources"),
        ticket_offer=ticket_offer_obj,
        human_offer=human_offer_obj,
        metadata={
            "execution_time_ms": int((time.perf_counter() - start) * 1000),
            "execution_trace": public_execution_trace(result),
        },
    )


@router.post("/send", response_model=ChatResponse)
async def send_message(
    request: ChatRequest,
    http_request: Request,
    player: CurrentPlayer = Depends(get_current_player),
) -> ChatResponse:
    """
    发送对话消息（非流式）

    人工接待中：消息直接写入 checkpoint，不跑 Agent。
    正常模式：排队取得全站名额后跑完整 LangGraph，可能返回 ticket_offer / human_offer。
    """
    require_session_owner(request.session_id, player)
    await enforce_chat_rate(http_request)
    request_id = valid_request_id(request.client_request_id)
    scope = f"chat-send:{request.session_id}"
    start = time.perf_counter()

    async with session_guard(request.session_id) as guard:
        cached = await load_result(scope, request_id)
        if cached:
            return ChatResponse(**cached)

        if await _human_mode_active(request.session_id):
            response = await _send_human_message(request.session_id, request.message, start)
        else:
            ticket = AdmissionTicket()
            try:
                await ticket.wait(cancelled=lambda: guard.cancel_requested)
                result = await execute_with_deadline(
                    run_agent(session_id=request.session_id, user_id=player.user_id, user_query=request.message),
                    guard,
                )
            except AppException:
                raise
            except Exception as exc:
                logger.warning("agent turn failed for %s: %s", request.session_id, type(exc).__name__)
                raise to_app_exception(exc)
            finally:
                await ticket.release()
            response = _build_chat_response(request.session_id, result, start)

        await save_result(scope, request_id, response.model_dump())
        return response


@router.get("/history/{session_id}", response_model=ChatHistoryResponse)
async def get_chat_history(
    session_id: str,
    player: CurrentPlayer = Depends(get_current_player),
) -> ChatHistoryResponse:
    """从 LangGraph checkpointer 读取对话历史（只读，不加会话锁）"""
    require_session_owner(session_id, player)
    checkpointer = await get_checkpointer()
    config = {
        "configurable": {
            "thread_id": session_id,
            "checkpoint_ns": "game_support_agent",
        }
    }

    checkpoint_tuple = await checkpointer.aget_tuple(config)
    if checkpoint_tuple is None:
        config_no_ns = {"configurable": {"thread_id": session_id}}
        checkpoint_tuple = await checkpointer.aget_tuple(config_no_ns)

    if not checkpoint_tuple:
        raise SessionNotFoundException(session_id)

    channel_values = checkpoint_tuple.checkpoint.get("channel_values", {})
    raw_messages = channel_values.get("messages", [])
    checkpoint_ts = checkpoint_tuple.checkpoint.get("ts") or datetime.now().isoformat()

    items: list[ChatHistoryItem] = []
    for msg in raw_messages:
        if isinstance(msg, HumanMessage):
            role = "user"
        elif isinstance(msg, AIMessage):
            role = "assistant"
        else:
            continue

        is_human = isinstance(msg, AIMessage) and bool(
            (msg.additional_kwargs or {}).get("human_source")
        )
        items.append(
            ChatHistoryItem(
                role=role,
                content=msg.content if isinstance(msg.content, str) else str(msg.content),
                timestamp=checkpoint_ts,
                is_human=is_human,
            )
        )

    return ChatHistoryResponse(
        session_id=session_id,
        messages=items,
        total=len(items),
    )


_IDLE_WARNING = "【系统提示】您好，请问还在吗？如果5分钟未回复，我们将结束本次会话。"
_IDLE_CLOSED = "【系统提示】由于您长时间未回复，本次人工服务已自动结束。如需帮助请重新提问。"


async def _idle_check(session_id: str, reply: str, ts_str: Optional[str]) -> tuple[str, bool]:
    """人工接待空闲提醒/自动结束；抢不到会话锁时跳过本次检查，避免与正在写入的请求交错。"""
    if not ts_str:
        return reply, True
    try:
        elapsed = (datetime.now(timezone.utc) - datetime.fromisoformat(ts_str)).total_seconds()
    except (TypeError, ValueError):
        return reply, True
    is_warning = "如果5分钟未回复" in reply
    needs_close = is_warning and elapsed > 240
    needs_warning = not is_warning and elapsed > 60 and "由于您长时间未回复" not in reply
    if not (needs_close or needs_warning):
        return reply, True
    guard = await try_session_lock(session_id)
    if guard is None:
        return reply, True
    try:
        if needs_close:
            await append_agent_message(session_id, _IDLE_CLOSED)
            await close_human_session(session_id)
            return _IDLE_CLOSED, False
        await append_agent_message(session_id, _IDLE_WARNING)
        return _IDLE_WARNING, True
    except Exception:
        logger.warning("idle check write failed for %s", session_id)
        return reply, True
    finally:
        await guard.release()


@router.get("/reply/{session_id}")
async def get_human_reply(
    session_id: str,
    player: CurrentPlayer = Depends(get_current_player),
):
    """
    轮询人工回复（供前端轮询）

    返回最后一条带 human_source 标记的客服消息。
    """
    require_session_owner(session_id, player)
    checkpointer = await get_checkpointer()
    config = {
        "configurable": {
            "thread_id": session_id,
            "checkpoint_ns": "game_support_agent",
        }
    }

    checkpoint_tuple = await checkpointer.aget_tuple(config)
    if checkpoint_tuple is None:
        config_no_ns = {"configurable": {"thread_id": session_id}}
        checkpoint_tuple = await checkpointer.aget_tuple(config_no_ns)

    if checkpoint_tuple is None:
        return {"status": "pending"}

    channel_values = checkpoint_tuple.checkpoint.get("channel_values", {})
    messages = channel_values.get("messages", [])

    for msg in reversed(messages):
        if isinstance(msg, AIMessage):
            kwargs = msg.additional_kwargs or {}
            if kwargs.get("human_source"):
                reply = msg.content if isinstance(msg.content, str) else str(msg.content)
                human_active = await get_pending(session_id) is not None
                if human_active:
                    reply, human_active = await _idle_check(session_id, reply, kwargs.get("timestamp"))
                return {
                    "status": "completed",
                    "reply": reply,
                    "human_active": human_active,
                }
            break

    return {"status": "pending", "human_active": await get_pending(session_id) is not None}


def _sse_response(body: AsyncIterator[str]) -> StreamingResponse:
    return StreamingResponse(body, media_type="text/event-stream", headers=_SSE_HEADERS)


async def _single_event(payload: dict) -> AsyncIterator[str]:
    yield sse(payload)


@router.post("/stream")
async def stream_chat(
    request: ChatRequest,
    http_request: Request,
    player: CurrentPlayer = Depends(get_current_player),
):
    """流式对话（SSE）。

    频率超限（429）、会话正忙（409）、队列已满（503）在建立流之前以 HTTP 状态返回；
    已入队的请求在流内收到 queue 事件和心跳，入场后才推送执行步骤。
    """
    require_session_owner(request.session_id, player)
    await enforce_chat_rate(http_request)
    request_id = valid_request_id(request.client_request_id)
    scope = f"chat-stream:{request.session_id}"
    session_id = request.session_id

    guard = await acquire_session_lock(session_id)
    ticket: Optional[AdmissionTicket] = None
    try:
        cached = await load_result(scope, request_id)
        human = False
        if cached is None:
            human = await _human_mode_active(session_id)
            if not human:
                ticket = AdmissionTicket()
                await ticket.attempt()
    except BaseException:
        if ticket is not None:
            await ticket.release()
        await guard.release()
        raise

    if cached is not None:
        await guard.release()
        return _sse_response(_single_event(cached))

    async def direct() -> dict:
        result = await _send_human_message(session_id, request.message, time.perf_counter())
        return {"type": "done", **result.model_dump()}

    turn = StreamTurn(
        guard,
        None if human else ticket,
        agent_events=lambda: stream_agent_events(session_id, player.user_id, request.message),
        direct=direct,
        on_done=lambda payload: save_result(scope, request_id, payload),
    )
    turn.arm_watchdog()
    return _sse_response(turn.events())


class TicketConfirmRequest(BaseModel):
    session_id: str
    confirmed: bool
    client_request_id: Optional[str] = Field(default=None, max_length=64)


class TicketConfirmResponse(BaseModel):
    status: str
    ticket_id: str | None = None
    estimated_response: str | None = None
    issue_type: str | None = None
    summary: str | None = None


async def _load_channel_values(session_id: str) -> dict:
    from app.core.checkpoint_helper import graph_config

    checkpointer = await get_checkpointer()
    checkpoint_tuple = await checkpointer.aget_tuple(graph_config(session_id))
    if checkpoint_tuple is None:
        checkpoint_tuple = await checkpointer.aget_tuple(
            {"configurable": {"thread_id": session_id}}
        )
    if checkpoint_tuple is None:
        raise HTTPException(status_code=404, detail="会话不存在")
    return checkpoint_tuple.checkpoint.get("channel_values", {})


async def _confirm_ticket(request: TicketConfirmRequest, player: CurrentPlayer) -> TicketConfirmResponse:
    from app.core.checkpoint_helper import append_agent_reply, append_session_messages

    channel_values = await _load_channel_values(request.session_id)
    ticket_offer = channel_values.get("ticket_offer")
    if not ticket_offer:
        raise HTTPException(status_code=400, detail="无待确认的工单请求")

    if not request.confirmed:
        await append_agent_reply(
            request.session_id,
            "好的，已取消工单创建。如需帮助随时告知。",
            ticket_offer=None,
        )
        return TicketConfirmResponse(status="cancelled")

    # 决策：建单前先消费待确认状态，即使后续写回复失败，重试也不会再建第二张工单；建单失败时恢复。
    await append_session_messages(request.session_id, [], extra_state={"ticket_offer": None})

    from app.services.ticket_service import create_ticket_core
    try:
        result = await run_blocking(
            create_ticket_core,
            user_id=player.user_id,
            issue_type=ticket_offer.get("issue_type", "other"),
            description=ticket_offer.get("summary", ""),
        )
    except Exception:
        await append_session_messages(request.session_id, [], extra_state={"ticket_offer": ticket_offer})
        raise
    created = result.get("status") == "submitted" and bool(result.get("ticket_id"))
    ticket_id = result.get("ticket_id") if created else None
    estimated = result.get("estimated_response") if created else None

    tool_calls = channel_values.get("tool_calls", [])
    if ticket_id and tool_calls:
        try:
            from app.repositories.database import update_ticket
            from agent.tools import simplify_tool_context
            await run_blocking(
                update_ticket,
                ticket_id,
                tool_context=json.dumps(simplify_tool_context(tool_calls), ensure_ascii=False),
            )
        except Exception:
            logger.warning("failed to attach tool context to ticket %s", ticket_id)

    if ticket_id:
        await append_agent_reply(
            request.session_id,
            f"✅ 工单已创建！工单号：{ticket_id}，预计处理时间：{estimated}",
            ticket_id=ticket_id,
            ticket_offer=None,
        )
    else:
        await append_agent_reply(request.session_id, "工单创建失败，请稍后重试。", ticket_offer=ticket_offer)

    return TicketConfirmResponse(
        status="created" if created else "failed",
        ticket_id=ticket_id,
        estimated_response=estimated,
        issue_type=ticket_offer.get("issue_type"),
        summary=ticket_offer.get("summary"),
    )


@router.post("/ticket-confirm", response_model=TicketConfirmResponse)
async def confirm_ticket_offer(
    request: TicketConfirmRequest,
    player: CurrentPlayer = Depends(get_current_player),
) -> TicketConfirmResponse:
    """处理工单创建确认（玩家点「是/否」）；同一请求 ID 重试返回首次结果，不会重复建单。"""
    require_session_owner(request.session_id, player)
    request_id = valid_request_id(request.client_request_id)
    scope = f"ticket-confirm:{request.session_id}"
    async with session_guard(request.session_id):
        cached = await load_result(scope, request_id)
        if cached:
            return TicketConfirmResponse(**cached)
        response = await _confirm_ticket(request, player)
        if response.status != "failed":
            await save_result(scope, request_id, response.model_dump())
        return response


class HumanConfirmRequest(BaseModel):
    session_id: str
    confirmed: bool
    client_request_id: Optional[str] = Field(default=None, max_length=64)


class HumanConfirmResponse(BaseModel):
    status: str  # entered / cancelled
    summary: str | None = None


@router.post("/human-confirm", response_model=HumanConfirmResponse)
async def confirm_human_offer(
    request: HumanConfirmRequest,
    player: CurrentPlayer = Depends(get_current_player),
) -> HumanConfirmResponse:
    """
    处理转人工确认（玩家点「是/否」）

    confirmed=True  → 进入人工接待，登记 pending，客服可见线程对话
    confirmed=False → 取消，无事发生
    """
    require_session_owner(request.session_id, player)
    from app.core.checkpoint_helper import append_agent_reply

    request_id = valid_request_id(request.client_request_id)
    scope = f"human-confirm:{request.session_id}"
    async with session_guard(request.session_id):
        cached = await load_result(scope, request_id)
        if cached:
            return HumanConfirmResponse(**cached)

        channel_values = await _load_channel_values(request.session_id)
        human_offer = channel_values.get("human_offer")
        if not human_offer:
            raise HTTPException(status_code=400, detail="无待确认的转人工请求")

        if not request.confirmed:
            await append_agent_reply(
                request.session_id,
                "好的，已取消转人工。如需帮助随时告知。",
                human_offer=None,
            )
            response = HumanConfirmResponse(status="cancelled")
        else:
            await enter_human_mode(request.session_id)
            response = HumanConfirmResponse(status="entered", summary=human_offer.get("summary"))
        await save_result(scope, request_id, response.model_dump())
        return response


class EndConversationRequest(BaseModel):
    session_id: str


@router.post("/end")
async def end_conversation(body: EndConversationRequest, player: CurrentPlayer = Depends(get_current_player)):
    """结束对话：通知本会话进行中的问答退出，取得会话锁后再关闭人工接待。"""
    require_session_owner(body.session_id, player)
    await request_cancel(body.session_id)
    try:
        guard = await acquire_session_lock(body.session_id, wait_seconds=_END_WAIT_SECONDS)
    finally:
        await clear_cancel(body.session_id)
    try:
        if await _human_mode_active(body.session_id):
            await close_human_session(body.session_id)
    finally:
        await guard.release()
    return {"status": "ended", "session_id": body.session_id}
