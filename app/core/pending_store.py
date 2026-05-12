"""
Human-in-loop 挂起状态存储

中断发生时 chat 端写入，human 端读取和清除。
当前为内存实现，重启丢失；生产环境替换为 Redis。
"""

from typing import Optional


# session_id → interrupt payload
_pending: dict[str, dict] = {}


def add_pending(session_id: str, payload: dict) -> None:
    """记录一个等待人工审核的会话"""
    _pending[session_id] = payload


def remove_pending(session_id: str) -> Optional[dict]:
    """审核完成，移除并返回中断载荷"""
    return _pending.pop(session_id, None)


def get_pending(session_id: str) -> Optional[dict]:
    """查询某个会话是否在等待审核"""
    return _pending.get(session_id)


def get_all_pending() -> dict[str, dict]:
    """获取所有等待审核的会话"""
    return dict(_pending)
