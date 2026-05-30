"""
LLM 工厂模块
统一创建 ChatOpenAI 实例，支持阿里云与OpenAI双通道
"""

from typing import Optional
from langchain_openai import ChatOpenAI

from app.core.config import get_settings, get_llm_provider


def get_chat_model(model_name: Optional[str] = None) -> ChatOpenAI:
    """
    创建统一的聊天模型实例

    策略：
    - 优先使用阿里云 DashScope（DASHSCOPE_API_KEY）
    - 若未配置则回退 OpenAI（OPENAI_API_KEY）
    - 可传入 model_name 覆盖默认模型（generate 节点用轻量模型）
    """
    settings = get_settings()
    provider = get_llm_provider(settings)
    model = model_name or settings.REASONING_MODEL_NAME or settings.MODEL_NAME or "qwen-turbo"

    if provider == "dashscope":
        extra_body = (
            {"thinking": {"type": "disabled"}}
            if not settings.ENABLE_THINKING
            else None
        )
        return ChatOpenAI(
            model=model,
            api_key=settings.DASHSCOPE_API_KEY,
            base_url=settings.LLM_BASE_URL
            or "https://dashscope.aliyuncs.com/compatible-mode/v1",
            temperature=0.2,
            extra_body=extra_body,
        )

    return ChatOpenAI(
        model=model,
        api_key=settings.OPENAI_API_KEY,
        base_url=settings.LLM_BASE_URL if settings.LLM_BASE_URL else None,
        temperature=0.2,
    )
