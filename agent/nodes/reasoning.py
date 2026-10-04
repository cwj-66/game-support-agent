"""LLM 推理节点：绑定工具自主决策。"""

import logging
from typing import Dict, Any
import re

from langchain_core.messages import SystemMessage, AIMessage, ToolMessage
from langchain_openai import ChatOpenAI

from ..state import AgentState
from ..tools import get_all_tools
from ..prompts.system import GAME_SUPPORT_SYSTEM_PROMPT
from app.core.config import get_settings
from app.core.llm import get_chat_model, llm_invoke

logger = logging.getLogger(__name__)

SERVICE_BUSY_REPLY = "抱歉，智能客服暂时繁忙，暂时无法处理您的问题，请稍后重试。"


def _build_llm_from_settings() -> ChatOpenAI:
    """返回推理模型的共享实例（连接池、超时与重试统一由 app.core.llm 管理）"""
    return get_chat_model(get_settings().REASONING_MODEL_NAME)


def _service_failure(metadata: dict, exc: Exception) -> Dict[str, Any]:
    """模型调用失败：记录诊断类型，向玩家返回通用提示，并让 generate 节点不再调用模型。"""
    logger.warning("reasoning LLM failed: %s", type(exc).__name__)
    metadata["terminal_response"] = SERVICE_BUSY_REPLY
    return {
        "messages": [AIMessage(content=SERVICE_BUSY_REPLY)],
        "metadata": metadata,
        "node_trace": ["reasoning"],
    }


async def reasoning_node(state: AgentState) -> Dict[str, Any]:
    """LLM 绑定工具后自主决策，可调用工具或直接回复。"""
    user_id = state.get("user_id", "")
    history = state.get("messages", [])
    metadata = state.get("metadata", {})

    # 知识查询失败或无命中是本轮的终点，不能把服务故障当作自动建单理由。
    last_message = history[-1] if history else None
    knowledge = metadata.get("knowledge_result")
    explicit_offer = re.search(r"(?:建|创建|提交).{0,4}工单|转人工|人工客服", state.get("user_query", ""))
    if (isinstance(last_message, ToolMessage)
            and last_message.name == "query_knowledge"
            and isinstance(knowledge, dict)
            and not knowledge.get("has_answer")
            and not explicit_offer):
        content = (
            "抱歉，知识库查询暂时失败，我现在无法核实答案。请稍后重试。"
            if knowledge.get("error") else
            "当前知识库没有找到足够依据，我无法确认这个问题的答案。"
        )
        metadata["knowledge_terminal"] = content
        return {
            "messages": [AIMessage(content=content)],
            "metadata": metadata,
            "node_trace": ["reasoning"],
        }

    system_prompt = GAME_SUPPORT_SYSTEM_PROMPT
    if user_id:
        system_prompt += f"\n\n当前玩家 UID：{user_id}"
        try:
            from app.services.long_term_memory import format_memory_prompt_block
            memory_block = await format_memory_prompt_block(user_id, session_id=state.get("session_id", ""))
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
            response: AIMessage = await llm_invoke(llm, llm_messages)
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
            response: AIMessage = await llm_invoke(llm, llm_messages)
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

    if metadata.get("tool_repeated_call") or metadata.get("max_rounds_reached"):
        metadata.pop("tool_repeated_call", None)
        metadata.pop("max_rounds_reached", None)
        try:
            response: AIMessage = await llm_invoke(llm, llm_messages)
        except Exception as exc:
            return _service_failure(metadata, exc)
        return {
            "messages": [response],
            "metadata": metadata,
            "node_trace": ["reasoning"],
        }

    allowed_tools = get_all_tools(user_id)
    llm_with_tools = llm.bind_tools(allowed_tools)

    try:
        response: AIMessage = await llm_invoke(llm_with_tools, llm_messages)
    except Exception as exc:
        return _service_failure(metadata, exc)

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
