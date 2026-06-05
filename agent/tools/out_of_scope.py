"""超出能力范围汇报工具"""

import json
from langchain_core.tools import tool


@tool
def report_out_of_scope(reason: str) -> str:
    """当没有合适的工具处理用户请求时调用此工具。

    当**确认**遍历了所有可用工具后，仍没有任何工具能处理用户的请求时
    （例如催单、加急、给好评、反馈建议等），调用此工具向系统报告。
    注意：不要滥用，有合适工具时优先用工具。

    Args:
        reason: 说明用户的请求内容和为什么没有可用工具处理
    """
    return json.dumps({
        "_health": {"ok": True, "confidence": 0.0},
        "status": "out_of_scope",
        "reason": reason,
        "message": f"当前系统无法处理此请求。请如实告知用户，并询问是否需要创建工单。",
    }, ensure_ascii=False)
