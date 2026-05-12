"""
Human-in-loop 模块

核心功能：
- detector: 中断触发检测（敏感词+置信度）
- reviewer: 人工审核操作（APPROVE/MODIFY/OVERRIDE）
- auditor: 审计链记录
- schema: 数据结构定义
- 升等检测逻辑已合并到 agent/tools/escalate.py

使用示例：
    from human_in_loop import InterruptDetector, HumanReviewer
    
    detector = InterruptDetector()
    decision = detector.detect(content, confidence)
    
    if decision.should_interrupt:
        # 进入人工审核流程
        pass
"""

from .detector import InterruptDetector, InterruptDecision
from .reviewer import HumanReviewer, ReviewActionType, ReviewContext
from .auditor import AuditLogger, get_audit_logger
from .schema import (
    InterruptDecision as InterruptDecisionDataclass,
    ReviewOperation,
    AuditLogEntry,
    PendingTask
)

__all__ = [
    # 检测器
    "InterruptDetector",
    "InterruptDecision",
    "InterruptDecisionDataclass",
    
    # 升等检测器（已迁移至 agent.tools.escalate）

    # 审核器
    "HumanReviewer",
    "ReviewActionType",
    "ReviewContext",
    "ReviewOperation",
    
    # 审计
    "AuditLogger",
    "get_audit_logger",
    "AuditLogEntry",
    
    # 其他
    "PendingTask",
]
