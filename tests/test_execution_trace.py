from app.services.execution_trace import public_execution_trace


def test_trace_is_current_turn_and_does_not_expose_private_payloads():
    result = {
        "node_trace": ["reasoning", "finish", "reasoning", "tool_exec", "generate", "finish"],
        "messages": [{"content": "private reasoning"}],
        "tool_calls": [{"tool": "lookup_account", "status": "completed", "input": {"secret": "x"}, "output": "private data"}],
        "metadata": {"sources": [{"content": "private document"}]},
    }
    trace = public_execution_trace(result)
    assert len(trace["stages"]) == 4
    assert trace["tools"] == [{"name": "lookup_account", "label": "查询账号", "status": "completed"}]
    assert trace["source_count"] == 1
    assert "private" not in str(trace)


def test_unknown_tools_and_stages_are_not_published():
    trace = public_execution_trace({"node_trace": ["secret-stage"], "tool_calls": [{"tool": "unknown"}]})
    assert trace == {"stages": [], "tools": [], "source_count": 0}
