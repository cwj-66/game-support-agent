"""
安全检测模块
实现InterruptDetector类，包含敏感词匹配和工具失败检测
"""

import re
from typing import List, Optional, Dict, Any
from .schema import InterruptDecision


class InterruptDetector:
    """安全检测（内容兜底层）

    职责：
    1. 检测 LLM 回复是否含违禁内容（越狱、涉黄、涉政、诱导等）
    2. 工具调用失败检测

    注意：
    - 此检测器不负责业务判断（封号/退款等由 LLM 主动调用 escalate_to_human 处理）
    - 只拦截 LLM 被诱导输出的违禁/有害内容

    TODO:
    - 实现更复杂的语义敏感内容检测
    - 添加基于用户行为模式的异常检测
    """

    def __init__(
        self,
        sensitive_words: Optional[List[str]] = None,
        case_sensitive: bool = False
    ):
        """
        初始化检测器

        Args:
            sensitive_words: 违禁词列表，默认使用内置列表
            case_sensitive: 是否区分大小写
        """
        self.sensitive_words = sensitive_words or [
            # 诱导私下交易/泄露隐私
            "私下转账", "加我微信", "私聊我", "内部渠道", "私下解决",
            # 冒充官方身份
            "我是腾讯官方", "我是客服主管", "我是系统管理员", "绕过系统",
            # 涉黄
            "色情", "裸体", "性交", "卖淫", "嫖娼",
            # 暴力/自伤
            "如何自杀", "如何自残", "制作炸弹", "如何伤害",
            # 涉政（根据业务合规要求）
            "法轮功", "分裂国家", "推翻政府",
        ]
        self.case_sensitive = case_sensitive

        self._compile_patterns()

    def _compile_patterns(self):
        """预编译敏感词正则表达式"""
        self._patterns = []
        flags = 0 if self.case_sensitive else re.IGNORECASE

        for word in self.sensitive_words:
            pattern = re.compile(re.escape(word), flags)
            self._patterns.append((word, pattern))

    def detect(
        self,
        content: str,
        metadata: Optional[Dict[str, Any]] = None
    ) -> InterruptDecision:
        """
        执行中断检测

        检查敏感词和工具调用失败

        Args:
            content: 需要检测的内容（Agent回复或用户问题）
            metadata: 额外元数据，如工具调用结果

        Returns:
            InterruptDecision: 中断决策结果
        """
        detected_words = []
        reasons = []

        # 1. 敏感词检测
        for word, pattern in self._patterns:
            if pattern.search(content):
                detected_words.append(word)

        if detected_words:
            reasons.append(f"检测到敏感词: {', '.join(detected_words)}")

        # 2. 工具调用失败检测
        tool_failed = False
        if metadata and metadata.get("tool_calls"):
            tool_calls = metadata["tool_calls"]
            if any(tc.get("status") == "failed" for tc in tool_calls):
                reasons.append("工具调用失败")
                tool_failed = True

        # 确定是否中断
        should_interrupt = len(detected_words) > 0 or tool_failed

        # 确定风险等级
        if detected_words:
            level = "high"      # 敏感词 → 高风险
        elif tool_failed:
            level = "medium"    # 工具失败 → 中风险
        else:
            level = "low"

        return InterruptDecision(
            should_interrupt=should_interrupt,
            reason="; ".join(reasons) if reasons else "未触发中断",
            level=level,
            sensitive_words=detected_words,
        )


# 默认检测器实例（单例模式）
_default_detector: Optional[InterruptDetector] = None


def get_default_detector() -> InterruptDetector:
    """获取默认检测器实例"""
    global _default_detector
    if _default_detector is None:
        _default_detector = InterruptDetector()
    return _default_detector


# TODO: 未来扩展
# - 实现基于NLP的语义敏感内容检测
# - 添加用户行为模式分析（如频繁投诉记录）
# - 实现动态阈值调整（基于历史审核数据）
