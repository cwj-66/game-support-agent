"""
LLM 工厂模块
统一创建 ChatOpenAI 实例，支持阿里云与OpenAI双通道
"""

from langchain_openai import ChatOpenAI

from app.core.config import get_settings, get_llm_provider


def get_chat_model() -> ChatOpenAI:
    """
    创建统一的聊天模型实例

    策略：
    - 优先使用阿里云 DashScope（DASHSCOPE_API_KEY）
    - 若未配置则回退 OpenAI（OPENAI_API_KEY）
    """
    settings = get_settings()
    provider = get_llm_provider(settings)

    if provider == "dashscope":
        return ChatOpenAI(
            model=settings.MODEL_NAME or "qwen-turbo",
            api_key=settings.DASHSCOPE_API_KEY,
            base_url=settings.LLM_BASE_URL
            or "https://dashscope.aliyuncs.com/compatible-mode/v1",
            temperature=0.2,
        )

    return ChatOpenAI(
        model=settings.MODEL_NAME or "gpt-3.5-turbo",
        api_key=settings.OPENAI_API_KEY,
        base_url=settings.LLM_BASE_URL if settings.LLM_BASE_URL else None,
        temperature=0.2,
    )
