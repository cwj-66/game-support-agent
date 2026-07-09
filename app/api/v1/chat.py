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
from app.models.chat import (
    ChatRequest,
    ChatResponse,
    ChatHistoryResponse,
    ChatHistoryItem,
    TicketOffer,
)
from agent.graph import run_agent, stream_agent, get_graph
from agent.checkpointer import get_checkpointer
from app.core.pending_store import add_pending, get_pending, remove_pending
from app.core.human_invoke import invoke_human_resume

# 兼容不同版本 LangGraph 的 GraphInterrupt
try:
    from langgraph.errors import GraphInterrupt
except ImportError:
    GraphInterrupt = None


router = APIRouter(prefix="/chat", tags=["对话"])


def _get_interrupt_response(interrupt_payload: dict) -> str:
    """根据中断来源生成合适的用户提示"""
    source = interrupt_payload.get("source", "")
    reason = interrupt_payload.get("interrupt_reason", "")

    # detector 触发 → 统一提示
    if source == "detector":
        return "您的问题正在由专员核实，请稍候。"

    # LLM 主动升等
    if source == "llm_escalate":
        if "知识库" in reason or "无结果" in reason or "找不到" in reason:
            return "抱歉，我暂时没有找到相关信息，已为您转接人工客服协助处理，请稍候。"
        return "正在为您转接人工客服处理，请稍候。"

    return "正在为您转接人工客服，请稍候。"


def _node_to_progress(node_name: str) -> str:
    """将节点名称映射为用户友好的进度描述"""
    mapping = {
        "reasoning": "正在分析您的问题...",
        "tool_exec": "正在查询知识库...",
        "detector": "正在进行安全检测...",
        "human": "已转交人工审核，请稍候...",
        "generate": "正在生成回复...",
        "finish": "处理完成",
    }
    return mapping.get(node_name, "")


# ──────────────────────────────────────────────
# 优化 1 & 4：发送消息 + 人工审核中断检测 + 耗时统计 + 细化错误处理
# ──────────────────────────────────────────────
@router.post("/send", response_model=ChatResponse)
async def send_message(
    request: ChatRequest,
    background_tasks: BackgroundTasks,
    settings: Settings = Depends(get_settings),
) -> ChatResponse:
    """
    发送对话消息

    流程：
    1. 接收用户消息
    2. 执行 LangGraph Agent
    3. 检查是否触发 Human-in-the-loop 中断
    4. 返回回复或审核等待标记，附带真实耗时
    """
    start_time = time.perf_counter()

    # --- 人工接待中：pending 存在即走人工通道，不再跑 Agent ---
    # 决策注释：interrupt 挂起时 graph_state.next 可能为空，不能依赖 next==("human",)
    if await get_pending(request.session_id):
        try:
            await invoke_human_resume(
                request.session_id,
                {
                    "source": "user",
                    "message": request.message,
                    "action": "continue",
                },
            )
            execution_time_ms = int((time.perf_counter() - start_time) * 1000)
            return ChatResponse(
                session_id=request.session_id,
                status="under_review",
                response="消息已发送，等待客服回复...",
                requires_review=True,
                review_id=request.session_id,
                metadata={"execution_time_ms": execution_time_ms, "human_mode": True},
            )
        except Exception:
            traceback.print_exc()
            raise AgentExecutionException("人工接待消息发送失败，请稍后重试")

    try:
        result = await run_agent(
            session_id=request.session_id,
            user_id=request.user_id,
            user_query=request.message,
        )

        execution_time_ms = int((time.perf_counter() - start_time) * 1000)

        # 检查是否触发了 interrupt（兼容不同 LangGraph 版本的中断返回方式）
        interrupt_payload = result.get("__interrupt__")
        if result.get("has_interrupt") or interrupt_payload:
            if not isinstance(interrupt_payload, dict):
                interrupt_payload = {}
            await add_pending(request.session_id, interrupt_payload)
            source = interrupt_payload.get("source", "")
            return ChatResponse(
                session_id=request.session_id,
                status="under_review",
                response=_get_interrupt_response(interrupt_payload),
                requires_review=True,
                review_id=request.session_id,
                metadata={
                    "execution_time_ms": execution_time_ms,
                    "interrupt_source": source,
                },
            )

        final_response = result.get("final_response") or ""

        # 检查是否有工单确认请求
        raw_offer = result.get("ticket_offer")
        ticket_offer_obj = None
        if raw_offer and isinstance(raw_offer, dict):
            ticket_offer_obj = TicketOffer(
                summary=raw_offer.get("summary", ""),
                issue_type=raw_offer.get("issue_type", "other"),
            )

        return ChatResponse(
            session_id=request.session_id,
            response=final_response,
            requires_review=False,
            review_id=None,
            sources=result.get("metadata", {}).get("sources"),
            ticket_offer=ticket_offer_obj,
            metadata={
                "execution_time_ms": execution_time_ms,
            },
        )

    except Exception as e:
        exc_name = type(e).__name__
        # GraphInterrupt：图被 interrupt() 真实挂起
        # 兼容不同 LangGraph 版本的异常类型名
        if "GraphInterrupt" in exc_name or "Interrupt" in exc_name:
            execution_time_ms = int((time.perf_counter() - start_time) * 1000)
            interrupt_payload = e.args[0] if e.args else {}
            await add_pending(request.session_id, interrupt_payload)
            return ChatResponse(
                session_id=request.session_id,
                status="under_review",
                response=_get_interrupt_response(interrupt_payload),
                requires_review=True,
                review_id=request.session_id,
                metadata={"execution_time_ms": execution_time_ms},
            )
        traceback.print_exc()
        raise AgentExecutionException(str(e))


