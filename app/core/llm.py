"""LLM 工厂：复用连接池的 ChatOpenAI 实例，以及带超时、重试与熔断的调用封装。"""

import asyncio
from typing import Any, Callable, Optional

import httpx
from langchain_openai import ChatOpenAI

from app.core.config import get_settings
from app.core.resilience import guarded_call

_models: dict[str, ChatOpenAI] = {}
_http_client: Optional[httpx.AsyncClient] = None
_bound_loop: Optional[asyncio.AbstractEventLoop] = None


def _shared_http_client() -> httpx.AsyncClient:
    """同一事件循环内共享的 Qwen HTTP 客户端（有界连接池）。"""
    global _http_client, _bound_loop
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    if _http_client is None or (loop is not None and loop is not _bound_loop):
        # 决策：事件循环变化（测试或重启）时重建，避免复用绑定在已关闭循环上的连接。
        s = get_settings()
        _models.clear()
        _bound_loop = loop
        _http_client = httpx.AsyncClient(
            timeout=httpx.Timeout(s.LLM_READ_TIMEOUT_SECONDS, connect=s.LLM_CONNECT_TIMEOUT_SECONDS),
            limits=httpx.Limits(max_connections=s.LLM_MAX_CONNECTIONS, max_keepalive_connections=s.LLM_MAX_CONNECTIONS),
        )
    return _http_client


def get_chat_model(model_name: Optional[str] = None) -> ChatOpenAI:
    """返回指定模型的共享实例；SDK 自带重试关闭，统一由 guarded_call 控制。"""
    settings = get_settings()
    model = model_name or settings.REASONING_MODEL_NAME or "qwen3.8-flash"
    http_client = _shared_http_client()
    if model not in _models:
        extra_body = (
            {"thinking": {"type": "disabled"}}
            if not settings.ENABLE_THINKING
            else None
        )
        _models[model] = ChatOpenAI(
            model=model,
            api_key=settings.DASHSCOPE_API_KEY,
            base_url=settings.LLM_BASE_URL
            or "https://dashscope.aliyuncs.com/compatible-mode/v1",
            temperature=0.2,
            extra_body=extra_body,
            timeout=httpx.Timeout(settings.LLM_READ_TIMEOUT_SECONDS, connect=settings.LLM_CONNECT_TIMEOUT_SECONDS),
            max_retries=0,
            http_async_client=http_client,
        )
    return _models[model]


async def llm_invoke(llm: Any, messages: list) -> Any:
    """非流式调用：临时错误最多重试 UPSTREAM_MAX_RETRIES 次。"""
    return await guarded_call("qwen", lambda: llm.ainvoke(messages))


async def llm_stream(llm: Any, messages: list, on_text: Callable[[str], None]) -> str:
    """流式调用：只有尚未输出任何内容时才允许重试，避免客户端看到重复文本。"""
    parts: list[str] = []

    async def run() -> str:
        async for chunk in llm.astream(messages):
            if isinstance(chunk.content, str) and chunk.content:
                parts.append(chunk.content)
                on_text(chunk.content)
        return "".join(parts)

    return await guarded_call("qwen", run, can_retry=lambda: not parts)


async def close_llm_clients() -> None:
    global _http_client
    if _http_client is not None:
        await _http_client.aclose()
        _http_client = None
    _models.clear()
