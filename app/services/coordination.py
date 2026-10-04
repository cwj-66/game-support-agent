"""跨进程协调后端：全站容量租约、会话锁、频率窗口、幂等结果。

生产使用 Redis（Lua 脚本保证原子性，时间取 Redis 服务端 TIME 避免各进程时钟偏差）；
memory 后端仅用于单进程开发与测试，必须显式配置，不会在 Redis 故障时自动切换。
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any, Optional

from app.core.config import get_settings

logger = logging.getLogger(__name__)

ACTIVE_KEY = "gsa:capacity:active"
WAIT_KEY = "gsa:capacity:wait"
HEARTBEAT_KEY = "gsa:capacity:wait-hb"
_IDLE_EXPIRE_MS = 10 * 60 * 1000  # 容量键空闲 10 分钟后自动过期，避免占用 noeviction 内存


class CoordinationUnavailable(RuntimeError):
    """协调存储不可用；调用方必须拒绝请求，不得静默跳过限制。"""


# --- Lua 脚本 ---

_NOW = """
local t = redis.call('TIME')
local now = tonumber(t[1]) * 1000 + math.floor(tonumber(t[2]) / 1000)
"""

_ADMIT = _NOW + """
local active, waitq, hb = KEYS[1], KEYS[2], KEYS[3]
local member = ARGV[1]
local lease, maxa, maxq, hbttl, idle = tonumber(ARGV[2]), tonumber(ARGV[3]), tonumber(ARGV[4]), tonumber(ARGV[5]), tonumber(ARGV[6])
redis.call('ZREMRANGEBYSCORE', active, '-inf', now)
local stale = redis.call('ZRANGEBYSCORE', hb, '-inf', now)
for _, m in ipairs(stale) do
  redis.call('ZREM', waitq, m)
  redis.call('ZREM', hb, m)
end
local nactive = redis.call('ZCARD', active)
local rank = redis.call('ZRANK', waitq, member)
if not rank then
  local nwait = redis.call('ZCARD', waitq)
  if nwait >= maxq and nactive + nwait >= maxa then
    return {-1, 0}
  end
  -- 毫秒时间可能相同；沿用队尾的递增分数，避免随机 token 的字典序造成插队。
  local tail = redis.call('ZREVRANGE', waitq, 0, 0, 'WITHSCORES')
  local order = now
  if #tail > 0 then order = math.max(now, tonumber(tail[2]) + 1) end
  redis.call('ZADD', waitq, order, member)
  rank = redis.call('ZRANK', waitq, member)
end
local status = 0
if nactive < maxa and rank < maxa - nactive then
  redis.call('ZREM', waitq, member)
  redis.call('ZREM', hb, member)
  redis.call('ZADD', active, now + lease, member)
  status = 1
else
  redis.call('ZADD', hb, now + hbttl, member)
end
for _, k in ipairs(KEYS) do redis.call('PEXPIRE', k, idle) end
return {status, rank + 1}
"""

_RENEW_LEASE = _NOW + """
redis.call('ZREMRANGEBYSCORE', KEYS[1], '-inf', now)
if redis.call('ZSCORE', KEYS[1], ARGV[1]) or redis.call('ZCARD', KEYS[1]) < tonumber(ARGV[3]) then
  redis.call('ZADD', KEYS[1], now + tonumber(ARGV[2]), ARGV[1])
  redis.call('PEXPIRE', KEYS[1], tonumber(ARGV[4]))
  return 1
end
return 0
"""

_RELEASE_LEASE = """
local removed = redis.call('ZREM', KEYS[1], ARGV[1])
redis.call('ZREM', KEYS[2], ARGV[1])
redis.call('ZREM', KEYS[3], ARGV[1])
return removed
"""

_SNAPSHOT = _NOW + """
redis.call('ZREMRANGEBYSCORE', KEYS[1], '-inf', now)
return {redis.call('ZCARD', KEYS[1]), redis.call('ZCARD', KEYS[2])}
"""

_LOCK_RENEW = """
if redis.call('GET', KEYS[1]) == ARGV[1] then
  return redis.call('PEXPIRE', KEYS[1], tonumber(ARGV[2]))
end
return 0
"""

_LOCK_RELEASE = """
if redis.call('GET', KEYS[1]) == ARGV[1] then
  return redis.call('DEL', KEYS[1])
end
return 0
"""

_HIT_WINDOW = """
local n = redis.call('INCR', KEYS[1])
if n == 1 then redis.call('PEXPIRE', KEYS[1], tonumber(ARGV[1])) end
local ttl = redis.call('PTTL', KEYS[1])
if ttl < 0 then
  redis.call('PEXPIRE', KEYS[1], tonumber(ARGV[1]))
  ttl = tonumber(ARGV[1])
