"""LLM 推理节点：绑定工具自主决策。"""

from typing import Dict, Any

from langchain_core.messages import SystemMessage, AIMessage
from langchain_openai import ChatOpenAI

from ..state import AgentState
from ..tools import get_all_tools
from ..prompts.system import GAME_SUPPORT_SYSTEM_PROMPT
from app.core.config import get_settings


def _build_llm_from_settings() -> ChatOpenAI:
    """从配置创建 LLM 实例"""
    settings = get_settings()
    model_name = settings.REASONING_MODEL_NAME or "qwen-turbo"
    base_url = settings.LLM_BASE_URL or "https://dashscope.aliyuncs.com/compatible-mode/v1"
    extra_body = (
        {"thinking": {"type": "disabled"}}
        if not settings.ENABLE_THINKING
        else None
    )
    return ChatOpenAI(
        api_key=settings.DASHSCOPE_API_KEY,
        model=model_name,
        base_url=base_url,
        temperature=0.2,
        extra_body=extra_body,
    )


async def reasoning_node(state: AgentState) -> Dict[str, Any]:
    """LLM 绑定工具后自主决策，可调用工具或直接回复。"""
    user_id = state.get("user_id", "")
    history = state.get("messages", [])
    metadata = state.get("metadata", {})

    system_prompt = GAME_SUPPORT_SYSTEM_PROMPT
    if user_id:
        system_prompt += f"\n\n当前玩家 UID：{user_id}"
        try:
            from app.services.long_term_memory import format_memory_prompt_block
            memory_block = await format_memory_prompt_block(user_id)
            if memory_block:
                system_prompt += f"\n\n{memory_block}"
        except Exception:
            pass

    llm_messages = [
        SystemMessage(content=system_prompt),
        *history,
    ]

    llm = _build_llm_from_settings()

    if metadata.get("ticket_offer_pending"):
        metadata.pop("ticket_offer_pending", None)
        try:
            response: AIMessage = await llm.ainvoke(llm_messages)
        except Exception:
            response = AIMessage(content="好的，已为您整理了问题详情，请稍后确认是否需要创建工单。")
        content = response.content or ""
        if not str(content).strip():
            content = (
                "很抱歉没能为您解决问题。您可通过下方按钮确认是否创建工单，"
                "也可以继续向我求助。"
            )
        response = AIMessage(content=content)
        return {
            "messages": [response],
            "metadata": metadata,
            "node_trace": ["reasoning"],
        }

    if metadata.get("human_offer_pending"):
        metadata.pop("human_offer_pending", None)
        try:
            response: AIMessage = await llm.ainvoke(llm_messages)
        except Exception:
            response = AIMessage(content="我们理解您的心情。请通过下方按钮确认是否需要转接人工客服。")
        content = response.content or ""
        if not str(content).strip():
            content = (
                "很抱歉没能为您解决问题。您可通过下方按钮确认是否转接人工客服，"
                "也可以继续向我求助。"
            )
        response = AIMessage(content=content)
        return {
            "messages": [response],
            "metadata": metadata,
            "node_trace": ["reasoning"],
        }

    if metadata.get("tool_repeated_call"):
        metadata.pop("tool_repeated_call", None)
        try:
            response: AIMessage = await llm.ainvoke(llm_messages)
        except Exception as exc:
            response = AIMessage(content=f"抱歉，处理您的请求时出现问题，建议联系人工客服。（错误：{exc}）")
        return {
            "messages": [response],
            "metadata": metadata,
            "node_trace": ["reasoning"],
        }

    if metadata.get("max_rounds_reached"):
        metadata.pop("max_rounds_reached", None)
        try:
            response: AIMessage = await llm.ainvoke(llm_messages)
        except Exception as exc:
            response = AIMessage(content=f"抱歉，处理您的请求时出现问题，建议联系人工客服。（错误：{exc}）")
        return {
            "messages": [response],
            "metadata": metadata,
            "node_trace": ["reasoning"],
        }

    allowed_tools = get_all_tools(user_id)
    llm_with_tools = llm.bind_tools(allowed_tools)

    try:
        response: AIMessage = await llm_with_tools.ainvoke(llm_messages)
    except Exception as exc:
        response = AIMessage(content=f"抱歉，处理您的请求时出现问题，建议联系人工客服。（错误：{exc}）")

    has_tool_calls = bool(getattr(response, "tool_calls", None))

    metadata = state.get("metadata", {})
    metadata["reasoning"] = {
        "intent": "LLM工具调用决策",
        "need_tool": has_tool_calls,
        "node": "reasoning",
    }

    return {
        "messages": [response],
        "metadata": metadata,
        "node_trace": ["reasoning"],
    }
