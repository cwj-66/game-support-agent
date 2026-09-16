"""LangGraph AsyncSqliteSaver 状态持久化。"""

import logging
import os
from typing import Optional

import aiosqlite
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

logger = logging.getLogger(__name__)

_conn: Optional[aiosqlite.Connection] = None
_saver: Optional[AsyncSqliteSaver] = None


def _get_db_path() -> str:
    """获取 SQLite 检查点路径"""
    try:
        from app.core.config import get_settings

        return get_settings().DB_PATH
    except Exception:
        return "./data/game_support.db"


async def init_checkpointer() -> None:
    """初始化 AsyncSqliteSaver（应用启动时调用）"""
    global _conn, _saver
    if _saver is not None:
        return

    db_path = _get_db_path()
    parent = os.path.dirname(os.path.abspath(db_path))
    if parent:
        os.makedirs(parent, exist_ok=True)

    _conn = await aiosqlite.connect(db_path)
    # 允许多协程共用同一连接（FastAPI 异步场景）
    await _conn.execute("PRAGMA journal_mode=WAL;")
    _saver = AsyncSqliteSaver(_conn)
    await _saver.setup()
    logger.info("AsyncSqliteSaver initialized — Agent state in SQLite (%s)", db_path)


async def get_checkpointer() -> AsyncSqliteSaver:
    """获取 AsyncSqliteSaver（用于 async invoke / astream）"""
    if _saver is None:
        await init_checkpointer()
    return _saver


async def close_checkpointer() -> None:
    """关闭 SQLite 连接（应用关闭时调用）"""
    global _conn, _saver
    _saver = None
    if _conn is not None:
        await _conn.close()
        _conn = None
