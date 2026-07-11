"""
结束节点
记录最终状态
"""

from datetime import datetime, timezone
from typing import Dict, Any

from ..state import AgentState


async def finish_node(state: AgentState) -> Dict[str, Any]:
    """结束节点：标记完成时间，清理运行时标记"""
    metadata = dict(state.get("metadata", {}))
    metadata.pop("tool_repeated_call", None)
    metadata["completed"] = True
    metadata["finished_at"] = datetime.now(timezone.utc).isoformat()

    return {
        "metadata": metadata,
        "node_trace": ["finish"],
    }
