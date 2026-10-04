"""访客级提问频率限制（固定 60 秒窗口）；与会话锁、全站容量是三道独立的门。"""

from __future__ import annotations

import hashlib
import logging
import math
import time
from collections import OrderedDict

from fastapi import Request

from app.core.client_ip import client_ip, visitor_id
from app.core.config import get_settings
from app.core.exceptions import RateLimitedException
from app.services.coordination import CoordinationUnavailable, get_coordination

logger = logging.getLogger(__name__)

_WINDOW_MS = 60_000
_local: "OrderedDict[str, tuple[int, float]]" = OrderedDict()  # Redis 故障时的进程内兜底计数
_LOCAL_MAX_KEYS = 4096


def _local_hit(key: str) -> tuple[int, int]:
    now = time.monotonic() * 1000
    count, expires = _local.get(key, (0, now + _WINDOW_MS))
    if expires <= now:
        count, expires = 0, now + _WINDOW_MS
    _local[key] = (count + 1, expires)
    _local.move_to_end(key)
    while len(_local) > _LOCAL_MAX_KEYS:
        _local.popitem(last=False)
    return count + 1, int(expires - now)


async def _hit(key: str) -> tuple[int, int]:
    try:
        return await get_coordination().hit_window(key, _WINDOW_MS)
    except CoordinationUnavailable:
        # 决策：频率限制在 Redis 故障时退回本进程计数而不是放开；问答本身仍会被容量控制拒绝。
        logger.warning("rate limit backend unavailable; using in-process window")
        return _local_hit(key)


def _key(kind: str, scope: str, ident: str) -> str:
    return f"gsa:rate:{scope}:{kind}:" + hashlib.sha256(ident.encode()).hexdigest()[:32]


async def enforce_chat_rate(request: Request, scope: str = "chat") -> None:
    """按访客 cookie 和真实客户端 IP 各计一次；任一超限返回 429 + Retry-After。"""
    s = get_settings()
    checks = [
        ("visitor", visitor_id(request), s.CHAT_RATE_LIMIT_PER_MINUTE),
        ("ip", client_ip(request), s.CHAT_RATE_LIMIT_PER_IP_PER_MINUTE),
    ]
    for kind, ident, limit in checks:
        if not ident:
            continue
        count, ttl_ms = await _hit(_key(kind, scope, ident))
        if count > limit:
            raise RateLimitedException(retry_after=max(1, math.ceil(ttl_ms / 1000)))
