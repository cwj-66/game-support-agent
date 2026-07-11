"""
对话API
处理用户对话请求，调用Agent执行
"""

import time
import json
import traceback
from datetime import datetime, timezone
from typing import AsyncGenerator

from fastapi import APIRouter, Depends, BackgroundTasks, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from langchain_core.messages import HumanMessage, AIMessage

from app.core.config import get_settings, Settings
from app.core.exceptions import AgentExecutionException, SessionNotFoundException
from app.api.deps import CurrentPlayer, get_current_player, require_session_owner
from app.models.chat import (
    ChatRequest,
    ChatResponse,
    ChatHistoryResponse,
    ChatHistoryItem,
    TicketOffer,
    HumanOffer,
)
from agent.graph import run_agent, stream_agent
from agent.checkpointer import get_checkpointer
from app.services.pending_store import get_pending, remove_pending
from app.services.human_chat import (
    append_user_message,
    append_agent_message,
    enter_human_mode,
    close_human_session,
    is_human_mode,
)


router = APIRouter(prefix="/chat", tags=["对话"])


def _node_to_progress(node_name: str) -> str:
    """将节点名称映射为用户友好的进度描述"""
    mapping = {
        "reasoning": "正在分析您的问题...",
        "tool_exec": "正在查询知识库...",
        "generate": "正在生成回复...",
        "finish": "处理完成",
    }
    return mapping.get(node_name, "")


@router.post("/send", response_model=ChatResponse)
async def send_message(
    request: ChatRequest,
    background_tasks: BackgroundTasks,
    player: CurrentPlayer = Depends(get_current_player),
    settings: Settings = Depends(get_settings),
) -> ChatResponse:
    """
    发送对话消息

    人工接待中：消息直接写入 checkpoint，不跑 Agent。
    正常模式：跑完整 LangGraph，可能返回 ticket_offer / human_offer 供前端确认。
    """
    require_session_owner(request.session_id, player)
    user_id = player.user_id
    start_time = time.perf_counter()

    # 人工接待中：pending 或 human_mode 存在即走人工通道
    if await get_pending(request.session_id) or await is_human_mode(request.session_id):
        try:
            await append_user_message(request.session_id, request.message)
            execution_time_ms = int((time.perf_counter() - start_time) * 1000)
            return ChatResponse(
                session_id=request.session_id,
                status="human_chat",
                response="消息已发送，等待客服回复...",
                metadata={"execution_time_ms": execution_time_ms, "human_mode": True},
            )
        except Exception:
            traceback.print_exc()
            raise AgentExecutionException("人工接待消息发送失败，请稍后重试")

    try:
        result = await run_agent(
            session_id=request.session_id,
            user_id=user_id,
            user_query=request.message,
        )

        execution_time_ms = int((time.perf_counter() - start_time) * 1000)
        final_response = result.get("final_response") or ""

        raw_ticket = result.get("ticket_offer")
        ticket_offer_obj = None
        if raw_ticket and isinstance(raw_ticket, dict):
            ticket_offer_obj = TicketOffer(
                summary=raw_ticket.get("summary", ""),
                issue_type=raw_ticket.get("issue_type", "other"),
            )

        raw_human = result.get("human_offer")
        human_offer_obj = None
        if raw_human and isinstance(raw_human, dict):
            human_offer_obj = HumanOffer(
                summary=raw_human.get("summary", ""),
            )

        return ChatResponse(
            session_id=request.session_id,
            response=final_response,
            sources=result.get("metadata", {}).get("sources"),
            ticket_offer=ticket_offer_obj,
            human_offer=human_offer_obj,
            metadata={"execution_time_ms": execution_time_ms},
        )

    except Exception as e:
        traceback.print_exc()
        raise AgentExecutionException(str(e))


@router.get("/history/{session_id}", response_model=ChatHistoryResponse)
async def get_chat_history(
    session_id: str,
    player: CurrentPlayer = Depends(get_current_player),
    settings: Settings = Depends(get_settings),
) -> ChatHistoryResponse:
    """从 LangGraph checkpointer 读取对话历史"""
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

        items.append(
            ChatHistoryItem(
                role=role,
                content=msg.content if isinstance(msg.content, str) else str(msg.content),
                timestamp=checkpoint_ts,
            )
        )

    return ChatHistoryResponse(
        session_id=session_id,
        messages=items,
        total=len(items),
    )


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

                # 超时检测：1分钟提醒，5分钟自动结束
                if human_active:
                    ts_str = kwargs.get("timestamp")
                    if ts_str:
                        try:
                            last_time = datetime.fromisoformat(ts_str)
                            elapsed = (datetime.now(timezone.utc) - last_time).total_seconds()
                            is_warning = "如果5分钟未回复" in reply

                            if is_warning and elapsed > 240:
                                await append_agent_message(
                                    session_id,
                                    "【系统提示】由于您长时间未回复，本次人工服务已自动结束。如需帮助请重新提问。",
                                )
                                await close_human_session(session_id)
                                human_active = False
                                reply = "【系统提示】由于您长时间未回复，本次人工服务已自动结束。如需帮助请重新提问。"
                            elif not is_warning and elapsed > 60 and "由于您长时间未回复" not in reply:
                                await append_agent_message(
                                    session_id,
                                    "【系统提示】您好，请问还在吗？如果5分钟未回复，我们将结束本次会话。",
                                )
                                reply = "【系统提示】您好，请问还在吗？如果5分钟未回复，我们将结束本次会话。"
                        except Exception:
                            pass

                return {
                    "status": "completed",
                    "reply": reply,
                    "human_active": human_active,
                }
            break

    return {"status": "pending", "human_active": await get_pending(session_id) is not None}


