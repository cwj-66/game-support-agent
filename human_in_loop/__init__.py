"""
Human-in-loop 模块

核心功能：
- detector: 中断触发检测（敏感词+工具失败）
- schema: 数据结构定义
"""

from .detector import InterruptDetector, InterruptDecision

__all__ = [
    "InterruptDetector",
    "InterruptDecision",
]
