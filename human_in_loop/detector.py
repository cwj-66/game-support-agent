"""
中断触发判断模块
实现InterruptDetector类，包含敏感词匹配和置信度双重过滤
"""

import re
from typing import List, Optional, Dict, Any
from .schema import InterruptDecision


class InterruptDetector:
    """
    中断检测器（安全兜底层）

    职责：
    1. 检测 LLM 回复是否含违禁内容（越狱、涉黄、涉政、诱导等）
    2. LLM 置信度评分低于阈值判断
    3. 返回结构化的 InterruptDecision

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
        confidence_threshold: float = 0.6,
        case_sensitive: bool = False
    ):
        """
        初始化检测器

        Args:
            sensitive_words: 违禁词列表，默认使用内置列表
            confidence_threshold: 置信度阈值（0-1）
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
        self.confidence_threshold = confidence_threshold
        self.case_sensitive = case_sensitive
        
        # 编译敏感词正则（优化匹配性能）
        self._compile_patterns()
    
    def _compile_patterns(self):
        """预编译敏感词正则表达式"""
        self._patterns = []
        flags = 0 if self.case_sensitive else re.IGNORECASE
        
        for word in self.sensitive_words:
            # 使用单词边界避免误匹配（如"投诉"不匹配"投诉讼"）
            pattern = re.compile(re.escape(word), flags)
            self._patterns.append((word, pattern))
    
    def detect(
        self,
        content: str,
        confidence: Optional[float] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> InterruptDecision:
        """
        执行中断检测
        
        同时检查敏感词和置信度，任一触发即中断
        
        Args:
            content: 需要检测的内容（Agent回复或用户问题）
            confidence: LLM置信度分数（0-1）
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
        
        # 2. 置信度检测
        confidence_triggered = False
        if confidence is not None and confidence < self.confidence_threshold:
            confidence_triggered = True
            reasons.append(f"置信度 {confidence:.2f} 低于阈值 {self.confidence_threshold}")
        
        # 3. 工具调用失败检测（与 EscalateDetector 互补，最终防线）
        tool_failed = False
        if metadata and metadata.get("tool_calls"):
            tool_calls = metadata["tool_calls"]
            if any(tc.get("status") == "failed" for tc in tool_calls):
                reasons.append("工具调用失败")
                tool_failed = True

        # 确定是否中断
        should_interrupt = len(detected_words) > 0 or confidence_triggered or tool_failed

        # 确定风险等级
        if detected_words:
            level = "high"      # 敏感词 → 高风险
        elif tool_failed:
            level = "medium"    # 工具失败 → 中风险
        elif confidence_triggered:
            level = "medium"    # 置信度低 → 中风险
        else:
            level = "low"
        
        return InterruptDecision(
            should_interrupt=should_interrupt,
            reason="; ".join(reasons) if reasons else "未触发中断",
            level=level,
            sensitive_words=detected_words,
            confidence=confidence
        )
    
    def update_sensitive_words(self, words: List[str]):
        """
        更新敏感词列表
        
        Args:
            words: 新的敏感词列表
        """
        self.sensitive_words = words
        self._compile_patterns()
    
    def add_sensitive_word(self, word: str):
        """添加单个敏感词"""
        if word not in self.sensitive_words:
            self.sensitive_words.append(word)
            self._compile_patterns()
    
    def remove_sensitive_word(self, word: str):
        """移除敏感词"""
        if word in self.sensitive_words:
            self.sensitive_words.remove(word)
            self._compile_patterns()


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
