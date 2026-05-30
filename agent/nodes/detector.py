"""
中断检测节点
检查最终回复是否包含敏感词，决定是否触发人工审核
"""

from typing import Dict, Any

from ..state import AgentState
from human_in_loop.detector import get_default_detector


async def detector_node(state: AgentState) -> Dict[str, Any]:
    """
    中断检测节点

    最后一道安全防线，在 generate 之后运行：
    1. 敏感词检测
    2. 工具调用失败检测
    """
    final_response = state.get("final_response", "")
    metadata = state.get("metadata", {})

    detector = get_default_detector()
    decision = detector.detect(
        content=final_response,
        metadata=metadata,
    )

    return {
        "interrupt_info": {
            "should_interrupt": decision.should_interrupt,
            "reason": decision.reason,
            "level": decision.level,
            "sensitive_words": decision.sensitive_words,
            "pending_content": final_response,
            "source": "detector",
        } if decision.should_interrupt else None,
        "node_trace": ["detector"],
    }
