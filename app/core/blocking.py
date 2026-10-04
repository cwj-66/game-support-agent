"""有界线程池：async 路径里的同步数据库调用统一走这里，避免阻塞事件循环。"""

from __future__ import annotations

import asyncio
import functools
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable, Optional, TypeVar

from app.core.config import get_settings

T = TypeVar("T")
_executor: Optional[ThreadPoolExecutor] = None


def _get_executor() -> ThreadPoolExecutor:
    global _executor
    if _executor is None:
        _executor = ThreadPoolExecutor(
            max_workers=get_settings().BLOCKING_POOL_SIZE, thread_name_prefix="gsa-blocking"
        )
    return _executor


async def run_blocking(fn: Callable[..., T], *args: Any, **kwargs: Any) -> T:
    """在有界线程池执行同步函数。

    决策：线程无法被强制中断；调用方被取消时仍等待线程结束再向上抛出取消，
    这样释放会话锁或容量名额时，对应的数据库操作确实已经结束（耗时受 MySQL 读写超时约束）。
    """
    loop = asyncio.get_running_loop()
    future = loop.run_in_executor(_get_executor(), functools.partial(fn, *args, **kwargs))
    try:
        return await asyncio.shield(future)
    except asyncio.CancelledError:
        while not future.done():
            try:
                await asyncio.wait({future})
            except asyncio.CancelledError:
                continue
        raise


def shutdown_blocking() -> None:
    global _executor
    if _executor is not None:
        _executor.shutdown(wait=True, cancel_futures=True)
        _executor = None