@router.post("/stream")
async def stream_chat(
    request: ChatRequest,
    player: CurrentPlayer = Depends(get_current_player),
    settings: Settings = Depends(get_settings),
):
    """流式对话（SSE）"""
    require_session_owner(request.session_id, player)
    user_id = player.user_id

    async def event_generator() -> AsyncGenerator[str, None]:
        final_response = ""
        try:
            async for chunk in stream_agent(
                session_id=request.session_id,
                user_id=user_id,
                user_query=request.message,
            ):
                if not chunk:
                    continue

                node_name = next(iter(chunk))
                node_updates = chunk[node_name]

                if isinstance(node_updates, dict) and node_updates.get("final_response"):
                    final_response = node_updates["final_response"]

                progress = _node_to_progress(node_name)
                if progress:
                    data = json.dumps(
                        {"type": "progress", "node": node_name, "message": progress},
                        ensure_ascii=False,
                    )
                    yield f"data: {data}\n\n"

            data = json.dumps(
                {"type": "done", "response": final_response},
                ensure_ascii=False,
            )
            yield f"data: {data}\n\n"

        except Exception as e:
            data = json.dumps(
                {"type": "error", "message": str(e)},
                ensure_ascii=False,
            )
            yield f"data: {data}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


class TicketConfirmRequest(BaseModel):
    session_id: str
    confirmed: bool


class TicketConfirmResponse(BaseModel):
    status: str
    ticket_id: str | None = None
    estimated_response: str | None = None
    issue_type: str | None = None
    summary: str | None = None


@router.post("/ticket-confirm", response_model=TicketConfirmResponse)
async def confirm_ticket_offer(
    request: TicketConfirmRequest,
    player: CurrentPlayer = Depends(get_current_player),
) -> TicketConfirmResponse:
    """处理工单创建确认（玩家点「是/否」）"""
    require_session_owner(request.session_id, player)
    from app.core.checkpoint_helper import append_agent_reply, graph_config

    checkpointer = await get_checkpointer()
    config = graph_config(request.session_id)
    checkpoint_tuple = await checkpointer.aget_tuple(config)

    if checkpoint_tuple is None:
        checkpoint_tuple = await checkpointer.aget_tuple(
            {"configurable": {"thread_id": request.session_id}}
        )

    if checkpoint_tuple is None:
        raise HTTPException(status_code=404, detail="会话不存在")

    channel_values = checkpoint_tuple.checkpoint.get("channel_values", {})
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

    user_id = player.user_id
    tool_calls = channel_values.get("tool_calls", [])

    from app.services.ticket_service import create_ticket_core
    result = create_ticket_core(
        user_id=user_id,
        issue_type=ticket_offer.get("issue_type", "other"),
        description=ticket_offer.get("summary", ""),
    )

    ticket_id = result.get("ticket_id")
    estimated = result.get("estimated_response", "3-5 个工作日")

    if ticket_id and tool_calls:
        try:
            from app.repositories.database import update_ticket
            from agent.tools import simplify_tool_context
            update_ticket(
                ticket_id,
                tool_context=json.dumps(simplify_tool_context(tool_calls), ensure_ascii=False),
            )
        except Exception:
            pass

    reply_text = (
        f"✅ 工单已创建！工单号：{ticket_id}，预计处理时间：{estimated}"
        if ticket_id
        else "工单创建失败，请稍后重试。"
    )
    await append_agent_reply(
        request.session_id,
        reply_text,
        ticket_id=ticket_id,
        ticket_offer=None,
    )

    return TicketConfirmResponse(
        status="created",
        ticket_id=ticket_id,
        estimated_response=estimated,
        issue_type=ticket_offer.get("issue_type"),
        summary=ticket_offer.get("summary"),
    )


class HumanConfirmRequest(BaseModel):
    session_id: str
    confirmed: bool


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
    from app.core.checkpoint_helper import append_agent_reply, graph_config

    checkpointer = await get_checkpointer()
    config = graph_config(request.session_id)
    checkpoint_tuple = await checkpointer.aget_tuple(config)

    if checkpoint_tuple is None:
        checkpoint_tuple = await checkpointer.aget_tuple(
            {"configurable": {"thread_id": request.session_id}}
        )

    if checkpoint_tuple is None:
        raise HTTPException(status_code=404, detail="会话不存在")

    channel_values = checkpoint_tuple.checkpoint.get("channel_values", {})
    human_offer = channel_values.get("human_offer")
    if not human_offer:
        raise HTTPException(status_code=400, detail="无待确认的转人工请求")

    if not request.confirmed:
        await append_agent_reply(
            request.session_id,
            "好的，已取消转人工。如需帮助随时告知。",
            human_offer=None,
        )
        return HumanConfirmResponse(status="cancelled")

    await enter_human_mode(request.session_id)

    return HumanConfirmResponse(
        status="entered",
        summary=human_offer.get("summary"),
    )
