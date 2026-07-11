"""
通用工具执行节点
读取 AIMessage.tool_calls，动态分发并执行对应工具

兜底策略：
轮次达上限 → 注入系统提示，让 LLM 基于已有信息生成最终回复
"""

import json
from datetime import datetime, timezone
from typing import Dict, Any, List

from langchain_core.messages import AIMessage, ToolMessage

from ..state import AgentState
from ..tools import get_all_tools, simplify_tool_context

# 最大 ReAct 轮次，超限后不再执行新工具调用
MAX_REACT_ROUNDS = 5


async def tool_exec_node(state: AgentState) -> Dict[str, Any]:
    """
    工具执行节点：通用分发器

    职责：
    1. 找到最后一条带 tool_calls 的 AIMessage
    2. 依次执行每个工具调用
    3. 将 ToolMessage 写回 messages
    """
    messages = state.get("messages", [])

    # 找最后一条带 tool_calls 的 AIMessage
    last_ai: AIMessage | None = None
    for msg in reversed(messages):
        if isinstance(msg, AIMessage) and getattr(msg, "tool_calls", None):
            last_ai = msg
            break

    if not last_ai:
        return {"node_trace": ["tool_exec"]}

    tools_map = {t.name: t for t in get_all_tools(state.get("user_id", ""))}
    tool_messages: List[ToolMessage] = []
    tool_call_records: List[Dict[str, Any]] = []
    metadata = state.get("metadata", {})

    # 计算已执行的 ReAct 轮次
    prev_tool_calls = state.get("tool_calls", [])
    current_round = len(prev_tool_calls) + 1

    # 超限 → 不执行工具，注入指导信息让 LLM 基于已有上下文生成最终回复
    if current_round >= MAX_REACT_ROUNDS:
        metadata["max_rounds_reached"] = True
        return {
            "messages": [ToolMessage(
                content="已到最大查询轮次。请基于已有信息给用户最终回复。"
                        "如果未能解决问题，请如实说明情况并询问是否需要创建工单由专员跟进。",
                name="system_info",
                tool_call_id="_max_rounds",
            )],
            "tool_calls": prev_tool_calls,
            "metadata": metadata,
            "node_trace": ["tool_exec"],
        }

    # 检查特殊工具：propose_ticket / propose_human_escalation（生成确认按钮，不真正执行）
    for tc in last_ai.tool_calls:
        if tc["name"] == "propose_ticket":
            issue_type = tc["args"].get("issue_type", "other")
            summary = tc["args"].get("summary", "")
            metadata["ticket_offer_pending"] = True
            return {
                "ticket_offer": {
                    "issue_type": issue_type,
                    "summary": summary,
                },
                "messages": [ToolMessage(
                    content="已生成工单确认选项，用户将看到「是/否」按钮。请生成一条自然的过渡回复，告知用户问题已整理完毕，等待其确认是否需要创建工单。",
                    name="propose_ticket",
                    tool_call_id=tc["id"],
                )],
                "metadata": metadata,
                "node_trace": ["tool_exec"],
            }

        if tc["name"] == "propose_human_escalation":
            summary = tc["args"].get("summary", "")
            metadata["human_offer_pending"] = True
            return {
                "human_offer": {
                    "summary": summary,
                },
                "messages": [ToolMessage(
                    content="已生成转人工确认选项，用户将看到「是/否」按钮。"
                            "请生成一条自然的过渡回复：先简要总结用户问题，"
                            "再告知用户可通过按钮确认是否转人工。",
                    name="propose_human_escalation",
                    tool_call_id=tc["id"],
                )],
                "metadata": metadata,
                "node_trace": ["tool_exec"],
            }

    for tc in last_ai.tool_calls:
        tool_name: str = tc["name"]
        tool_args: dict = dict(tc["args"])
        tool_call_id: str = tc["id"]

        # 账号/工单查询强制使用 state 中的 user_id（来自 JWT，不可被 LLM 伪造）
        if tool_name in ("check_ticket", "lookup_account"):
            tool_args["user_id"] = state.get("user_id", "")

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

        # 重复调用检测：相同 tool + 相同 args 已在之前执行过，跳过执行
        is_duplicate = False
        if tool_name in ("check_ticket", "lookup_account"):
            for prev_call in state.get("tool_calls", []):
                if prev_call.get("tool") == tool_name and prev_call.get("input") == tool_args:
                    is_duplicate = True
                    break

        if is_duplicate:
            result_str = json.dumps({
                "status": "duplicate",
                "message": f"已查询过相同内容，结果为最终状态，请勿重复查询。请直接回复用户。",
                "do_not_retry": True,
            }, ensure_ascii=False)
            record["status"] = "completed"
            record["output"] = result_str
            record["duplicate"] = True
            tool_messages.append(ToolMessage(
                content=result_str,
                name=tool_name,
                tool_call_id=tool_call_id,
            ))
            tool_call_records.append(record)
            metadata["tool_repeated_call"] = True
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
        "node_trace": ["tool_exec"],
    }
