"""
安全检测数据结构定义
"""

from typing import List, Dict, Any
from dataclasses import dataclass, field


@dataclass
class InterruptDecision:
    """
    中断决策结果

    由InterruptDetector生成，决定是否替换回复内容。

    Attributes:
        should_interrupt: 是否触发检测
        reason: 检测原因说明
        level: 风险等级 (low/medium/high)
        sensitive_words: 检测到的敏感词
    """
    should_interrupt: bool
    reason: str
    level: str = "low"
    sensitive_words: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "should_interrupt": self.should_interrupt,
            "reason": self.reason,
            "level": self.level,
            "sensitive_words": self.sensitive_words,
        }
