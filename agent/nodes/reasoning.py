"""
LLM 自主决策节点
分析用户意图，决定是否需要调用工具，评估置信度
"""

import json
from typing import Dict, Any, List
from langchain_core.messages import AIMessage, SystemMessage, HumanMessage
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field, ConfigDict

from ..state import AgentState
from ..prompts.system import GAME_SUPPORT_SYSTEM_PROMPT, build_reasoning_prompt
from app.core.config import get_settings


class ReasoningOutputSchema(BaseModel):
    """大模型结构化输出 Schema（严格）"""

    model_config = ConfigDict(extra="forbid", strict=True)

    intent: str = Field(..., min_length=1, description="用户意图")
    need_tool: bool = Field(..., description="是否需要调用工具")
    confidence: float = Field(..., ge=0.0, le=1.0, description="置信度")
    has_sensitive: bool = Field(..., description="是否包含敏感内容")
    sensitive_words: List[str] = Field(default_factory=list, description="敏感词")
    reasoning: str = Field(..., min_length=1, description="推理过程")


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


def _extract_json_block(content: str) -> Dict[str, Any]:
    """从模型文本中提取 JSON（兼容 ```json ... ``` 包裹）"""
    raw = content.strip()
    if raw.startswith("```"):
        parts = raw.split("```")
        for part in parts:
            part = part.strip()
            if part.startswith("json"):
                part = part[4:].strip()
            if part.startswith("{") and part.endswith("}"):
                return json.loads(part)
    return json.loads(raw)


async def reasoning_node(state: AgentState) -> Dict[str, Any]:
    """
    推理节点：分析用户意图并决策
    
    这是Agent的第一个节点，负责：
    1. 理解用户问题
    2. 评估是否需要调用知识库工具
    3. 检测敏感内容
    4. 输出置信度评分
    
    Args:
        state: 当前Agent状态
    Returns:
        状态更新字典
        
    TODO:
    - 添加工具选择逻辑（未来可能有多个工具）
    - 优化敏感词检测（与detector模块复用逻辑）
    """
    user_query = state["user_query"]
    messages = state["messages"]
    
    # 构建推理提示词
    reasoning_prompt = build_reasoning_prompt(user_query, messages)
    
    # 构造LLM输入
    llm_messages = [
        SystemMessage(content=GAME_SUPPORT_SYSTEM_PROMPT),
        *messages,
        HumanMessage(content=reasoning_prompt),
    ]

    llm = _build_llm_from_settings()
    try:
        result = await analyze_intent_llm(llm, llm_messages, user_query)
    except Exception as exc:
        # LLM异常或JSON解析失败时，回退到保守默认值
        result = ReasoningOutputSchema(
            intent="查询游戏机制",
            need_tool=True,
            confidence=0.6,
            has_sensitive=False,
            sensitive_words=[],
            reasoning=f"LLM解析失败，使用保守策略：优先走知识库，错误: {exc}",
        )
    
    # 将推理结果存入metadata
    reasoning_data = {
        "intent": result.intent,
        "need_tool": result.need_tool,
        "confidence": result.confidence,
        "has_sensitive": result.has_sensitive,
        "sensitive_words": result.sensitive_words,
        "reasoning": result.reasoning,
        "node": "reasoning"
    }
    
    # 更新metadata
    metadata = state.get("metadata", {})
    metadata["reasoning"] = reasoning_data
    
    # 构建AI消息记录推理结果
    ai_message = AIMessage(
        content=f"[推理] 意图：{result.intent}，需要工具：{result.need_tool}"
    )
    
    return {
        "messages": [ai_message],
        "metadata": metadata,
        # 标记是否需要工具调用（用于条件路由）
        "_need_tool": result.need_tool
    }


async def analyze_intent_llm(
    llm: ChatOpenAI,
    messages,
    user_query: str
) -> ReasoningOutputSchema:
    """
    使用LLM分析意图（异步真实网络请求）

    1. 向大模型发起 ainvoke 异步请求
    2. 解析模型返回 JSON
    3. 用 Pydantic 严格校验输出结构
    """
    response = await llm.ainvoke(messages)
    if not isinstance(response.content, str):
        raise ValueError(f"模型返回内容类型错误: {type(response.content)}")

    payload = _extract_json_block(response.content)
    return ReasoningOutputSchema.model_validate(payload)
