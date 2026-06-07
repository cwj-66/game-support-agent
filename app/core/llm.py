"""
LLM 工厂模块
统一创建 ChatOpenAI 实例
"""

from typing import Optional
from langchain_openai import ChatOpenAI

from app.core.config import get_settings


def get_chat_model(model_name: Optional[str] = None) -> ChatOpenAI:
    """
    创建统一的聊天模型实例
    可传入 model_name 覆盖默认模型（generate 节点用轻量模型）
    """
    settings = get_settings()
    model = model_name or settings.REASONING_MODEL_NAME or settings.MODEL_NAME or "qwen-turbo"
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