# ──────────────────────────────────────────────
# 优化 2：从 Checkpointer 读取真实历史记录
# ──────────────────────────────────────────────
@router.get("/history/{session_id}", response_model=ChatHistoryResponse)
async def get_chat_history(
    session_id: str,
    settings: Settings = Depends(get_settings),
) -> ChatHistoryResponse:
    """
    获取对话历史

    从 LangGraph checkpointer 中读取指定会话的消息列表
    """
    checkpointer = await get_checkpointer()
    config = {
        "configurable": {
            "thread_id": session_id,
            "checkpoint_ns": "game_support_agent",
        }
    }

    # 兼容 LangGraph 不同版本的 checkpoint 查询
    checkpoint_tuple = await checkpointer.aget_tuple(config)
    if checkpoint_tuple is None:
        # 尝试不带 checkpoint_ns 查询
        config_no_ns = {"configurable": {"thread_id": session_id}}
        checkpoint_tuple = await checkpointer.aget_tuple(config_no_ns)

    if not checkpoint_tuple:
        raise SessionNotFoundException(session_id)

    channel_values = checkpoint_tuple.checkpoint.get("channel_values", {})
    raw_messages = channel_values.get("messages", [])

    # 使用 checkpoint 时间戳作为消息时间的参考值
    checkpoint_ts = checkpoint_tuple.checkpoint.get("ts") or datetime.now().isoformat()

    items: list[ChatHistoryItem] = []
    for msg in raw_messages:
        if isinstance(msg, HumanMessage):
            role = "user"
        elif isinstance(msg, AIMessage):
            role = "assistant"
        else:
            # ToolMessage / SystemMessage 不在对话历史里展示
            continue

        items.append(
            ChatHistoryItem(
                role=role,
                content=msg.content if isinstance(msg.content, str) else str(msg.content),
                timestamp=checkpoint_ts,
                requires_review=False,
                reviewed=False,
            )
        )

    return ChatHistoryResponse(
        session_id=session_id,
        messages=items,
        total=len(items),
    )


