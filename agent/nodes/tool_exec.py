"""
通用工具执行节点
读取 AIMessage.tool_calls，动态分发并执行对应工具
"""

import json
from datetime import datetime, timezone
from typing import Dict, Any

from langchain_core.messages import AIMessage, ToolMessage

from ..state import AgentState
from ..tools import get_all_tools


async def tool_exec_node(state: AgentState) -> Dict[str, Any]:
    """
    工具执行节点：通用分发器

    职责：
    1. 找到最后一条带 tool_calls 的 AIMessage
    2. 依次执行每个工具调用
    3. 将 ToolMessage 写回 messages
    4. 若工具是 query_knowledge，解析 JSON 更新 metadata.knowledge_result
    """
    messages = state.get("messages", [])

    # 找最后一条带 tool_calls 的 AIMessage
    last_ai: AIMessage | None = None
    for msg in reversed(messages):
        if isinstance(msg, AIMessage) and getattr(msg, "tool_calls", None):
            last_ai = msg
            break

    if not last_ai:
        return {}

    tools_map = {t.name: t for t in get_all_tools()}
    tool_messages = []
    tool_call_records = []
    metadata = state.get("metadata", {})

    for tc in last_ai.tool_calls:
        tool_name: str = tc["name"]
        tool_args: dict = tc["args"]
        tool_call_id: str = tc["id"]

        record = {
            "tool": tool_name,
            "input": tool_args,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "status": "started",
        }

        tool = tools_map.get(tool_name)
        if tool is None:
            record["status"] = "failed"
            record["error"] = f"未知工具：{tool_name}"
            tool_messages.append(ToolMessage(
                content=json.dumps({"error": f"未知工具：{tool_name}"}, ensure_ascii=False),
                name=tool_name,
                tool_call_id=tool_call_id,
            ))
            tool_call_records.append(record)
            continue

        try:
            result = await tool.ainvoke(tool_args)
            result_str = str(result)

            record["status"] = "completed"
            record["output"] = result_str

            # query_knowledge 返回 JSON，解析后存入 metadata
            if tool_name == "query_knowledge":
                try:
                    metadata["knowledge_result"] = json.loads(result_str)
                except (json.JSONDecodeError, ValueError):
                    pass

            tool_messages.append(ToolMessage(
                content=result_str,
                name=tool_name,
                tool_call_id=tool_call_id,
            ))

        except Exception as e:
            record["status"] = "failed"
            record["error"] = str(e)
            tool_messages.append(ToolMessage(
                content=json.dumps(
                    {"has_answer": False, "error": str(e)},
                    ensure_ascii=False,
                ),
                name=tool_name,
                tool_call_id=tool_call_id,
            ))

        tool_call_records.append(record)

    return {
        "messages": tool_messages,
        "tool_calls": state.get("tool_calls", []) + tool_call_records,
        "metadata": metadata,
    }
