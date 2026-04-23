"""
LangGraph 状态持久化配置
使用 MemorySaver 作为开发/测试环境的checkpointer
生产环境可替换为 RedisSaver 或 PostgresSaver
"""

from langgraph.checkpoint.memory import MemorySaver
from typing import Optional


# 全局checkpointer实例
_checkpoint_saver: Optional[MemorySaver] = None


def get_checkpointer() -> MemorySaver:
    """
    获取或创建 MemorySaver 实例
    
    MemorySaver将Agent状态保存在内存中，支持：
    1. 断点恢复：从任意节点重新开始
    2. 状态回滚：查看历史状态
    3. 并发隔离：不同session_id互不干扰
    
    TODO: 生产环境替换为持久化存储
    """
    global _checkpoint_saver
    if _checkpoint_saver is None:
        _checkpoint_saver = MemorySaver()
    return _checkpoint_saver


def reset_checkpointer():
    """
    重置checkpointer（主要用于测试）
    
    警告：这会清除所有存储的状态！
    """
    global _checkpoint_saver
    _checkpoint_saver = None


# TODO: Redis持久化实现（生产环境）
# class RedisCheckpointSaver(BaseCheckpointSaver):
#     """基于Redis的状态持久化"""
#     def __init__(self, redis_url: str):
#         self.redis = redis.from_url(redis_url)
#     
#     async def aget(self, config: RunnableConfig) -> Optional[Checkpoint]:
#         # 从Redis读取状态
#         pass
#     
#     async def aput(self, config: RunnableConfig, checkpoint: Checkpoint) -> None:
#         # 写入Redis
#         pass


# TODO: Postgres持久化实现
# class PostgresCheckpointSaver(BaseCheckpointSaver):
#     """基于PostgreSQL的状态持久化，支持复杂查询"""
#     pass
