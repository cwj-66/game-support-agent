"""
对话API
处理用户对话请求，调用Agent执行
"""

import time
import json
import traceback
from datetime import datetime
from typing import AsyncGenerator

from fastapi import APIRouter, Depends, BackgroundTasks
from fastapi.responses import StreamingResponse
from langchain_core.messages import HumanMessage, AIMessage

from app.core.config import get_settings, Settings
from app.core.exceptions import AgentExecutionException, SessionNotFoundException
from app.models.chat import (
    ChatRequest,
    ChatResponse,
    ChatHistoryResponse,
    ChatHistoryItem,
)
from agent.graph import run_agent, stream_agent
from agent.checkpointer import get_checkpointer
from app.core.pending_store import add_pending

# 兼容不同版本 LangGraph 的 GraphInterrupt
try:
    from langgraph.errors import GraphInterrupt
except ImportError:
    GraphInterrupt = None


router = APIRouter(prefix="/chat", tags=["对话"])


def _get_interrupt_response(interrupt_payload: dict) -> str:
    """根据中断来源生成合适的用户提示，避免对所有中断都说"敏感操作" """
    source = interrupt_payload.get("source", "")
    level = interrupt_payload.get("interrupt_level", "")
    reason = interrupt_payload.get("interrupt_reason", "")

    # 敏感词检测 high 级别 → 保留安全提示
    if source == "detector" and level == "high":
        return "您的消息涉及敏感操作，已转交人工客服处理，请稍候。"

    # LLM 主动升等 → 用升等原因生成友好提示
    if source == "llm_escalate":
        if "知识库" in reason or "无结果" in reason or "找不到" in reason:
            return "抱歉，我暂时没有找到相关信息，已为您转接人工客服协助处理，请稍候。"
        return "正在为您转接人工客服处理，请稍候。"

    # 自动升等（工具失败/账号封禁等）
    if source == "auto_escalate":
        return "正在为您转接人工客服处理，请稍候。"

    # 检测器低置信度
    if source == "detector":
        return "抱歉，我暂时无法确认这个问题的答案，已为您转接人工客服协助处理，请稍候。"

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
            add_pending(request.session_id, interrupt_payload)
            return ChatResponse(
                session_id=request.session_id,
                response=_get_interrupt_response(interrupt_payload),
                requires_review=True,
                review_id=request.session_id,
                metadata={"execution_time_ms": execution_time_ms},
            )

        final_response = result.get("final_response") or ""
        return ChatResponse(
            session_id=request.session_id,
            response=final_response,
            requires_review=False,
            review_id=None,
            sources=result.get("metadata", {}).get("sources"),
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
            add_pending(request.session_id, interrupt_payload)
            return ChatResponse(
                session_id=request.session_id,
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
    checkpointer = get_checkpointer()
    config = {
        "configurable": {
            "thread_id": session_id,
            "checkpoint_ns": "game_support_agent",
        }
    }

    # 兼容 LangGraph 不同版本的 checkpoint 查询
    checkpoint_tuple = checkpointer.get_tuple(config)
    if checkpoint_tuple is None:
        # 尝试不带 checkpoint_ns 查询
        config_no_ns = {"configurable": {"thread_id": session_id}}
        checkpoint_tuple = checkpointer.get_tuple(config_no_ns)

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


# TODO: 未来扩展
# - 添加会话创建API（POST /sessions）
# - 添加会话结束/归档API
# - 添加消息反馈API（点赞/点踩）
