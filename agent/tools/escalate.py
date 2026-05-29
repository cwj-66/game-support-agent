"""
转人工工具 + 升等检测器

两路触发机制：
1. LLM 主动调用 escalate_to_human → tool_exec_node 直接设 interrupt_info → route 到 human
2. 轮次达到上限（默认10轮）→ tool_exec_node 跑 check_batch() 兜底检测：
   - 超限 + 工具执行失败 → should_interrupt=True，升等转人工
   - 仅超限无失败 → should_interrupt=False，tool_exec 自动建工单 + 优雅降级回复
"""

import json
from typing import Any, Dict, List, Optional

from langchain_core.tools import tool

from human_in_loop.schema import InterruptDecision


# ============ 升等检测器 ============

class EscalateDetector:
    """升等检测器：轮次到上限时做兜底检测，区分"仅超限"和"超限+工具失败"两种场景"""

    def __init__(self, max_react_rounds: int = 10, rag_confidence_threshold: float = 0.5):
        self.max_react_rounds = max_react_rounds
        self.rag_confidence_threshold = rag_confidence_threshold

    def check_batch(
        self,
        tool_call_records: List[Dict[str, Any]],
        react_round: int = 1,
    ) -> InterruptDecision:
        """对一批工具执行结果做兜底检测（由 tool_exec_node 在轮次达上限时调用）

        返回逻辑：
        - 超限 + 存在 tool status=failed → should_interrupt=True，升等转人工
        - 仅超限无失败 → should_interrupt=False，tool_exec 自动建工单 + 优雅降级
        """
        reasons: List[str] = []
        level = "low"
        has_failures = False

        # 1. ReAct 轮次超限
        if react_round >= self.max_react_rounds:
            reasons.append(f"超过最大尝试次数（{self.max_react_rounds}轮），仍未找到有效答案")
            level = "medium"

        # 2. 遍历所有工具记录，检查是否有工具执行失败
        for record in tool_call_records:
            tool_name = record.get("tool", "")
            status = record.get("status", "")

            if status == "failed":
                has_failures = True
                reasons.append(f"工具 {tool_name} 执行失败: {record.get('error', '未知错误')}")
                level = "high"
                continue

            if status != "completed":
                continue

            result_str = record.get("output", "")
            try:
                result_data = json.loads(result_str)
            except (json.JSONDecodeError, ValueError):
                has_failures = True
                reasons.append(f"工具 {tool_name} 返回格式异常")
                level = "high"
                continue

            health = result_data.get("_health", {})
            if not health:
                continue

            if not health.get("ok", True):
                has_failures = True
                reasons.append(health.get("message", f"工具 {tool_name} 执行异常"))
                if level not in ("medium", "high"):
                    level = "medium"

        # 仅当超限且有工具失败时才中断升等；仅超限则记录原因但不中断
        has_timeout = react_round >= self.max_react_rounds
        should_interrupt = has_timeout and has_failures

        return InterruptDecision(
            should_interrupt=should_interrupt,
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
    """将对话移交人工客服。仅在用户明确说"转人工""叫人工""找客服"等指令时调用。

    注意（按优先级）：
    1. 用户明确要求人工 → 直接调用此工具
    2. 用户情绪激动/不满 → 先回复询问"需要我为您转接人工客服吗？"，
       待用户确认后再调用。不要直接升人工。
    3. 账号封禁申诉、支付/退款问题等后台可异步处理的场景，
       应调用 create_ticket 创建工单，不触发此工具。
       若确需升人工，必须先调 create_ticket 再调本工具，
       并在 reason 中包含工单号。

    重要：若已创建工单，reason 中须包含工单号（TK-xxxx），方便客服交接。

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
