import json
from typing import Any, Dict, List

from .propose_ticket import propose_ticket
from .propose_human_escalation import propose_human_escalation


def simplify_tool_context(records: List[Dict[str, Any]]) -> List[Dict[str, str]]:
    """
    精简工具调用记录为关键信息，减少 tool_context 存储体积。
    """
    simplified: List[Dict[str, str]] = []
    for rec in records:
        tool = rec.get("tool", "")
        inp = rec.get("input", {})
        output = rec.get("output", "")
        status = rec.get("status", "")

        entry: Dict[str, str] = {"tool": tool}

        if isinstance(inp, dict):
            if tool == "lookup_account":
                entry["args"] = inp.get("fields", "") or ""
            elif tool in ("create_ticket", "propose_ticket"):
                issue = inp.get("issue_type", "")
                desc = inp.get("description", "") or inp.get("summary", "")
                entry["args"] = f"{issue}: {desc[:60]}" if desc else issue
            elif tool == "propose_human_escalation":
                entry["args"] = (inp.get("summary", "") or "")[:60]
            elif tool == "query_knowledge":
                entry["args"] = (inp.get("query", "") or "")[:80]
            elif tool == "check_ticket":
                entry["args"] = inp.get("ticket_id", "") or ""
            else:
                compact = ",".join(f"{k}={v}" for k, v in inp.items() if v is not None)
                entry["args"] = compact[:80]
        else:
            entry["args"] = str(inp)[:80]

        if isinstance(output, str) and output.startswith("{"):
            try:
                data = json.loads(output)
            except json.JSONDecodeError:
                data = None
            if data:
                if tool == "lookup_account":
                    parts = [data.get(k, "") for k in ("status", "ban_reason", "last_login") if data.get(k)]
                    entry["result"] = " | ".join(parts)[:120]
                elif tool in ("create_ticket", "propose_ticket"):
                    entry["result"] = f"工单 {data.get('ticket_id', '')} ({data.get('status', '')})"
                elif tool == "query_knowledge":
                    entry["result"] = "有结果" if data.get("has_answer") else "无结果"
                elif tool == "check_ticket":
                    status_val = data.get("status", "")
                    reply = data.get("agent_reply", "")
                    entry["result"] = f"{status_val}" + (f" | {reply[:60]}" if reply else "")
                else:
                    entry["result"] = str(data)[:120]
                if status == "failed":
                    entry["error"] = data.get("error", "执行失败")[:80]
                simplified.append(entry)
                continue

        if status == "failed":
            entry["error"] = rec.get("error", "执行失败")[:80]
        else:
            entry["result"] = str(output)[:120]
        simplified.append(entry)

    return simplified


def get_all_tools(user_id: str = ""):
    """返回 MCP 工具 + 本地提议类工具（propose_ticket / propose_human_escalation）。"""
    from .mcp_client import get_mcp_tools

    mcp_tools = get_mcp_tools()
    if not mcp_tools:
        raise RuntimeError("MCP 未连接，请确认 MCP Server 已启动且应用启动时初始化成功")

    local_offer_tools = [propose_ticket, propose_human_escalation]
    return list(mcp_tools) + local_offer_tools
