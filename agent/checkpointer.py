"""
LangGraph 状态持久化配置
使用 AsyncSqliteSaver 持久化 Agent 状态到 SQLite 文件
与工单数据库共用同一个 SQLite 文件

生产环境可替换为 RedisSaver 或 PostgresSaver
"""

import os
from typing import Optional

import aiosqlite
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver


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


# 全局 checkpointer 实例
_checkpoint_saver: Optional[AsyncSqliteSaver] = None
_connection: Optional[aiosqlite.Connection] = None


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


async def reset_checkpointer():
    """
    重置 checkpointer（主要用于测试）

    警告：这会清除所有持久化状态！
    """
    global _checkpoint_saver, _connection

    if _connection:
        await _connection.close()
        _connection = None
    _checkpoint_saver = None
