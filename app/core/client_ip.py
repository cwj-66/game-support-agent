"""真实客户端 IP 与访客标识：只信任来自可信代理网段的转发头。"""

from __future__ import annotations

import ipaddress
import re
import secrets
from functools import lru_cache
from http.cookies import SimpleCookie

from fastapi import Request

from app.core.config import get_settings

VISITOR_COOKIE = "gsa_visitor"
_VISITOR_RE = re.compile(r"^[0-9a-f]{32}$")
_VISITOR_MAX_AGE = 30 * 24 * 3600


@lru_cache(maxsize=8)
def _trusted_networks(spec: str) -> tuple:
    networks = []
    for part in spec.split(","):
        part = part.strip()
        if part:
            networks.append(ipaddress.ip_network(part, strict=False))
    return tuple(networks)


def _parse(value: str):
    try:
        return ipaddress.ip_address(value.strip())
    except ValueError:
        return None


def is_trusted_proxy(value: str) -> bool:
    ip = _parse(value)
    if ip is None:
        return False
    return any(ip in net for net in _trusted_networks(get_settings().TRUSTED_PROXY_CIDRS))


def client_ip(request: Request) -> str:
    """直连对端可信时，从 X-Forwarded-For 右侧向左跳过可信代理，取第一个非代理地址。

    决策：不读取 X-Real-IP。边缘 Nginx 用 $remote_addr 覆盖 X-Forwarded-For，
    客户端伪造的转发头不会进入链路；即使边缘改为追加模式，从右侧取值也只会落在真实连接地址上。
    """
    peer = request.client.host if request.client else ""
    if not is_trusted_proxy(peer):
        return peer or "unknown"
    chain = [hop.strip() for hop in request.headers.get("x-forwarded-for", "").split(",") if hop.strip()]
    for hop in reversed(chain):
        if _parse(hop) is None:
            break
        if not is_trusted_proxy(hop):
            return hop
    first = chain[0] if chain and _parse(chain[0]) is not None else ""
    return first or peer or "unknown"


def visitor_id(request: Request) -> str:
    """访客 ID：优先使用中间件写入的值，其次是请求 cookie。"""
    value = getattr(request.state, "visitor_id", None) or request.cookies.get(VISITOR_COOKIE, "")
    return value if _VISITOR_RE.match(value or "") else ""


class VisitorCookieMiddleware:
    """为没有访客 cookie 的请求签发 HttpOnly 随机 ID（纯 ASGI，不缓冲 SSE）。"""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        cookie_header = ""
        secure = False
        for name, value in scope.get("headers", []):
            if name == b"cookie":
                cookie_header = value.decode("latin-1")
            elif name == b"x-forwarded-proto" and value == b"https":
                secure = True
        jar = SimpleCookie()
        try:
            jar.load(cookie_header)
        except Exception:
            jar = SimpleCookie()
        current = jar[VISITOR_COOKIE].value if VISITOR_COOKIE in jar else ""
        if _VISITOR_RE.match(current):
            await self.app(scope, receive, send)
            return

        new_id = secrets.token_hex(16)
        scope.setdefault("state", {})["visitor_id"] = new_id
        attrs = f"{VISITOR_COOKIE}={new_id}; Path=/; Max-Age={_VISITOR_MAX_AGE}; HttpOnly; SameSite=Lax"
        if secure or scope.get("scheme") == "https":
            attrs += "; Secure"

        async def send_with_cookie(message):
            if message["type"] == "http.response.start":
                message.setdefault("headers", [])
                message["headers"] = list(message["headers"]) + [(b"set-cookie", attrs.encode("latin-1"))]
            await send(message)

        await self.app(scope, receive, send_with_cookie)