@router.get("/reply/{session_id}")
async def get_human_reply(session_id: str):
    """
    轮询人工回复状态（供前端轮询）

    当 human_node interrupt 被人工审核恢复后，finish_node 会写入带 human_source=True
    标记的 AIMessage。前端轮询此端点即可感知人工回复已就绪。

    返回：
    - {status: "completed", reply: "..."} — 人工已回复
    - {status: "pending"} — 尚未回复
    """
    checkpointer = await get_checkpointer()
    config = {
        "configurable": {
            "thread_id": session_id,
            "checkpoint_ns": "game_support_agent",
        }
    }

    # 兼容 LangGraph 不同版本的 checkpoint 查询
    checkpoint_tuple = await checkpointer.aget_tuple(config)
    if checkpoint_tuple is None:
        config_no_ns = {"configurable": {"thread_id": session_id}}
        checkpoint_tuple = await checkpointer.aget_tuple(config_no_ns)

    if checkpoint_tuple is None:
        return {"status": "pending"}

    channel_values = checkpoint_tuple.checkpoint.get("channel_values", {})
    messages = channel_values.get("messages", [])

    # 找最后一条带 human_source 标记的 AIMessage
    for msg in reversed(messages):
        if isinstance(msg, AIMessage):
            kwargs = msg.additional_kwargs or {}
            if kwargs.get("human_source"):
                reply = msg.content if isinstance(msg.content, str) else str(msg.content)
                # human_active：会话是否仍在人工接待中（pending 未移除）
                human_active = await get_pending(session_id) is not None

                # --- 超时检测逻辑（1分钟提醒，5分钟结束） ---
                if human_active:
                    ts_str = kwargs.get("timestamp")
                    if ts_str:
                        try:
                            last_time = datetime.fromisoformat(ts_str)
                            elapsed = (datetime.now(timezone.utc) - last_time).total_seconds()
                            is_warning = "如果5分钟未回复" in reply

                            if is_warning and elapsed > 240:  # 提醒后又过了4分钟（总计5分钟）
                                resume_payload = {
                                    "source": "agent",
                                    "message": "【系统提示】由于您长时间未回复，本次人工服务已自动结束。如需帮助请重新提问。",
                                    "action": "close",
                                }
                                await invoke_human_resume(session_id, resume_payload)
                                await remove_pending(session_id)
                                human_active = False
                                reply = resume_payload["message"]
                            elif not is_warning and elapsed > 60 and "由于您长时间未回复" not in reply:
                                # 1分钟未回复，发送提醒
                                resume_payload = {
                                    "source": "agent",
                                    "message": "【系统提示】您好，请问还在吗？如果5分钟未回复，我们将结束本次会话。",
                                    "action": "continue"
                                }
                                await invoke_human_resume(session_id, resume_payload)
                                reply = resume_payload["message"]
                        except Exception:
                            pass

                return {
                    "status": "completed",
                    "reply": reply,
                    "human_active": human_active,
                }
            break

    # 兜底：直接检查 human_reply 字段（兼容旧数据）
    human_reply = channel_values.get("human_reply")
    final_response = channel_values.get("final_response") or ""
    if human_reply and final_response:
        human_active = await get_pending(session_id) is not None
        return {
            "status": "completed",
            "reply": final_response,
            "human_active": human_active,
        }

    return {"status": "pending", "human_active": await get_pending(session_id) is not None}


# ──────────────────────────────────────────────
# 优化 3：真实流式输出（SSE）
# ──────────────────────────────────────────────
@router.post("/stream")
async def stream_chat(
    request: ChatRequest,
    settings: Settings = Depends(get_settings),
):
    """
    流式对话（SSE）

    逐节点推送 Agent 执行进度，最终推送完整回复。

    事件格式（JSON）：
    - {"type": "progress", "node": "...", "message": "..."}
    - {"type": "done", "response": "..."}
    - {"type": "error", "message": "..."}
    """

    async def event_generator() -> AsyncGenerator[str, None]:
        final_response = ""
        try:
            async for chunk in stream_agent(
                session_id=request.session_id,
                user_id=request.user_id,
                user_query=request.message,
            ):
                if not chunk:
                    continue

                node_name = next(iter(chunk))
                node_updates = chunk[node_name]

                # 更新当前最新的 final_response
                if isinstance(node_updates, dict) and node_updates.get("final_response"):
                    final_response = node_updates["final_response"]

                # 推送节点进度
                progress = _node_to_progress(node_name)
                if progress:
                    data = json.dumps(
                        {"type": "progress", "node": node_name, "message": progress},
                        ensure_ascii=False,
                    )
                    yield f"data: {data}\n\n"

            # 所有节点执行完毕，推送最终回复
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
    confirmed: bool  # True=点了「是」，False=点了「否」


class TicketConfirmResponse(BaseModel):
    status: str  # created / cancelled
    ticket_id: str | None = None
    estimated_response: str | None = None
    issue_type: str | None = None
    summary: str | None = None


@router.post("/ticket-confirm", response_model=TicketConfirmResponse)
async def confirm_ticket_offer(request: TicketConfirmRequest) -> TicketConfirmResponse:
    """
    处理工单创建确认

    用户点击前端「是」/「否」按钮后调用此接口：
    - confirmed=True  → 创建工单，并将结果写入 checkpoint messages
    - confirmed=False → 写入取消记录到 checkpoint
    """
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

    user_id = channel_values.get("user_id", "")
    tool_calls = channel_values.get("tool_calls", [])

    from app.core.ticket_service import create_ticket_core
    result = create_ticket_core(
        user_id=user_id,
        issue_type=ticket_offer.get("issue_type", "other"),
        description=ticket_offer.get("summary", ""),
    )

    ticket_id = result.get("ticket_id")
    estimated = result.get("estimated_response", "3-5 个工作日")

    if ticket_id and tool_calls:
        try:
            from app.core.database import update_ticket
            from agent.tools import simplify_tool_context
            update_ticket(
                ticket_id,
                tool_context=json.dumps(simplify_tool_context(tool_calls), ensure_ascii=False),
            )
        except Exception:
            pass

    # 写入 checkpoint，让 Agent 会话内记忆包含建单结果
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


# TODO: 未来扩展
# - 添加会话创建API（POST /sessions）
# - 添加会话结束/归档API
# - 添加消息反馈API（点赞/点踩）
