"""Public execution summary: allowlisted stages and tool status only."""

STAGES = {
    "reasoning": "分析请求",
    "tool_exec": "执行工具",
    "generate": "组织回复",
    "finish": "完成回复",
}
TOOLS = {
    "lookup_account": "查询账号",
    "check_ticket": "查询工单",
    "query_knowledge": "检索知识库",
    "propose_ticket": "提议创建工单",
    "propose_human": "提议转人工",
}


def public_execution_trace(result: dict) -> dict:
    nodes = list(result.get("node_trace") or [])
    # The checkpoint reducer accumulates node_trace across turns.
    previous_ends = [i for i, node in enumerate(nodes[:-1]) if node == "finish"]
    if previous_ends:
        nodes = nodes[previous_ends[-1] + 1:]
    tools = []
    for call in result.get("tool_calls") or []:
        name = call.get("tool")
        if name in TOOLS:
            tools.append({
                "name": name,
                "label": TOOLS[name],
                "status": "failed" if call.get("status") == "failed" else "completed",
            })
    return {
        "stages": [{"name": node, "label": STAGES[node]} for node in nodes if node in STAGES],
        "tools": tools,
        "source_count": len((result.get("metadata") or {}).get("sources") or []),
    }
