"""
人工接待服务
通过 checkpoint 直接读写消息，不经过 LangGraph interrupt。
"""

from datetime import datetime, timezone
from typing import Any

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage

from app.core.checkpoint_helper import append_session_messages, graph_config


async def get_channel_values(session_id: str) -> dict[str, Any]:
    """读取会话 checkpoint 中的 channel_values"""
    from agent.checkpointer import get_checkpointer

    checkpointer = await get_checkpointer()
    config = graph_config(session_id)
    checkpoint_tuple = await checkpointer.aget_tuple(config)
    if checkpoint_tuple is None:
        checkpoint_tuple = await checkpointer.aget_tuple(
            {"configurable": {"thread_id": session_id}}
        )
    if checkpoint_tuple is None:
        return {}
    return checkpoint_tuple.checkpoint.get("channel_values", {})


async def is_human_mode(session_id: str) -> bool:
    """会话是否处于人工接待中"""
    values = await get_channel_values(session_id)
    return bool(values.get("human_mode"))


async def append_user_message(session_id: str, message: str) -> None:
    """玩家消息写入 checkpoint 短期对话"""
    now_iso = datetime.now(timezone.utc).isoformat()
    await append_session_messages(
        session_id,
        [HumanMessage(content=message, additional_kwargs={"timestamp": now_iso})],
    )


async def append_agent_message(session_id: str, message: str) -> None:
    """客服消息写入 checkpoint 短期对话"""
    now_iso = datetime.now(timezone.utc).isoformat()
    await append_session_messages(
        session_id,
        [AIMessage(
            content=message,
            additional_kwargs={"human_source": True, "timestamp": now_iso},
        )],
    )


async def enter_human_mode(session_id: str) -> dict[str, Any]:
    """
    玩家点「是」后进入人工接待：写 human_mode、登记 pending、清空 human_offer。
    """
    from app.services.pending_store import add_pending

    values = await get_channel_values(session_id)
    human_offer = values.get("human_offer") or {}

    now_iso = datetime.now(timezone.utc).isoformat()
    payload = {
        "session_id": session_id,
        "user_id": values.get("user_id", ""),
        "user_query": values.get("user_query", ""),
        "summary": human_offer.get("summary", ""),
        "waiting_for": "human_chat",
        "timestamp": now_iso,
        "last_user_at": now_iso,
        "last_agent_at": None,
    }
    await add_pending(session_id, payload)

    now_iso = datetime.now(timezone.utc).isoformat()
    await append_session_messages(
        session_id,
        [AIMessage(
            content="已为您转接人工客服，请稍候，客服将尽快回复您。",
            additional_kwargs={"timestamp": now_iso},
        )],
        extra_state={"human_mode": True, "human_offer": None},
    )
    return payload


async def close_human_session(session_id: str) -> None:
    """结束人工接待，清除 pending 和 human_mode"""
    from app.services.pending_store import remove_pending

    await append_session_messages(session_id, [], extra_state={"human_mode": False})
    await remove_pending(session_id)


async def get_thread_messages(session_id: str) -> list[BaseMessage]:
    """获取线程完整短期对话"""
    values = await get_channel_values(session_id)
    return values.get("messages", [])
