"""
LLM 自主决策节点（ReAct 风格）
LLM 通过 bind_tools 主动决定调用哪个工具，或直接生成回复
"""

from typing import Dict, Any

from langchain_core.messages import SystemMessage, HumanMessage, AIMessage
from langchain_openai import ChatOpenAI

from ..state import AgentState
from ..tools import get_all_tools
from ..prompts.system import GAME_SUPPORT_SYSTEM_PROMPT
from app.core.config import get_settings


def _build_llm_from_settings() -> ChatOpenAI:
    """
    从 .env 配置创建大模型实例

    规则：
    - 优先使用阿里云：DASHSCOPE_API_KEY
    - 其次使用 OpenAI：OPENAI_API_KEY
    """
    settings = get_settings()
    model_name = settings.REASONING_MODEL_NAME or settings.MODEL_NAME or "qwen-turbo"
    base_url = settings.LLM_BASE_URL or "https://dashscope.aliyuncs.com/compatible-mode/v1"

    if settings.DASHSCOPE_API_KEY:
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

    if settings.OPENAI_API_KEY:
        return ChatOpenAI(
            api_key=settings.OPENAI_API_KEY,
            model=model_name,
            base_url=base_url if settings.LLM_BASE_URL else None,
            temperature=0.2,
        )

    raise ValueError("未配置 LLM 密钥，请在 .env 设置 DASHSCOPE_API_KEY 或 OPENAI_API_KEY")


def _detect_human_request(user_query: str, history: list) -> bool:
    """关键词匹配检测用户是否明确要求转人工"""
    import re

    # 合并当前查询与上一轮用户消息（多轮对话场景）
    combined = user_query
    from langchain_core.messages import HumanMessage
    for msg in reversed(history[-6:]):
        if isinstance(msg, HumanMessage):
            text = msg.content if isinstance(msg.content, str) else ""
            combined = text + " " + combined
            break

    keywords = [
        "人工", "客服", "真人", "转人工", "找人工",
        "customer service", "human agent", "talk to a human",
        "real person", "speak to a",
    ]
    pattern = "|".join(re.escape(k) for k in keywords)
    return bool(re.search(pattern, combined, re.IGNORECASE))


async def reasoning_node(state: AgentState) -> Dict[str, Any]:
    """
    推理节点：LLM 绑定工具后自主决策（ReAct 风格）

    LLM 收到用户问题后可以：
    - 调用 query_knowledge 查询游戏知识库
    - 调用 lookup_account 查询玩家账号状态（按需传 fields 参数）
    - 调用 create_ticket 创建客服工单
    - 调用 escalate_to_human 主动触发人工审核
    - 直接输出回答（不调用任何工具）

    工具结果会追加到 messages，LLM 可多轮循环调用直到给出最终回复。
    """
    user_query = state["user_query"]
    user_id = state.get("user_id", "")
    history = state.get("messages", [])
    metadata = state.get("metadata", {})

    # 关键词检测：用户是否明确要求转人工
    human_requested = _detect_human_request(user_query, history)

    # ReAct 超限兜底：直接输出优雅降级回复，不再调 LLM
    react_timeout = metadata.get("react_timeout")
    if react_timeout:
        ticket_id = react_timeout.get("ticket_id")
        reason = react_timeout.get("reason", "")
        if ticket_id:
            content = (
                f"抱歉，我多次尝试后仍无法解决您的问题。"
                f"已为您创建工单 {ticket_id}，会有专人在1-3个工作日内与您联系。"
                f"感谢您的耐心等待。"
            )
        else:
            content = (
                f"抱歉，我多次尝试后仍无法解决您的问题。"
                f"建议您联系人工客服获取进一步帮助。"
            )
        return {
            "messages": [AIMessage(content=content)],
            "metadata": metadata,
            "human_requested": human_requested,
            "node_trace": ["reasoning"],
        }

    system_prompt = GAME_SUPPORT_SYSTEM_PROMPT
    if user_id:
        system_prompt += f"\n\n当前玩家 UID：{user_id}"

    llm_messages = [
        SystemMessage(content=system_prompt),
        *history,
        HumanMessage(content=user_query),
    ]

    llm = _build_llm_from_settings()

    # 重复工具调用 → 摘掉工具，强制生成最终回复
    if metadata.get("tool_repeated_call"):
        metadata.pop("tool_repeated_call", None)
        try:
            response: AIMessage = await llm.ainvoke(llm_messages)
        except Exception as exc:
            response = AIMessage(content=f"抱歉，处理您的请求时出现问题，建议联系人工客服。（错误：{exc}）")
        has_tool_calls = False
        return {
            "messages": [response],
            "metadata": metadata,
            "human_requested": human_requested,
            "node_trace": ["reasoning"],
        }

    # human_requested 时只暴露查询类工具，禁止创建工单和转人工
    allowed_tools = get_all_tools(user_id)
    if human_requested:
        allowed_names = {"query_knowledge", "lookup_account"}
        allowed_tools = [t for t in allowed_tools if t.name in allowed_names]
    llm_with_tools = llm.bind_tools(allowed_tools)

    try:
        response: AIMessage = await llm_with_tools.ainvoke(llm_messages)
    except Exception as exc:
        # 降级：直接生成兜底回复，避免崩溃
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
        "human_requested": human_requested,
        "node_trace": ["reasoning"],
    }
