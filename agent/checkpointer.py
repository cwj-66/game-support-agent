"""
LangGraph 状态持久化配置 — RedisSaver

用 Redis 替代 SQLite 存储 Agent 执行状态（messages、中断点等）。
RedisSaver 支持同步/异步双模式，共享同一连接实例。
"""

import logging
from typing import Optional

from langgraph.checkpoint.redis import RedisSaver

logger = logging.getLogger(__name__)

_saver: Optional[RedisSaver] = None


def _get_redis_config() -> tuple[str, str | None]:
    """获取 Redis 连接配置，优先从 app 配置读取"""
    try:
        from app.core.config import get_settings

        cfg = get_settings()
        return cfg.REDIS_URL, cfg.REDIS_PASSWORD
    except Exception:
        return "redis://localhost:6379/0", None


async def init_checkpointer() -> None:
    """初始化 RedisSaver（应用启动时调用）"""
    global _saver
    if _saver is not None:
        return

    redis_url, password = _get_redis_config()
    try:
        conn_args = {"password": password} if password else {}
        _saver = RedisSaver(redis_url=redis_url, connection_args=conn_args)
        _saver.setup()
        logger.info("RedisSaver initialized — Agent state in Redis (%s)", redis_url)
    except Exception as exc:
        logger.critical(
            "RedisSaver init failed — is Redis running at %s? %s", redis_url, exc
        )
        raise


async def get_checkpointer() -> RedisSaver:
    """获取 RedisSaver（用于 async invoke / astream）"""
    if _saver is None:
        await init_checkpointer()
    return _saver


def get_sync_checkpointer() -> RedisSaver:
    """
    获取 RedisSaver（用于同步 invoke / Command resume）

    RedisSaver 自动支持 sync / async 两种操作模式，返回同一实例。
    """
    if _saver is None:
        raise RuntimeError(
            "RedisSaver not initialized. Ensure FastAPI startup completed "
            "or Redis is reachable."
        )
    return _saver
