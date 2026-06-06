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
    # 记录本次执行中是否有创建工单，供 state.ticket_id 更新
    _new_ticket_id: str | None = None

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

    # 检查是否包含 request_human_escalation → 跳过所有工具，直接升等
    for tc in last_ai.tool_calls:
        if tc["name"] == "request_human_escalation":
            reason = tc["args"].get("reason", "用户要求转人工")
            return {
                "interrupt_info": {
                    "should_interrupt": True,
                    "reason": reason,
                    "level": "high",
                    "sensitive_words": [],
                    "pending_content": None,
                    "source": "llm_escalate",
                },
                "node_trace": ["tool_exec"],
            }

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

            # create_ticket：提取工单号，并附上工具调用上下文
            if tool_name == "create_ticket":
                try:
                    data = json.loads(result_str)
                    ticket_id_from_tool = data.get("ticket_id")
                except (json.JSONDecodeError, ValueError):
                    ticket_id_from_tool = None
                if ticket_id_from_tool:
                    _new_ticket_id = ticket_id_from_tool
                    # 收集本轮及之前的工具调用记录（排除 create_ticket 自身）
                    context_records = [
                        r for r in state.get("tool_calls", [])
                        if r.get("tool") != "create_ticket"
                    ]
                    for r in tool_call_records:
                        if r.get("tool") != "create_ticket":
                            context_records.append(r)
                    try:
                        from app.core.database import update_ticket
                        update_ticket(
                            ticket_id_from_tool,
                            tool_context=json.dumps(simplify_tool_context(context_records), ensure_ascii=False),
                        )
                    except Exception:
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

    result: Dict[str, Any] = {
        "messages": tool_messages,
        "tool_calls": state.get("tool_calls", []) + tool_call_records,
        "metadata": metadata,
        "node_trace": ["tool_exec"],
    }
    if _new_ticket_id is not None:
        result["ticket_id"] = _new_ticket_id
    return result
