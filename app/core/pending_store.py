"""
待审核队列存储

支持两级存储：
1. Redis（生产）— 持久化、多进程共享、重启不丢失
2. 内存 dict（降级）— Redis 不可用时自动回退，重启丢失

所有函数都是 async，调用方需 await。
"""

import json
import logging
from typing import Optional


logger = logging.getLogger(__name__)

# ---- 内存降级存储 ----
_memory: dict[str, dict] = {}

# ---- Redis 客户端（懒初始化） ----
_redis_client = None
_redis_available = False
_connection_checked = False


async def _get_redis():
    """获取 Redis 连接（懒初始化，只在首次调用时检查连通性）"""
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
        logger.info("Redis connected — pending_store using Redis (%s)", cfg.REDIS_URL)
    except Exception as exc:
        _redis_client = None
        _redis_available = False
        logger.warning(
            "Redis unavailable (%s), pending_store falling back to in-memory dict",
            exc,
        )
    return _redis_client if _redis_available else None


# ---- Redis Key 前缀 ----
_PREFIX = "pending:"
_TTL_SECONDS = 86400  # 24 小时自动过期


async def add_pending(session_id: str, payload: dict) -> None:
    """记录一个等待人工审核的会话"""
    r = await _get_redis()
    if r:
        await r.set(f"{_PREFIX}{session_id}", json.dumps(payload, ensure_ascii=False, default=str), ex=_TTL_SECONDS)
    else:
        _memory[session_id] = payload


async def remove_pending(session_id: str) -> Optional[dict]:
    """审核完成，移除并返回中断载荷"""
    r = await _get_redis()
    if r:
        data = await r.get(f"{_PREFIX}{session_id}")
        if data:
            await r.delete(f"{_PREFIX}{session_id}")
            return json.loads(data)
        return None
    else:
        return _memory.pop(session_id, None)


async def get_pending(session_id: str) -> Optional[dict]:
    """查询某个会话是否在等待审核"""
    r = await _get_redis()
    if r:
        data = await r.get(f"{_PREFIX}{session_id}")
        return json.loads(data) if data else None
    else:
        return _memory.get(session_id)


async def get_all_pending() -> dict[str, dict]:
    """获取所有等待审核的会话"""
    r = await _get_redis()
    if r:
        keys = await r.keys(f"{_PREFIX}*")
        result = {}
        for key in keys:
            data = await r.get(key)
            if data:
                session_id = key[len(_PREFIX):]
                result[session_id] = json.loads(data)
        return result
    else:
        return dict(_memory)
