"""
转人工工具 + 升等检测器

两路触发机制：
1. LLM 主动调用 escalate_to_human → tool_exec_node 直接设 interrupt_info → route 到 human
2. 轮次达到上限（默认10轮）→ tool_exec_node 跑 check_batch() 兜底拉闸
"""

import json
from typing import Any, Dict, List, Optional

from langchain_core.tools import tool

from human_in_loop.schema import InterruptDecision


# ============ 升等检测器 ============

class EscalateDetector:
    """升等检测器：轮次到上限时做兜底检测，判断工具执行结果是否需要转人工"""

    def __init__(self, max_react_rounds: int = 10, confidence_threshold: float = 0.6):
        self.max_react_rounds = max_react_rounds
        self.confidence_threshold = confidence_threshold

    def check_batch(
        self,
        tool_call_records: List[Dict[str, Any]],
        react_round: int = 1,
    ) -> InterruptDecision:
        """对一批工具执行结果做兜底升等检测（由 tool_exec_node 在轮次达上限时调用）"""
        reasons: List[str] = []
        level = "low"

        # 1. ReAct 轮次超限
        if react_round >= self.max_react_rounds:
            reasons.append(f"超过最大尝试次数（{self.max_react_rounds}轮），仍未找到有效答案")
            level = "medium"

        # 2. 遍历所有工具记录（通用检测，依赖工具返回的 _health 字段）
        for record in tool_call_records:
            tool_name = record.get("tool", "")
            status = record.get("status", "")

            if status == "failed":
                reasons.append(f"工具 {tool_name} 执行失败: {record.get('error', '未知错误')}")
                level = "high"
                continue

            if status != "completed":
                continue

            result_str = record.get("output", "")
            try:
                result_data = json.loads(result_str)
            except (json.JSONDecodeError, ValueError):
                reasons.append(f"工具 {tool_name} 返回格式异常")
                level = "high"
                continue

            health = result_data.get("_health", {})
            if not health:
                continue

            if not health.get("ok", True):
                reasons.append(health.get("message", f"工具 {tool_name} 执行异常"))
                if level not in ("medium", "high"):
                    level = "medium"

            confidence = health.get("confidence")
            if confidence is not None and confidence < self.confidence_threshold:
                reasons.append(f"工具 {tool_name} 置信度 {confidence:.2f} 过低")
                level = "high"

        return InterruptDecision(
            should_interrupt=len(reasons) > 0,
            reason="; ".join(reasons) if reasons else "未触发中断",
            level=level,
            sensitive_words=[],
            confidence=None,
        )


# 单例
_default_escalate_detector: Optional[EscalateDetector] = None


def get_default_escalate_detector() -> EscalateDetector:
    global _default_escalate_detector
    if _default_escalate_detector is None:
        _default_escalate_detector = EscalateDetector()
    return _default_escalate_detector


# ============ LangChain 工具 ============

@tool
def escalate_to_human(reason: str) -> str:
    """当遇到以下情况时调用此工具，将对话移交人工客服：
    - 用户涉及账号封禁、实名认证、退款等敏感操作
    - 工具查询无结果或执行失败，无法回答问题
    - 知识库中找不到相关信息
    - 多次尝试后仍无法给出可信答复
    - 用户情绪激动或多次表达不满

    Args:
        reason: 具体说明为何需要人工介入，客服将直接看到此内容
    """
    return json.dumps({
        "_health": {"ok": False, "confidence": None, "message": reason},
        "should_interrupt": True,
        "reason": reason,
        "level": "high",
        "source": "llm_escalate",
    }, ensure_ascii=False)
