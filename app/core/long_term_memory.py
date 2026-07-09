"""
长期记忆存储

按 user_id 保存历史会话摘要（2h 过期归档产生）。
新会话开始时注入 system prompt，不做全文对话恢复。
"""

import json
import logging
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

_PREFIX = "ltm:"
_MAX_ENTRIES = 10  # 每用户最多保留条数
_memory: dict[str, list[dict]] = {}

_redis_client = None
_redis_available = False
_connection_checked = False


async def _get_redis():
    global _redis_client, _redis_available, _connection_checked
    if _connection_checked:
        return _redis_client if _redis_available else None
    _connection_checked = True
    try:
        from app.core.config import get_settings
        import redis.asyncio as aioredis

        cfg = get_settings()
        _redis_client = aioredis.from_url(
            cfg.REDIS_URL,
            password=cfg.REDIS_PASSWORD or None,
            decode_responses=True,
            socket_connect_timeout=2,
            socket_timeout=2,
        )
        await _redis_client.ping()
        _redis_available = True
    except Exception as exc:
        _redis_client = None
        _redis_available = False
        logger.warning("long_term_memory Redis unavailable, using in-memory: %s", exc)
    return _redis_client if _redis_available else None


def _key(user_id: str) -> str:
    return f"{_PREFIX}{user_id}"


async def save_session_summary(
    user_id: str,
    summary: str,
    session_id: str = "",
    outcome: str = "",
) -> None:
    """保存一条会话摘要"""
    if not user_id or not summary.strip():
        return

    entry = {
        "summary": summary.strip(),
        "session_id": session_id,
        "outcome": outcome,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }

    r = await _get_redis()
    if r:
        key = _key(user_id)
        await r.lpush(key, json.dumps(entry, ensure_ascii=False))
        await r.ltrim(key, 0, _MAX_ENTRIES - 1)
    else:
        _memory.setdefault(user_id, []).insert(0, entry)
        _memory[user_id] = _memory[user_id][:_MAX_ENTRIES]

    logger.info("Long-term memory saved for user %s: %s", user_id, summary[:80])


async def get_recent_summaries(user_id: str, limit: int = 3) -> list[dict[str, Any]]:
    """读取用户最近几条历史会话摘要"""
    if not user_id:
        return []

    r = await _get_redis()
    if r:
        raw_list = await r.lrange(_key(user_id), 0, limit - 1)
        result = []
        for raw in raw_list:
            try:
                result.append(json.loads(raw))
            except json.JSONDecodeError:
                continue
        return result

    return _memory.get(user_id, [])[:limit]


async def format_memory_prompt_block(user_id: str, limit: int = 3) -> str:
    """格式化为可注入 system prompt 的文本块"""
    entries = await get_recent_summaries(user_id, limit=limit)
    if not entries:
        return ""

    lines = ["【该玩家历史会话摘要（仅供参考，非当前对话）】"]
    for i, e in enumerate(entries, 1):
        ts = e.get("created_at", "")[:16].replace("T", " ")
        lines.append(f"{i}. [{ts}] {e.get('summary', '')}")
    return "\n".join(lines)
