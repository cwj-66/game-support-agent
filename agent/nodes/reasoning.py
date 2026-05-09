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
    model_name = settings.MODEL_NAME or "qwen-turbo"
    base_url = settings.LLM_BASE_URL or "https://dashscope.aliyuncs.com/compatible-mode/v1"

    if settings.DASHSCOPE_API_KEY:
        return ChatOpenAI(
            api_key=settings.DASHSCOPE_API_KEY,
            model=model_name,
            base_url=base_url,
            temperature=0.2,
        )

    if settings.OPENAI_API_KEY:
        return ChatOpenAI(
            api_key=settings.OPENAI_API_KEY,
            model=model_name,
            base_url=base_url if settings.LLM_BASE_URL else None,
            temperature=0.2,
        )

    raise ValueError("未配置 LLM 密钥，请在 .env 设置 DASHSCOPE_API_KEY 或 OPENAI_API_KEY")


async def reasoning_node(state: AgentState) -> Dict[str, Any]:
    """
    推理节点：LLM 绑定工具后自主决策（ReAct 风格）

    LLM 收到用户问题后可以：
    - 调用 query_knowledge 查询游戏知识库
    - 调用 lookup_account 查询玩家账号状态
    - 调用 create_ticket 创建客服工单
    - 调用 escalate_to_human 主动触发人工审核
    - 直接输出回答（不调用任何工具）

    工具结果会追加到 messages，LLM 可多轮循环调用直到给出最终回复。
    """
    user_query = state["user_query"]
    history = state.get("messages", [])

    llm = _build_llm_from_settings()
    llm_with_tools = llm.bind_tools(get_all_tools())

    # user_query 始终作为第一条 HumanMessage 传入，不重复添加到 state
    llm_messages = [
        SystemMessage(content=GAME_SUPPORT_SYSTEM_PROMPT),
        HumanMessage(content=user_query),
        *history,
    ]

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
    }
