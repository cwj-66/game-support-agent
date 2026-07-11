"""
LangGraph checkpoint 辅助工具

用于对话外（如 ticket-confirm）直接向 checkpoint 追加消息，
无需重新跑 Agent 图。
"""

from typing import Any

from langchain_core.messages import AIMessage, BaseMessage


def graph_config(session_id: str) -> dict:
    """构建 LangGraph thread config"""
    return {
        "configurable": {
            "thread_id": session_id,
            "checkpoint_ns": "game_support_agent",
        }
    }


async def append_session_messages(
    session_id: str,
    messages: list[BaseMessage],
    extra_state: dict[str, Any] | None = None,
) -> None:
    """
    向会话 checkpoint 追加消息（及可选 state 字段）。

    利用 LangGraph aupdate_state + add_messages reducer 自动合并。
    """
    if not messages and not extra_state:
        return

    from agent.graph import get_graph

    values: dict[str, Any] = {}
    if messages:
        values["messages"] = messages
    if extra_state:
        values.update(extra_state)

    g = await get_graph()
    # 根图无子图：aupdate_state 不能带 checkpoint_ns，否则会报 Subgraph not found
    await g.aupdate_state(
        {"configurable": {"thread_id": session_id}},
        values,
    )


async def append_agent_reply(session_id: str, content: str, **extra_state: Any) -> None:
    """追加一条 AI 回复到会话 checkpoint"""
    await append_session_messages(
        session_id,
        [AIMessage(content=content)],
        extra_state or None,
    )


async def checkpoint_exists(session_id: str) -> bool:
    """会话是否已有 LangGraph checkpoint（用于跳过无意义的归档）"""
    from agent.checkpointer import get_checkpointer

    checkpointer = await get_checkpointer()
    config = graph_config(session_id)
    if await checkpointer.aget_tuple(config) is not None:
        return True
    return await checkpointer.aget_tuple(
        {"configurable": {"thread_id": session_id}}
    ) is not None
