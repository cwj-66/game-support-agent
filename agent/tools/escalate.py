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

    def __init__(self, max_react_rounds: int = 10, rag_confidence_threshold: float = 0.5):
        self.max_react_rounds = max_react_rounds
        self.rag_confidence_threshold = rag_confidence_threshold

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

            # RAG 检索相关性过低 → LLM 可能基于不靠谱资料产生幻觉
            rag_confidence = health.get("confidence")
            if rag_confidence is not None and rag_confidence < self.rag_confidence_threshold:
                reasons.append(f"工具 {tool_name} 检索相关性 {rag_confidence:.2f} 低于阈值 {self.rag_confidence_threshold}")
                level = "high"

        return InterruptDecision(
            should_interrupt=len(reasons) > 0,
            reason="; ".join(reasons) if reasons else "未触发中断",
            level=level,
            sensitive_words=[],
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
    """将对话移交人工客服。仅在以下情况调用，不要作为首选：
    - query_knowledge 查询无结果或置信度过低，无法回答问题
    - 用户明确要求执行需要人工权限的操作（如实际解封账号、退款打款、身份核实）
    - 用户多次表达不满或情绪激动，需要人工安抚
    - 多轮尝试后仍无法给出可信答复

    注意：涉及封号、退款等话题时，应先调 query_knowledge 查询处理流程和规则告知用户。
    只有在知识库无法解答、或用户要求实际执行操作时才调此工具。

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
