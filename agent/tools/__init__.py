import json
from typing import Any, Dict, List

from .query_knowledge import create_knowledge_tool

from .account import create_lookup_account
from .ticket import create_ticket
from .ticket_status import create_check_ticket
from .human_escalation import request_human_escalation


def simplify_tool_context(records: List[Dict[str, Any]]) -> List[Dict[str, str]]:
    """
    精简工具调用记录为关键信息，减少 tool_context 存储体积。

    输入（当前详细格式）：
        [{"tool":"lookup_account","input":{"fields":"status"},"timestamp":"...","status":"completed","output":"{...}"}]

    输出（精简后）：
        [{"tool":"lookup_account","args":"status","result":"banned | 账号封禁"}]
    """
    simplified: List[Dict[str, str]] = []
    for rec in records:
        tool = rec.get("tool", "")
        inp = rec.get("input", {})
        output = rec.get("output", "")
        status = rec.get("status", "")

        entry: Dict[str, str] = {"tool": tool}

        # --- 精简 input 为简短字符串 ---
        if isinstance(inp, dict):
            if tool == "lookup_account":
                entry["args"] = inp.get("fields", "") or ""
            elif tool == "create_ticket":
                issue = inp.get("issue_type", "")
                desc = inp.get("description", "")
                entry["args"] = f"{issue}: {desc[:60]}" if desc else issue
            elif tool == "query_knowledge":
                entry["args"] = (inp.get("query", "") or "")[:80]
            elif tool == "check_ticket":
                entry["args"] = inp.get("ticket_id", "") or ""
            else:
                # 兜底：只保留非空值 key
                compact = ",".join(f"{k}={v}" for k, v in inp.items() if v is not None)
                entry["args"] = compact[:80]
        else:
            entry["args"] = str(inp)[:80]

        # --- 精简 output 为简短结果摘要 ---
        if isinstance(output, str) and output.startswith("{"):
            try:
                data = json.loads(output)
            except json.JSONDecodeError:
                data = None
            if data:
                if tool == "lookup_account":
                    parts = [data.get(k, "") for k in ("status", "ban_reason", "last_login") if data.get(k)]
                    entry["result"] = " | ".join(parts)[:120]
                elif tool == "create_ticket":
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

        # 非 JSON 或 JSON 解析失败：直接截取输出
        if status == "failed":
            entry["error"] = rec.get("error", "执行失败")[:80]
        else:
            entry["result"] = str(output)[:120]
        simplified.append(entry)

    return simplified


def get_all_tools(user_id: str = ""):
    """返回所有客服工具列表。

    所有工具都是本地注册的 LangChain tool，其中 lookup_account 和 check_ticket
    的 user_id 由系统注入，不暴露给 LLM 自由传参。

    Args:
        user_id: 当前玩家 UID，传给工厂创建绑定了该用户的工具实例
    """
    tools = [
        create_knowledge_tool(),
        create_lookup_account(user_id),
        create_check_ticket(user_id),
        create_ticket,
        request_human_escalation,
    ]
    return tools
