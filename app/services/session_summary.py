"""
会话归档：2h 过期前用 LLM 生成摘要写入长期记忆
"""

import logging
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

logger = logging.getLogger(__name__)

SUMMARY_PROMPT = """你是客服会话归档助手。根据以下对话记录，用**一段话**（80~150字）总结这次会话。

必须包含：
- 大致时间（用记录中的时间或“本次会话”）
- 玩家 UID
- 遇到了什么问题
- 最终结果（选一种说清楚）：问题已解答 / 创建了工单（写出工单号）/ 用户取消建单 / 转人工 / 未解决

只输出摘要正文，不要标题、不要列表。"""


def _messages_to_text(messages: list, user_id: str) -> str:
    """把 checkpoint messages 转成可读文本"""
    lines = [f"玩家 UID：{user_id}"]
    for msg in messages:
        if isinstance(msg, HumanMessage):
            lines.append(f"玩家：{msg.content}")
        elif isinstance(msg, AIMessage):
            lines.append(f"客服：{msg.content}")
        elif isinstance(msg, ToolMessage):
            content = str(msg.content)
            if len(content) > 300:
                content = content[:300] + "..."
            lines.append(f"[工具 {msg.name}] {content}")
    return "\n".join(lines)


def _guess_outcome(channel_values: dict[str, Any]) -> str:
    """从 state 字段推断结果类型（辅助日志）"""
    ticket_id = channel_values.get("ticket_id")
    if ticket_id:
        return f"ticket_created:{ticket_id}"
    if channel_values.get("human_mode"):
        return "human_escalated"
    if channel_values.get("human_offer"):
        return "human_offer_pending"
    if channel_values.get("ticket_offer"):
        return "ticket_offer_pending"
    return "resolved_or_unknown"


async def archive_session_before_clear(session_id: str) -> None:
    """
    会话过期清 checkpoint 前：读取 state → LLM 摘要 → 写入长期记忆。
    无 checkpoint 或 messages 为空时静默跳过。
    """
    from agent.checkpointer import get_checkpointer
    from app.core.checkpoint_helper import graph_config
    from app.services.long_term_memory import save_session_summary

    checkpointer = await get_checkpointer()
    config = graph_config(session_id)
    checkpoint_tuple = await checkpointer.aget_tuple(config)
    if checkpoint_tuple is None:
        checkpoint_tuple = await checkpointer.aget_tuple(
            {"configurable": {"thread_id": session_id}}
        )
    if checkpoint_tuple is None:
        return

    channel_values = checkpoint_tuple.checkpoint.get("channel_values", {})
    messages = channel_values.get("messages") or []
    user_id = channel_values.get("user_id", "")
    if not messages or not user_id:
        return

    transcript = _messages_to_text(messages, user_id)
    outcome = _guess_outcome(channel_values)

    try:
        from langchain_core.messages import SystemMessage
        from app.core.llm import get_chat_model

        llm = get_chat_model()
        result = await llm.ainvoke([
            SystemMessage(content=SUMMARY_PROMPT),
            HumanMessage(content=transcript),
        ])
        summary = result.content if isinstance(result.content, str) else str(result.content)
    except Exception as exc:
        logger.warning("archive: LLM summary failed for %s: %s", session_id, exc)
        # 降级：简单拼接
        summary = f"玩家 {user_id} 本次会话共 {len(messages)} 条消息，结果：{outcome}"

    await save_session_summary(
        user_id=user_id,
        summary=summary,
        session_id=session_id,
        outcome=outcome,
    )
