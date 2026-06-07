"""
中断检测节点
检查最终回复是否包含敏感词或工具调用失败，直接处理不再触发人工审核
"""

from typing import Dict, Any

from langchain_core.messages import AIMessage

from ..state import AgentState
from safety.detector import get_default_detector


async def detector_node(state: AgentState) -> Dict[str, Any]:
    """
    中断检测节点

    最后一道安全防线，在 generate 之后运行：
    1. 敏感词检测 → 替换回复为违规警告，不触发中断
    2. 工具调用失败检测 → 替换回复为道歉+询问是否转人工，不触发中断
    3. 两者都无 → 透传原回复
    """
    final_response = state.get("final_response", "")
    metadata = dict(state.get("metadata", {}))

    detector = get_default_detector()
    decision = detector.detect(
        content=final_response,
        metadata=metadata,
    )

    # 未触发任何检测 → 透传
    if not decision.should_interrupt:
        return {
            "interrupt_info": None,
            "node_trace": ["detector"],
        }

    # ── 敏感词命中 ─────────────────────────────────────────────
    if decision.sensitive_words:
        warning = "抱歉，您的请求涉及违规内容，请遵守游戏社区规范。"
        metadata["detector_intercepted"] = {
            "type": "sensitive",
            "words": decision.sensitive_words,
            "original_response": final_response,
        }
        return {
            "final_response": warning,
            "messages": [AIMessage(content=warning)],
            "interrupt_info": None,
            "metadata": metadata,
            "node_trace": ["detector"],
        }

    # ── 工具调用失败 ───────────────────────────────────────────
    apology = "抱歉，我暂时无法完成您的请求。是否需要为您转接人工客服？"
    metadata["detector_intercepted"] = {
        "type": "tool_failure",
        "reason": decision.reason,
        "original_response": final_response,
    }
    return {
        "final_response": apology,
        "messages": [AIMessage(content=apology)],
        "interrupt_info": None,
        "metadata": metadata,
        "node_trace": ["detector"],
    }
