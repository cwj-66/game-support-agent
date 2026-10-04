"""Password gate shared by player and reviewer APIs; credentials stay server-side."""
import hashlib
import hmac
import os
import secrets
import time
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit

import jwt
from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field
from starlette.responses import JSONResponse

COOKIE = "gsa_demo_access"
TTL = 24 * 60 * 60
router = APIRouter(prefix="/api/v1/access", tags=["演示访问"])
_attempts = defaultdict(deque)


def enabled():
    return bool(os.getenv("DEMO_ACCESS_PASSWORD_HASH"))


def authenticated(request):
    if not enabled():
        return False
    secret = os.getenv("DEMO_ACCESS_SECRET", "")
    if not secret:
        return False
    try:
        payload = jwt.decode(request.cookies.get(COOKIE, ""), secret, algorithms=["HS256"],
                             audience="game-support-demo", options={"require": ["exp", "sub", "aud"]})
        return payload.get("sub") == "demo-reviewer"
    except jwt.PyJWTError:
        return False


class DemoAccessMiddleware:
    # Pure ASGI middleware preserves SSE streaming without response buffering.
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http" and enabled():
            request = Request(scope)
            public = {"/api/v1/access/session", "/api/v1/access/status", "/health"}
            if request.url.path not in public:
                if not authenticated(request):
                    await JSONResponse({"detail": "请先输入演示访问密码", "code": "demo_access_required"}, status_code=401)(scope, receive, send)
                    return
                origin = request.headers.get("origin")
                if request.method not in {"GET", "HEAD", "OPTIONS"} and origin and urlsplit(origin).hostname != request.url.hostname:
                    await JSONResponse({"detail": "不允许跨站操作"}, status_code=403)(scope, receive, send)
                    return
        await self.app(scope, receive, send)


async def _get_rate_redis():
    from app.services.pending_store import _get_redis
    return await _get_redis()


async def _reserve_attempt(ip):
    key = "demo:access:attempts:" + hashlib.sha256(ip.encode()).hexdigest()
    try:
        redis = await _get_rate_redis()
        if redis is not None:
            count = await redis.eval(
                "local n=redis.call('INCR',KEYS[1]); if n==1 then redis.call('EXPIRE',KEYS[1],60) end; return n",
                1, key,
            )
            if count > 10:
                wait = max(1, await redis.ttl(key))
                raise HTTPException(429, "尝试次数过多，请一分钟后重试", headers={"Retry-After": str(wait)})
            return key
    except HTTPException:
        raise
    except Exception:
        pass  # Keep a local limit if Redis is temporarily unavailable.
    now = time.monotonic()
    attempts = _attempts[ip]
    while attempts and attempts[0] < now - 60:
        attempts.popleft()
    if len(attempts) >= 10:
        raise HTTPException(429, "尝试次数过多，请一分钟后重试", headers={"Retry-After": "60"})
    attempts.append(now)
    # Prune expired clients without clearing active limits.
    if len(_attempts) > 2048:
        expired = [client for client, items in _attempts.items() if not items or items[-1] < now - 60]
        for client in expired:
            del _attempts[client]
    return key


async def _clear_attempts(ip, key):
    _attempts.pop(ip, None)
    try:
        redis = await _get_rate_redis()
        if redis is not None:
            await redis.delete(key)
    except Exception:
        pass


class AccessLogin(BaseModel):
    password: str = Field(min_length=1, max_length=128)


@router.get("/status")
async def status(request: Request):
    return {"authenticated": authenticated(request) or not enabled(), "required": enabled()}


@router.post("/session")
async def login(body: AccessLogin, request: Request, response: Response):
    if not enabled():
        return {"authenticated": True}
    from app.core.client_ip import client_ip
    ip = client_ip(request)
    attempt_key = await _reserve_attempt(ip)
    try:
        salt, expected = os.environ["DEMO_ACCESS_PASSWORD_HASH"].split(":", 1)
        actual = hashlib.pbkdf2_hmac("sha256", body.password.encode(), bytes.fromhex(salt), 310000).hex()
    except (ValueError, KeyError):
        raise HTTPException(503, "演示访问尚未配置")
    if not hmac.compare_digest(actual, expected):
        raise HTTPException(401, "密码不正确，请核对简历中的手机号后 6 位")
    secret = os.getenv("DEMO_ACCESS_SECRET", "")
    if not secret:
        raise HTTPException(503, "演示访问尚未配置")
    await _clear_attempts(ip, attempt_key)
    now_utc = datetime.now(timezone.utc)
    token = jwt.encode({"sub": "demo-reviewer", "aud": "game-support-demo", "iat": now_utc,
                        "exp": now_utc + timedelta(seconds=TTL), "jti": secrets.token_hex(16)}, secret, algorithm="HS256")
    response.set_cookie(COOKIE, token, max_age=TTL, httponly=True, samesite="lax",
                        secure=request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https", path="/")
    response.headers["Cache-Control"] = "no-store"
    return {"authenticated": True}
