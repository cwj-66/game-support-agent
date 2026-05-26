"""
通用工具执行节点
读取 AIMessage.tool_calls，动态分发并执行对应工具
"""

import json
from datetime import datetime, timezone
from typing import Dict, Any, List

from langchain_core.messages import AIMessage, ToolMessage

from ..state import AgentState
from ..tools import get_all_tools
from ..tools.escalate import get_default_escalate_detector


async def tool_exec_node(state: AgentState) -> Dict[str, Any]:
    """
    工具执行节点：通用分发器

    职责：
    1. 找到最后一条带 tool_calls 的 AIMessage
    2. 依次执行每个工具调用
    3. 若执行 escalate_to_human → 直接设 interrupt_info 升等
    4. 所有工具执行完后，若轮次达上限 → 跑 check_batch() 兜底拉闸
    5. 将 ToolMessage 写回 messages
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
    tool_messages: List[ToolMessage] = []
    tool_call_records: List[Dict[str, Any]] = []
    metadata = state.get("metadata", {})
    interrupt_info = None
    # 记录本次执行中是否有创建工单，供 state.ticket_id 更新
    _new_ticket_id: str | None = None

    # 计算 ReAct 轮次
    prev_tool_calls = state.get("tool_calls", [])
    non_escalate_count = sum(
        1 for tc in prev_tool_calls if tc.get("tool") != "escalate_to_human"
    )
    react_round = non_escalate_count + 1

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

            # lookup_account 返回封号状态 → 自动升等，不依赖 LLM 判断
            if tool_name == "lookup_account" and interrupt_info is None:
                try:
                    data = json.loads(result_str)
                except (json.JSONDecodeError, ValueError):
                    data = {}
                if data.get("status") == "banned":
                    interrupt_info = {
                        "should_interrupt": True,
                        "reason": f"账号 {data.get('uid', '未知')} 处于封禁状态：{data.get('ban_reason', '未知原因')}",
                        "level": "high",
                        "sensitive_words": [],
"pending_content": None,
                        "source": "auto_escalate",
                    }

            # create_ticket：提取工单号，供后续节点回写状态
            if tool_name == "create_ticket":
                try:
                    data = json.loads(result_str)
                    ticket_id_from_tool = data.get("ticket_id")
                except (json.JSONDecodeError, ValueError):
                    ticket_id_from_tool = None
                if ticket_id_from_tool:
                    _new_ticket_id = ticket_id_from_tool

            # escalate_to_human：LLM 主动升等，直接设 interrupt_info
            if tool_name == "escalate_to_human":
                try:
                    data = json.loads(result_str)
                except (json.JSONDecodeError, ValueError):
                    data = {}
                interrupt_info = {
                    "should_interrupt": True,
                    "reason": data.get("reason", "LLM主动请求人工介入"),
                    "level": data.get("level", "high"),
                    "sensitive_words": [],
                    "pending_content": None,
                    "source": "llm_escalate",
                }

            # 通用检查：工具通过 _health.needs_escalation 主动要求升等
            if interrupt_info is None:
                try:
                    health = json.loads(result_str).get("_health", {})
                except (json.JSONDecodeError, ValueError):
                    health = {}
                if health.get("needs_escalation"):
                    interrupt_info = {
                        "should_interrupt": True,
                        "reason": health.get("message", "工具执行结果需要人工介入"),
                        "level": "medium",
                        "sensitive_words": [],
                        "pending_content": None,
                        "source": "auto_escalate",
                    }

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

    # LLM 没有主动升等，但轮次达到上限 → 系统兜底拉闸
    if interrupt_info is None:
        detector = get_default_escalate_detector()
        if react_round >= detector.max_react_rounds:
            decision = detector.check_batch(tool_call_records, react_round)
            if decision.should_interrupt:
                interrupt_info = {
                    "should_interrupt": True,
                    "reason": decision.reason,
                    "level": decision.level,
                    "sensitive_words": [],
                    "pending_content": None,
                    "source": "auto_escalate",
                }

    result: Dict[str, Any] = {
        "messages": tool_messages,
        "tool_calls": state.get("tool_calls", []) + tool_call_records,
        "metadata": metadata,
    }
    if _new_ticket_id is not None:
        result["ticket_id"] = _new_ticket_id
    if interrupt_info is not None:
        result["interrupt_info"] = interrupt_info
    return result
