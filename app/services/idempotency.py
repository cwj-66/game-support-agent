"""有副作用操作的幂等结果缓存：相同 client_request_id 重试时直接返回首次结果。"""

from __future__ import annotations

import hashlib
import re
from typing import Optional

from app.core.config import get_settings
from app.core.exceptions import CapacityUnavailableException
from app.services.coordination import CoordinationUnavailable, get_coordination

_REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9_-]{8,64}$")


def valid_request_id(value: Optional[str]) -> Optional[str]:
    """校验客户端请求 ID；格式不合法时视为未提供。"""
    return value if value and _REQUEST_ID_RE.match(value) else None


def _key(scope: str, request_id: str) -> str:
    return "gsa:idem:" + hashlib.sha256(f"{scope}\0{request_id}".encode()).hexdigest()


async def load_result(scope: str, request_id: Optional[str]) -> Optional[dict]:
    if not request_id:
        return None
    try:
        return await get_coordination().get_json(_key(scope, request_id))
    except CoordinationUnavailable:
        raise CapacityUnavailableException()


async def save_result(scope: str, request_id: Optional[str], payload: dict) -> None:
    if not request_id:
        return
    try:
        await get_coordination().set_json(
            _key(scope, request_id), payload, get_settings().IDEMPOTENCY_TTL_SECONDS * 1000
        )
    except CoordinationUnavailable:
        # 结果已生效，只是无法缓存；重试会被会话状态校验拦下（例如待确认工单已被消费）。
        pass
