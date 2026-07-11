"""
客服会话 TTL 管理

用 Redis key 记录会话最后活跃时间，2 小时无活动视为过期。
过期后清除 LangGraph checkpoint，下次消息等同新会话。

Agent 记忆策略：
- 只保留当前会话内的 messages（原文）
- 不跨会话保留 metadata / 用户画像
- UI 对话框由前端自己展示，与此模块无关
"""

import logging
import time

logger = logging.getLogger(__name__)

_PREFIX = "session:active:"
_memory: dict[str, float] = {}  # session_id -> expire_timestamp（Redis 不可用时的降级）

_redis_client = None
_redis_available = False
_connection_checked = False


async def _get_redis():
    """获取 Redis 连接（懒初始化）"""
    global _redis_client, _redis_available, _connection_checked

    if _connection_checked:
        return _redis_client if _redis_available else None

    _connection_checked = True
    try:
        from app.core.config import get_settings
        cfg = get_settings()
        import redis.asyncio as aioredis

        _redis_client = aioredis.from_url(
            cfg.REDIS_URL,
            password=cfg.REDIS_PASSWORD or None,
            decode_responses=True,
            socket_connect_timeout=2,
            socket_timeout=2,
        )
        await _redis_client.ping()
        _redis_available = True
        logger.info("Redis connected — session_store using Redis")
    except Exception as exc:
        _redis_client = None
        _redis_available = False
        logger.warning("Redis unavailable for session_store, using in-memory fallback: %s", exc)
    return _redis_client if _redis_available else None


def _ttl_seconds() -> int:
    from app.core.config import get_settings
    return get_settings().SESSION_TTL_SECONDS


async def is_session_active(session_id: str) -> bool:
    """会话是否在 TTL 内（True=活跃，False=已过期或首次）"""
    r = await _get_redis()
    if r:
        return await r.exists(f"{_PREFIX}{session_id}") > 0
    expire_at = _memory.get(session_id)
    if expire_at is None:
        return False
    return time.time() < expire_at


async def touch_session(session_id: str) -> None:
    """刷新会话 TTL（每次收到用户消息时调用）"""
    ttl = _ttl_seconds()
    r = await _get_redis()
    if r:
        await r.set(f"{_PREFIX}{session_id}", "1", ex=ttl)
    else:
        _memory[session_id] = time.time() + ttl


async def clear_session(session_id: str) -> None:
    """主动清除会话标记（测试或手动重置用）"""
    r = await _get_redis()
    if r:
        await r.delete(f"{_PREFIX}{session_id}")
    else:
        _memory.pop(session_id, None)


async def expire_session_if_needed(session_id: str) -> bool:
    """
    检查会话是否过期；若过期则清除 LangGraph checkpoint。

    Returns:
        True  — 会话仍活跃（或刚 touch）
        False — 会话已过期，checkpoint 已清除，等同新会话
    """
    active = await is_session_active(session_id)
    if active:
        await touch_session(session_id)
        return True

    # 会话过期 → 先归档长期记忆，再清除 checkpoint
    try:
        from app.core.session_summary import archive_session_before_clear
        await archive_session_before_clear(session_id)
    except Exception as exc:
        logger.warning("Session archive failed for %s: %s", session_id, exc)

    try:
        from agent.checkpointer import get_checkpointer
        cp = await get_checkpointer()
        await cp.adelete_thread(session_id)
        logger.info("Session expired, checkpoint cleared: %s", session_id)
    except Exception as exc:
        logger.warning("Failed to clear checkpoint for expired session %s: %s", session_id, exc)

    await touch_session(session_id)
    return False
