"""评测集与多轮执行器的离线回归测试。"""

from unittest.mock import AsyncMock
from pathlib import Path

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from eval.evaluate import (
    _build_judge_messages, _knowledge_evidence, _tool_evidence, load_test_cases, run_single,
    score_escalation, score_forbidden, score_tool_usage, score_turn,
)


def test_eval_suite_has_27_grounded_cases():
    cases = load_test_cases()
    assert len(cases) == 27
    assert len({case["id"] for case in cases}) == 27
    assert all(case["suite_version"] in (2, 3) and case["fixture"] for case in cases)
    assert all(len(case["turns"]) >= 2 for case in cases if case["id"].startswith("mc_"))

    root = Path(__file__).resolve().parents[1]
    sql = (root / "scripts/mysql/init.sql").read_text(encoding="utf-8")
    for case in cases:
        if case["fixture"].startswith("enterprise-rag"):
            continue
        file_name, _, record = case["fixture"].partition(":")
        assert (root / file_name).is_file()
        if record.startswith("support_tickets:TK-"):
            assert record.split(":", 1)[1] in sql

    import re
    owners = dict(re.findall(r"\('(TK-\d+-\d+)',\s*'(\d+)'", sql))
    for case in cases:
        if "support_tickets:TK-" not in case["fixture"]:
            continue
        ticket_id = case["fixture"].rsplit(":", 1)[1]
        if case["id"] == "tool_06":
            assert owners[ticket_id] != case["user_id"]
        else:
            assert owners[ticket_id] == case["user_id"]


def test_rag_cases_reference_real_knowledge():
    cases = load_test_cases("rag")
    assert len(cases) == 7
    assert all(case["suite_version"] == 3 for case in cases)
    assert all(case["fixture"].startswith("enterprise-rag") for case in cases)
    assert all("mock_rag" not in case["fixture"] for case in cases)
    assert next(case for case in cases if case["id"] == "rag_06")["category"] == "knowledge_gap"


@pytest.mark.asyncio
async def test_run_single_executes_turns_in_one_thread():
    messages = []
    calls = []

    async def invoke(turn_input, config):
        calls.append((turn_input, config))
        messages.extend([
            turn_input["messages"][0],
            AIMessage(content="回复", tool_calls=[{
                "name": "check_ticket", "args": {}, "id": f"call_{len(calls)}",
            }]),
        ])
        return {
            "messages": list(messages),
            "node_trace": ["reasoning", "tool_exec"] * len(calls),
            "final_response": "回复",
            "metadata": {"sources": []},
        }

    graph = type("Graph", (), {"ainvoke": AsyncMock(side_effect=invoke)})()
    case = {"id": "mc_test", "user_id": "10001", "turns": [
        {"question": "第一轮"}, {"question": "第二轮"},
    ]}
    result = await run_single(graph, case)

    assert result["error"] is None
    assert [turn["question"] for turn in result["turn_results"]] == ["第一轮", "第二轮"]
    assert all(len(turn["actual_tools"]) == 1 for turn in result["turn_results"])
    assert calls[0][1]["configurable"]["thread_id"] == calls[1][1]["configurable"]["thread_id"]
    assert isinstance(calls[0][0]["messages"][0], HumanMessage)


def test_tool_sequence_and_unsafe_claims_are_scored():
    case = {"expected_tool_sequence": [
        {"name": "lookup_account"}, {"name": "propose_ticket"},
    ]}
    score, _ = score_tool_usage(case, {"actual_tools": [
        {"name": "propose_ticket"}, {"name": "lookup_account"},
    ]})
    assert score < 1

    forbidden_score, _, blocked = score_forbidden(
        {"forbidden_phrases": ["工单已创建"]},
        {"actual_tools": [], "final_response": "工单已创建"},
    )
    assert forbidden_score == 0
    assert blocked is True


@pytest.mark.asyncio
async def test_quota_error_is_reported_as_environment_error():
    detail = await score_turn(
        {"question": "原石如何获取？", "expected_tool_sequence": [{"name": "query_knowledge"}]},
        {
            "actual_tools": [{"name": "query_knowledge"}],
            "tool_results": [{"name": "query_knowledge", "content": "AllocationQuota.FreeTierOnly"}],
            "final_response": "知识库暂时无法查询",
            "node_trace": [],
        },
        skip_llm=True,
    )
    assert "额度已用尽" in detail["environment_error"]


def test_other_players_ticket_case_expects_immediate_refusal():
    case = next(case for case in load_test_cases() if case["id"] == "tool_06")
    assert case["expected_no_tools"] is True
    assert score_tool_usage(case, {"actual_tools": []})[0] == 1.0


def test_unsolicited_human_offer_is_penalized():
    score, reason = score_escalation(
        {"must_escalate": False},
        {"actual_tools": [{"name": "propose_human_escalation"}]},
    )
    assert score == 0.0
    assert "不应主动转人工" in reason


def test_knowledge_judge_receives_only_actual_internal_sources():
    result = {"tool_results": [{"name": "query_knowledge", "content": (
        '{"sources":[{"text":"原石可通过每日委托获得。"}]}'
    )}]}
    evidence = _knowledge_evidence(result)
    prompt = _build_judge_messages("原石可通过每日委托获得，还可完成网上任务。",
                                   "原石可通过每日委托获得。", evidence=evidence)[0]["content"]
    assert "原石可通过每日委托获得。" in prompt
    assert "无依据内容" in prompt
    assert "不使用互联网" in prompt


def test_pending_ticket_status_is_not_scored_as_processing():
    case = next(case for case in load_test_cases() if case["id"] == "tool_07")
    score, _, blocked = score_forbidden(case, {
        "actual_tools": [], "final_response": "您的工单正在处理中。",
    })
    assert score == 0.0 and blocked


def test_account_judge_receives_current_players_tool_result():
    evidence = _tool_evidence({"tool_results": [{
        "name": "lookup_account", "content": '{"recharge_total":648.0}',
    }]})
    assert "recharge_total" in evidence
    assert "648.0" in evidence
