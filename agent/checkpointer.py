"""
LangGraph 状态持久化配置 — AsyncRedisSaver

用 AsyncRedisSaver 替代 RedisSaver，以支持 FastAPI async 接口的异步调用。
0.4.x 版本的 RedisSaver.aget_tuple 未实现，必须使用 AsyncRedisSaver。
"""

import logging
from typing import Optional

from langgraph.checkpoint.redis import AsyncRedisSaver

logger = logging.getLogger(__name__)

_saver: Optional[AsyncRedisSaver] = None


def _get_redis_config() -> tuple[str, str | None]:
    """获取 Redis 连接配置，优先从 app 配置读取"""
    try:
        from app.core.config import get_settings

        cfg = get_settings()
        return cfg.REDIS_URL, cfg.REDIS_PASSWORD
    except Exception:
        return "redis://localhost:6379/0", None


async def init_checkpointer() -> None:
    """初始化 AsyncRedisSaver（应用启动时调用）"""
    global _saver
    if _saver is not None:
        return

    redis_url, password = _get_redis_config()
    try:
        conn_args = {"password": password} if password else {}
        _saver = AsyncRedisSaver(redis_url=redis_url, connection_args=conn_args)
        # 0.4.x AsyncRedisSaver 用 asetup() 做异步初始化（创建索引等）
        await _saver.asetup()
        logger.info("AsyncRedisSaver initialized — Agent state in Redis (%s)", redis_url)
    except Exception as exc:
        logger.critical(
            "AsyncRedisSaver init failed — is Redis running at %s? %s", redis_url, exc
        )
        raise


async def get_checkpointer() -> AsyncRedisSaver:
    """获取 AsyncRedisSaver（用于 async invoke / astream）"""
    if _saver is None:
        await init_checkpointer()
    return _saver


def get_sync_checkpointer() -> AsyncRedisSaver:
    """
    获取 AsyncRedisSaver（用于同步 invoke / Command resume）

    AsyncRedisSaver 同时支持同步和异步操作，返回同一实例。
    """
    if _saver is None:
        raise RuntimeError(
            "AsyncRedisSaver not initialized. Ensure FastAPI startup completed "
            "or Redis is reachable."
        )
    return _saver
