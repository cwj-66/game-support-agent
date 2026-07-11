"""
MySQL 连接工具（Mock 游戏用户 + 工单）

数据文件不在项目目录里，由 Docker 卷 mysql-data 持久化。
初始化脚本：scripts/mysql/init.sql
"""

from contextlib import contextmanager
from typing import Iterator

import pymysql
from pymysql.cursors import DictCursor

from app.core.config import get_settings


@contextmanager
def get_mysql_conn() -> Iterator[pymysql.connections.Connection]:
    """获取 MySQL 连接（上下文管理器，自动提交/回滚）"""
    settings = get_settings()
    conn = pymysql.connect(
        host=settings.MYSQL_HOST,
        port=settings.MYSQL_PORT,
        user=settings.MYSQL_USER,
        password=settings.MYSQL_PASSWORD,
        database=settings.MYSQL_DATABASE,
        charset="utf8mb4",
        cursorclass=DictCursor,
        autocommit=False,
    )
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def ping_mysql() -> bool:
    """检查 MySQL 是否可用"""
    try:
        with get_mysql_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
        return True
    except Exception:
        return False
