"""
人工接待图唤醒工具
统一处理 Command(resume=...) 与 GraphInterrupt 预期异常
"""

from langgraph.types import Command

from agent.graph import get_graph


def graph_config(session_id: str) -> dict:
    """构建 LangGraph config"""
    return {
        "configurable": {
            "thread_id": session_id,
            "checkpoint_ns": "game_support_agent",
        }
    }


def is_graph_interrupt(exc: Exception) -> bool:
    """是否为 LangGraph interrupt 挂起（预期行为）"""
    name = type(exc).__name__
    return "GraphInterrupt" in name or "Interrupt" in name


async def invoke_human_resume(session_id: str, resume_payload: dict) -> dict | None:
    """
    唤醒 human 节点追加消息。

    interrupt 后图会再次挂起，可能抛 GraphInterrupt，属于正常情况。
    返回 ainvoke 结果；若仅为 interrupt 挂起则返回 None。
    """
    g = await get_graph()
    try:
        return await g.ainvoke(Command(resume=resume_payload), graph_config(session_id))
    except Exception as e:
        if is_graph_interrupt(e):
            return None
        raise
