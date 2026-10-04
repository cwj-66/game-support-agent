"""MySQL 连接池（Mock 游戏用户 + 工单）：有上限、等待超时、取出时有效性检查。"""

from __future__ import annotations

import logging
import queue
import threading
import time
from contextlib import contextmanager
from typing import Iterator, Optional

import pymysql
from pymysql.cursors import DictCursor

from app.core.config import get_settings

logger = logging.getLogger(__name__)


class PoolTimeout(RuntimeError):
    """等待空闲连接超时"""


class MySQLPool:
    """线程安全的 PyMySQL 连接池。

    每次 with 取出独占连接，退出时提交或回滚后归还；连接与游标从不跨请求共享。
    """

    def __init__(self, max_size: int, timeout: float, recycle: int) -> None:
        self._max = max_size
        self._timeout = timeout
        self._recycle = recycle
        self._idle: "queue.LifoQueue[tuple[pymysql.connections.Connection, float]]" = queue.LifoQueue()
        self._slots = threading.BoundedSemaphore(max_size)

    @staticmethod
    def _connect() -> pymysql.connections.Connection:
        s = get_settings()
        return pymysql.connect(
            host=s.MYSQL_HOST,
            port=s.MYSQL_PORT,
            user=s.MYSQL_USER,
            password=s.MYSQL_PASSWORD,
            database=s.MYSQL_DATABASE,
            charset="utf8mb4",
            cursorclass=DictCursor,
            autocommit=False,
            connect_timeout=s.MYSQL_CONNECT_TIMEOUT_SECONDS,
            read_timeout=s.MYSQL_READ_TIMEOUT_SECONDS,
            write_timeout=s.MYSQL_READ_TIMEOUT_SECONDS,
        )

    def _checkout(self) -> tuple[pymysql.connections.Connection, float]:
        while True:
            try:
                conn, created = self._idle.get_nowait()
            except queue.Empty:
                return self._connect(), time.monotonic()
            if time.monotonic() - created > self._recycle:
                self._discard(conn)
                continue
            try:
                conn.ping(reconnect=False)
                return conn, created
            except Exception:
                self._discard(conn)

    @staticmethod
    def _discard(conn: pymysql.connections.Connection) -> None:
        try:
            conn.close()
        except Exception:
            pass

    @contextmanager
    def connection(self) -> Iterator[pymysql.connections.Connection]:
        if not self._slots.acquire(timeout=self._timeout):
            raise PoolTimeout("MySQL pool exhausted")
        conn: Optional[pymysql.connections.Connection] = None
        try:
            conn, created = self._checkout()
            try:
                yield conn
                conn.commit()
            except BaseException:
                try:
                    conn.rollback()
                except Exception:
                    self._discard(conn)
                    conn = None
                raise
            if conn is not None:
                self._idle.put((conn, created))
                conn = None
        finally:
            if conn is not None:
                self._discard(conn)
            self._slots.release()

    def close(self) -> None:
        while True:
            try:
                conn, _ = self._idle.get_nowait()
            except queue.Empty:
                return
            self._discard(conn)


_pool: Optional[MySQLPool] = None
_pool_lock = threading.Lock()


def get_pool() -> MySQLPool:
    global _pool
    if _pool is None:
        with _pool_lock:
            if _pool is None:
                s = get_settings()
                _pool = MySQLPool(s.MYSQL_POOL_SIZE, s.MYSQL_POOL_TIMEOUT_SECONDS, s.MYSQL_POOL_RECYCLE_SECONDS)
    return _pool


@contextmanager
def get_mysql_conn() -> Iterator[pymysql.connections.Connection]:
    """获取池化 MySQL 连接（上下文管理器，自动提交/回滚并归还）"""
    with get_pool().connection() as conn:
        yield conn


def close_pool() -> None:
    global _pool
    if _pool is not None:
        _pool.close()
        _pool = None


def ping_mysql() -> bool:
    """检查 MySQL 是否可用"""
    try:
        with get_mysql_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
        return True
    except Exception:
        return False
