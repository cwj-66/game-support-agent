"""
LangGraph 状态持久化配置

提供两种 checkpointer：
- AsyncSqliteSaver：用于异步 invoke/astream（run_agent、stream_agent）
- SqliteSaver（同步）：用于 Command(resume=...) 恢复（submit_review），
  因为 LangGraph 的 resume 路径内部使用同步方法调用 checkpointer。

生产环境可替换为 RedisSaver 或 PostgresSaver
"""

import os
import sqlite3
from typing import Optional

import aiosqlite
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.checkpoint.sqlite import SqliteSaver


# 数据库文件路径（与 app.core.database 共享）
# 默认在项目 data 目录下
_DB_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data",
    "game_support.db",
)


def _get_db_path() -> str:
    """获取数据库文件路径，优先从配置读取"""
    try:
        from app.core.config import get_settings

        return get_settings().DB_PATH
    except Exception:
        return _DB_PATH


# 全局 checkpointer 实例（异步）
_checkpoint_saver: Optional[AsyncSqliteSaver] = None
_connection: Optional[aiosqlite.Connection] = None

# 全局 checkpointer 实例（同步，用于 resume）
_sync_checkpointer: Optional[SqliteSaver] = None
_sync_connection: Optional[sqlite3.Connection] = None


async def get_checkpointer() -> AsyncSqliteSaver:
    """
    获取或创建 AsyncSqliteSaver 实例

    AsyncSqliteSaver 将 Agent 状态持久化到 SQLite 文件，支持：
    1. 断点恢复：服务重启后仍可恢复中断的会话
    2. 状态回滚：查看历史状态
    3. 并发隔离：不同 session_id 互不干扰
    """
    global _checkpoint_saver, _connection

    if _checkpoint_saver is None:
        db_path = _get_db_path()

        # 确保 data 目录存在
        os.makedirs(os.path.dirname(db_path), exist_ok=True)

        _connection = await aiosqlite.connect(db_path)
        _checkpoint_saver = AsyncSqliteSaver(_connection)

    return _checkpoint_saver


def get_sync_checkpointer() -> SqliteSaver:
    """
    获取或创建同步 SqliteSaver 实例

    LangGraph 的 Command(resume=...) 恢复路径内部使用同步方法调用
    checkpointer，因此需要同步 saver。
    """
    global _sync_checkpointer, _sync_connection

    if _sync_checkpointer is None:
        db_path = _get_db_path()
        os.makedirs(os.path.dirname(db_path), exist_ok=True)

        _sync_connection = sqlite3.connect(db_path, check_same_thread=False)
        _sync_checkpointer = SqliteSaver(_sync_connection)

    return _sync_checkpointer


async def reset_checkpointer():
    """
    重置 checkpointer（主要用于测试）

    警告：这会清除所有持久化状态！
    """
    global _checkpoint_saver, _connection, _sync_checkpointer, _sync_connection

    if _connection:
        await _connection.close()
        _connection = None
    _checkpoint_saver = None

    if _sync_connection:
        _sync_connection.close()
        _sync_connection = None
    _sync_checkpointer = None