end
return {n, ttl}
"""


class RedisCoordination:
    """Redis 实现：所有计数与队列变更都在单个 Lua 脚本内完成。"""

    def __init__(self, client: Any) -> None:
        self._client = client
        self._scripts = {
            name: self._client.register_script(src)
            for name, src in {
                "admit": _ADMIT, "renew": _RENEW_LEASE, "release": _RELEASE_LEASE,
                "snapshot": _SNAPSHOT, "lock_renew": _LOCK_RENEW,
                "lock_release": _LOCK_RELEASE, "hit": _HIT_WINDOW,
            }.items()
        }

    @classmethod
    def from_url(cls, url: str, password: Optional[str]) -> "RedisCoordination":
        import redis.asyncio as aioredis

        # 决策：短超时 + 有界连接池，Redis 卡顿时快速失败并拒绝请求，而不是拖住事件循环。
        return cls(aioredis.from_url(
            url,
            password=password or None,
            decode_responses=True,
            socket_connect_timeout=2,
            socket_timeout=2,
            health_check_interval=30,
            max_connections=20,
        ))

    async def _run(self, name: str, keys: list[str], args: list[Any]) -> Any:
        try:
            return await self._scripts[name](keys=keys, args=args)
        except Exception as exc:
            raise CoordinationUnavailable(f"redis script {name} failed: {type(exc).__name__}") from exc

    async def _call(self, method: str, *args: Any, **kwargs: Any) -> Any:
        try:
            return await getattr(self._client, method)(*args, **kwargs)
        except Exception as exc:
            raise CoordinationUnavailable(f"redis {method} failed: {type(exc).__name__}") from exc

    async def admit(self, member: str, lease_ms: int, max_active: int, max_queue: int, heartbeat_ms: int) -> tuple[int, int]:
        status, position = await self._run(
            "admit", [ACTIVE_KEY, WAIT_KEY, HEARTBEAT_KEY],
            [member, lease_ms, max_active, max_queue, heartbeat_ms, _IDLE_EXPIRE_MS],
        )
        return int(status), int(position)

    async def renew_lease(self, member: str, lease_ms: int, max_active: int) -> bool:
        return bool(await self._run("renew", [ACTIVE_KEY], [member, lease_ms, max_active, _IDLE_EXPIRE_MS]))

    async def release_lease(self, member: str) -> bool:
        return bool(await self._run("release", [ACTIVE_KEY, WAIT_KEY, HEARTBEAT_KEY], [member]))

    async def capacity_snapshot(self) -> tuple[int, int]:
        active, waiting = await self._run("snapshot", [ACTIVE_KEY, WAIT_KEY], [])
        return int(active), int(waiting)

    async def lock_acquire(self, key: str, token: str, ttl_ms: int) -> bool:
        return bool(await self._call("set", key, token, nx=True, px=ttl_ms))

    async def lock_renew(self, key: str, token: str, ttl_ms: int) -> bool:
        return bool(await self._run("lock_renew", [key], [token, ttl_ms]))

    async def lock_release(self, key: str, token: str) -> bool:
        return bool(await self._run("lock_release", [key], [token]))

    async def set_flag(self, key: str, ttl_ms: int) -> None:
        await self._call("set", key, "1", px=ttl_ms)

    async def has_flag(self, key: str) -> bool:
        return bool(await self._call("exists", key))

    async def delete(self, key: str) -> None:
        await self._call("delete", key)

    async def hit_window(self, key: str, window_ms: int) -> tuple[int, int]:
        count, ttl = await self._run("hit", [key], [window_ms])
        return int(count), int(ttl)

    async def get_json(self, key: str) -> Optional[dict]:
        raw = await self._call("get", key)
        return json.loads(raw) if raw else None

    async def set_json(self, key: str, value: dict, ttl_ms: int) -> None:
        await self._call("set", key, json.dumps(value, ensure_ascii=False, default=str), px=ttl_ms)

    async def close(self) -> None:
        await self._client.aclose()


class MemoryCoordination:
    """单进程内存实现：语义与 Redis 版一致；方法内无 await，事件循环下天然原子。"""

    def __init__(self) -> None:
        self.active: dict[str, float] = {}
        self.waiting: dict[str, float] = {}  # member -> 入队时间
        self.heartbeat: dict[str, float] = {}
        self.kv: dict[str, tuple[Any, float]] = {}  # key -> (value, 过期时间)
        self._seq = 0

    @staticmethod
    def _now() -> float:
        return time.monotonic() * 1000

    def _purge(self, now: float) -> None:
        for m in [m for m, exp in self.active.items() if exp <= now]:
            del self.active[m]
        for m in [m for m, exp in self.heartbeat.items() if exp <= now]:
            self.waiting.pop(m, None)
            self.heartbeat.pop(m, None)
        for k in [k for k, (_, exp) in self.kv.items() if exp <= now]:
            del self.kv[k]

    def _rank(self, member: str) -> Optional[int]:
        if member not in self.waiting:
            return None
        ordered = sorted(self.waiting.items(), key=lambda item: (item[1], item[0]))
        return [m for m, _ in ordered].index(member)

    async def admit(self, member: str, lease_ms: int, max_active: int, max_queue: int, heartbeat_ms: int) -> tuple[int, int]:
        now = self._now()
        self._purge(now)
        rank = self._rank(member)
        if rank is None:
            if len(self.waiting) >= max_queue and len(self.active) + len(self.waiting) >= max_active:
                return -1, 0
            self._seq += 1
            self.waiting[member] = now + self._seq * 1e-6
            rank = self._rank(member)
        if len(self.active) < max_active and rank < max_active - len(self.active):
            self.waiting.pop(member, None)
            self.heartbeat.pop(member, None)
            self.active[member] = now + lease_ms
            return 1, rank + 1
        self.heartbeat[member] = now + heartbeat_ms
        return 0, rank + 1

    async def renew_lease(self, member: str, lease_ms: int, max_active: int) -> bool:
        now = self._now()
        self._purge(now)
        if member in self.active or len(self.active) < max_active:
            self.active[member] = now + lease_ms
            return True
        return False

    async def release_lease(self, member: str) -> bool:
        self.waiting.pop(member, None)
        self.heartbeat.pop(member, None)
        return self.active.pop(member, None) is not None

    async def capacity_snapshot(self) -> tuple[int, int]:
        self._purge(self._now())
        return len(self.active), len(self.waiting)

    def _get(self, key: str) -> Any:
        item = self.kv.get(key)
        if item is None or item[1] <= self._now():
            self.kv.pop(key, None)
            return None
        return item[0]

    async def lock_acquire(self, key: str, token: str, ttl_ms: int) -> bool:
        if self._get(key) is not None:
            return False
        self.kv[key] = (token, self._now() + ttl_ms)
        return True

    async def lock_renew(self, key: str, token: str, ttl_ms: int) -> bool:
        if self._get(key) != token:
            return False
        self.kv[key] = (token, self._now() + ttl_ms)
        return True

    async def lock_release(self, key: str, token: str) -> bool:
        if self._get(key) != token:
            return False
        del self.kv[key]
        return True

    async def set_flag(self, key: str, ttl_ms: int) -> None:
        self.kv[key] = ("1", self._now() + ttl_ms)

    async def has_flag(self, key: str) -> bool:
        return self._get(key) is not None

    async def delete(self, key: str) -> None:
        self.kv.pop(key, None)

    async def hit_window(self, key: str, window_ms: int) -> tuple[int, int]:
        now = self._now()
        value = self._get(key)
        if value is None:
            self.kv[key] = (1, now + window_ms)
            return 1, window_ms
        expires = self.kv[key][1]
        self.kv[key] = (value + 1, expires)
        return value + 1, int(expires - now)

    async def get_json(self, key: str) -> Optional[dict]:
        raw = self._get(key)
        return json.loads(raw) if raw else None

    async def set_json(self, key: str, value: dict, ttl_ms: int) -> None:
        self.kv[key] = (json.dumps(value, ensure_ascii=False, default=str), self._now() + ttl_ms)

    async def close(self) -> None:
        return None


_backend: RedisCoordination | MemoryCoordination | None = None


def get_coordination() -> RedisCoordination | MemoryCoordination:
    """返回进程内协调后端单例（按 COORDINATION_BACKEND 选择）。"""
    global _backend
    if _backend is None:
        settings = get_settings()
        if settings.COORDINATION_BACKEND == "memory":
            logger.warning("COORDINATION_BACKEND=memory：容量与会话锁仅在本进程内生效，禁止多 worker 部署")
            _backend = MemoryCoordination()
        else:
            _backend = RedisCoordination.from_url(settings.REDIS_URL, settings.REDIS_PASSWORD)
    return _backend


def set_coordination(backend: RedisCoordination | MemoryCoordination | None) -> None:
    """替换后端（测试注入用）。"""
    global _backend
    _backend = backend


async def close_coordination() -> None:
    """应用关闭时释放连接池。"""
    global _backend
    if _backend is not None:
        await _backend.close()
        _backend = None
