"""
Agent 测试
测试Agent完整流程
"""

import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from agent.state import AgentState, create_initial_state, create_turn_input
from langchain_core.messages import AIMessage, ToolMessage, HumanMessage


class TestAgentState:
    """Agent状态测试"""

    def test_create_initial_state(self):
        """测试创建初始状态"""
        state = create_initial_state("session_123", "test_uid_001", "如何获得原石？")

        assert state["session_id"] == "session_123"
        assert state["user_id"] == "test_uid_001"
        assert state["user_query"] == "如何获得原石？"
        assert state["messages"] == []
        assert state["human_mode"] is False
        assert state["human_offer"] is None
        assert state["ticket_offer"] is None
        assert state["tool_calls"] == []
        assert state["final_response"] is None
        assert state["node_trace"] == []
        assert "metadata" in state

    def test_create_turn_input(self):
        """测试每轮增量输入：玩家原话写入 messages"""
        turn = create_turn_input("session_123", "uid_001", "帮我查账号")

        assert turn["session_id"] == "session_123"
        assert turn["user_query"] == "帮我查账号"
        assert len(turn["messages"]) == 1
        assert isinstance(turn["messages"][0], HumanMessage)
        assert turn["messages"][0].content == "帮我查账号"
        assert turn["tool_calls"] == []
        assert turn["metadata"] == {}
        assert turn["ticket_offer"] is None
        assert turn["human_offer"] is None
        assert turn["final_response"] is None


@pytest.mark.asyncio
async def test_knowledge_error_does_not_propose_ticket_or_human():
    from agent.nodes.reasoning import reasoning_node
    from agent.nodes.generate import generate_response_node

    state = create_initial_state("s", "10001", "原石有哪些获取方式？")
    state["messages"] = [
        HumanMessage(content=state["user_query"]),
        ToolMessage(content='{"has_answer":false,"error":"quota"}',
                    name="query_knowledge", tool_call_id="call_1"),
    ]
    state["metadata"] = {"knowledge_result": {"has_answer": False, "error": "quota"}}

    with patch("agent.nodes.reasoning._build_llm_from_settings") as llm:
        decision = await reasoning_node(state)
    assert llm.call_count == 0
    assert not decision["messages"][0].tool_calls
    assert "查询暂时失败" in decision["messages"][0].content

    state.update(decision)
    response = await generate_response_node(state)
    assert response["final_response"] == decision["messages"][0].content


@pytest.mark.asyncio
async def test_knowledge_polish_receives_only_verified_facts():
    from agent.nodes.generate import generate_response_node

    quote = "原石可通过每日委托、活动奖励、深渊挑战和商店购买等方式获得。"
    state = create_initial_state("s", "10001", "原石有哪些获取方式？")
    state["messages"] = [HumanMessage(content=state["user_query"])]
    state["tool_calls"] = [{"tool": "query_knowledge"}]
    state["metadata"] = {"knowledge_result": {
        "has_answer": True,
        "answer": quote + "还可通过邮箱领取。",
        "source_quote": quote,
        "sources": [{"text": quote}],
    }}

    llm = MagicMock()
    llm.ainvoke = AsyncMock(return_value=AIMessage(content=quote + "如果还有其他问题，也可以继续问我。"))
    with patch("agent.nodes.generate.get_chat_model", return_value=llm):
        response = await generate_response_node(state)
    assert quote in response["final_response"]
    assert "还可通过邮箱领取" not in llm.ainvoke.call_args.args[0][-1].content
    assert quote in llm.ainvoke.call_args.args[0][-1].content


def test_pdf_line_wrap_does_not_reject_real_quote():
    from agent.tools.knowledge_answer import _quote_matches_source

    sources = [{"text": "等待24 小时后仍未到账,请提供带有商\n户订单号的支付截图。"}]
    assert _quote_matches_source(
        "等待24 小时后仍未到账,请提供带有商户订单号的支付截图。", sources
    )
    assert not _quote_matches_source("客服保证立即退款。", sources)


@pytest.mark.asyncio
async def test_pending_ticket_keeps_database_status():
    from agent.nodes.generate import generate_response_node

    state = create_initial_state("s", "10006", "看看我最近的工单有没有进展")
    state["tool_calls"] = [{"tool": "check_ticket"}]
    state["messages"] = [
        HumanMessage(content=state["user_query"]),
        ToolMessage(
            content=json.dumps({"total": 1, "tickets": [{
                "ticket_id": "TK-20260528-6001", "title": "活动奖励未发放",
                "status": "pending", "agent_reply": "",
            }]}),
            name="check_ticket", tool_call_id="call_1",
        ),
    ]
    with patch("agent.nodes.generate.get_chat_model") as llm:
        result = await generate_response_node(state)
    assert llm.call_count == 0
    assert "待处理" in result["final_response"]
    assert "处理中" not in result["final_response"]
    assert "尚无客服回复" in result["final_response"]


@pytest.mark.asyncio
async def test_previous_turn_ticket_status_does_not_replace_new_answer():
    from agent.nodes.generate import generate_response_node

    state = create_initial_state("s", "10006", "谢谢")
    state["messages"] = [
        HumanMessage(content="查工单"),
        ToolMessage(
            content=json.dumps({"found": True, "ticket_id": "TK-1", "status": "pending"}),
            name="check_ticket", tool_call_id="call_1",
        ),
        HumanMessage(content="谢谢"),
        AIMessage(content="不客气。"),
    ]
    state["tool_calls"] = []
    mock_llm = MagicMock()
    mock_llm.ainvoke = AsyncMock(return_value=AIMessage(content="不客气。"))
    with patch("agent.nodes.generate.get_chat_model", return_value=mock_llm):
        result = await generate_response_node(state)

    mock_llm.ainvoke.assert_awaited_once()
    assert result["final_response"] == "不客气。"


class TestCheckpointer:
    """Checkpointer测试"""

    @pytest.mark.asyncio
    async def test_get_checkpointer_singleton(self):
        """测试 checkpointer 单例行为（AsyncSqliteSaver mocked）"""
        from agent import checkpointer

        checkpointer._saver = None
        checkpointer._conn = None

        with patch("agent.checkpointer.aiosqlite.connect", new_callable=AsyncMock) as mock_connect, \
             patch("agent.checkpointer.AsyncSqliteSaver") as mock_saver_cls, \
             patch("agent.checkpointer.os.makedirs"):
            mock_conn = AsyncMock()
            mock_connect.return_value = mock_conn
            mock_instance = MagicMock()
            mock_instance.setup = AsyncMock()
            mock_saver_cls.return_value = mock_instance

            cp1 = await checkpointer.get_checkpointer()
            cp2 = await checkpointer.get_checkpointer()

            assert cp1 is cp2
            assert cp1 is mock_instance
            assert mock_saver_cls.call_count == 1

        checkpointer._saver = None
        checkpointer._conn = None


class TestAgentNodes:
    """Agent节点测试"""

    @staticmethod
    def _make_mock_llm(ai_msg_return):
        mock_llm = MagicMock()
        mock_llm.bind_tools.return_value = mock_llm
        mock_llm.ainvoke = AsyncMock(return_value=ai_msg_return)
        return mock_llm

    @pytest.mark.asyncio
    async def test_reasoning_node_no_tool(self):
        from agent.nodes.reasoning import reasoning_node

        state = create_initial_state("test_001", "test_uid_001", "如何获得原石？")

        mock_ai_msg = MagicMock(spec=AIMessage)
        mock_ai_msg.tool_calls = []
        mock_ai_msg.content = "可以通过完成每日委托、开启宝箱等方式获得原石。"
        mock_llm = self._make_mock_llm(mock_ai_msg)

        with patch("agent.nodes.reasoning._build_llm_from_settings", return_value=mock_llm), \
             patch("agent.nodes.reasoning.get_all_tools", return_value=[]):
            result = await reasoning_node(state)

        assert "messages" in result
        assert result["node_trace"] == ["reasoning"]
        assert result["metadata"]["reasoning"]["need_tool"] is False

    @pytest.mark.asyncio
    async def test_reasoning_node_with_tool(self):
        from agent.nodes.reasoning import reasoning_node

        state = create_initial_state("test_001", "test_uid_001", "帮我查一下账号状态")

        mock_ai_msg = MagicMock(spec=AIMessage)
        mock_ai_msg.tool_calls = [
            {"name": "lookup_account", "args": {"fields": ["status"]}, "id": "call_1", "type": "tool_call"},
        ]
        mock_llm = self._make_mock_llm(mock_ai_msg)

        with patch("agent.nodes.reasoning._build_llm_from_settings", return_value=mock_llm), \
             patch("agent.nodes.reasoning.get_all_tools", return_value=[]):
            result = await reasoning_node(state)

        assert result["metadata"]["reasoning"]["need_tool"] is True

    @pytest.mark.asyncio
    async def test_tool_exec_node(self):
        from agent.nodes.tool_exec import tool_exec_node

        state = create_initial_state("test_002", "test_uid_001", "查账号状态")
        state["messages"] = [
            AIMessage(
                content="我来查询账号状态",
                tool_calls=[
                    {"name": "lookup_account", "args": {"fields": ["status"]}, "id": "call_1", "type": "tool_call"},
                ],
            ),
        ]

        mock_tool = MagicMock()
        mock_tool.name = "lookup_account"
        mock_tool.ainvoke = AsyncMock(return_value='{"status": "normal"}')

        with patch("agent.nodes.tool_exec.get_all_tools", return_value=[mock_tool]):
            result = await tool_exec_node(state)

        assert len(result["tool_calls"]) == 1
        assert result["tool_calls"][0]["tool"] == "lookup_account"
        assert isinstance(result["messages"][0], ToolMessage)

    @pytest.mark.asyncio
    async def test_knowledge_tool_failure_sets_terminal_metadata(self):
        from agent.nodes.tool_exec import tool_exec_node

        state = create_initial_state("s", "10001", "原石有哪些获取方式？")
        state["messages"] = [AIMessage(content="", tool_calls=[{
            "name": "query_knowledge", "args": {"question": state["user_query"]},
            "id": "call_kb", "type": "tool_call",
        }])]
        mock_tool = MagicMock()
        mock_tool.name = "query_knowledge"
        mock_tool.ainvoke = AsyncMock(side_effect=RuntimeError("quota"))

        with patch("agent.nodes.tool_exec.get_all_tools", return_value=[mock_tool]):
            result = await tool_exec_node(state)
        assert result["metadata"]["knowledge_result"]["has_answer"] is False
        assert result["metadata"]["sources"] == []

    @pytest.mark.asyncio
    async def test_check_ticket_uses_authenticated_user_id(self):
        from agent.nodes.tool_exec import tool_exec_node

        state = create_initial_state("player-1_session", "player-1", "查工单")
        state["messages"] = [AIMessage(content="", tool_calls=[{
            "name": "check_ticket",
            "args": {"ticket_id": "TK-1", "user_id": "player-2"},
            "id": "call_ticket", "type": "tool_call",
        }])]
        mock_tool = MagicMock()
        mock_tool.name = "check_ticket"
        mock_tool.ainvoke = AsyncMock(return_value='{"found": false}')

        with patch("agent.nodes.tool_exec.get_all_tools", return_value=[mock_tool]):
            await tool_exec_node(state)

        mock_tool.ainvoke.assert_awaited_once_with({
            "ticket_id": "TK-1", "user_id": "player-1",
        })

    @pytest.mark.asyncio
    async def test_query_knowledge_sources_reach_chat_response(self):
        from agent.nodes.tool_exec import tool_exec_node
        from app.api.v1.chat import send_message
        from app.api.deps import CurrentPlayer
        from app.models.chat import ChatRequest
        from tests.conftest import make_request

        sources = [{"source": "faq.json", "text": "每日委托可获得原石", "score": 0.92}]
        state = create_initial_state("player-1_session", "player-1", "如何获得原石？")
        state["messages"] = [AIMessage(
            content="", tool_calls=[{
                "name": "query_knowledge", "args": {"question": "如何获得原石？"},
                "id": "call_knowledge", "type": "tool_call",
            }],
        )]
        mock_tool = MagicMock()
        mock_tool.name = "query_knowledge"
        mock_tool.ainvoke = AsyncMock(return_value=json.dumps({
            "has_answer": True, "answer": "做每日委托", "sources": sources,
        }, ensure_ascii=False))

        with patch("agent.nodes.tool_exec.get_all_tools", return_value=[mock_tool]):
            tool_result = await tool_exec_node(state)

        assert tool_result["metadata"]["sources"] == sources
        with patch("app.api.v1.chat.get_pending", new=AsyncMock(return_value=None)), \
             patch("app.api.v1.chat.is_human_mode", new=AsyncMock(return_value=False)), \
             patch("app.api.v1.chat.run_agent", new=AsyncMock(return_value={
                 "final_response": "做每日委托", "metadata": tool_result["metadata"],
             })):
            response = await send_message(
                ChatRequest(session_id="player-1_session", message="如何获得原石？"),
                make_request(), CurrentPlayer(user_id="player-1"),
            )

        assert response.sources == sources

    @pytest.mark.asyncio
    async def test_query_knowledge_mcp_content_blocks_preserve_sources(self):
        from agent.nodes.tool_exec import tool_exec_node

        sources = [{"source": "faq.json", "text": "每日委托可获得原石", "score": 0.92}]
        state = create_initial_state("player-1_session", "player-1", "如何获得原石？")
        state["messages"] = [AIMessage(content="", tool_calls=[{
            "name": "query_knowledge", "args": {"question": "如何获得原石？"},
            "id": "call_knowledge", "type": "tool_call",
        }])]
        mock_tool = MagicMock()
        mock_tool.name = "query_knowledge"
        mock_tool.ainvoke = AsyncMock(return_value=[{
            "type": "text", "text": json.dumps({"has_answer": True, "sources": sources}),
        }])

        with patch("agent.nodes.tool_exec.get_all_tools", return_value=[mock_tool]):
            result = await tool_exec_node(state)

        assert result["metadata"]["sources"] == sources
        assert json.loads(result["messages"][0].content)["sources"] == sources

    @pytest.mark.asyncio
    async def test_tool_exec_propose_human_escalation(self):
        """转人工提议应写入 human_offer，不设 interrupt"""
        from agent.nodes.tool_exec import tool_exec_node

        state = create_initial_state("test_003", "test_uid_001", "转人工")
        state["messages"] = [
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "propose_human_escalation",
                        "args": {"summary": "充值未到账"},
                        "id": "call_h1",
                        "type": "tool_call",
                    },
                ],
            ),
        ]

        with patch("agent.nodes.tool_exec.get_all_tools", return_value=[]):
            result = await tool_exec_node(state)

        assert result.get("human_offer") == {
            "summary": "充值未到账",
        }
        assert "interrupt_info" not in result
        assert result["metadata"]["human_offer_pending"] is True

    @pytest.mark.asyncio
    async def test_generate_response_node_fallback(self):
        from agent.nodes.generate import generate_response_node

        state = create_initial_state("test", "test_uid_001", "测试")

        result = await generate_response_node(state)

        assert result["final_response"] == "抱歉，我暂时无法回答这个问题，建议联系人工客服。"

    @pytest.mark.asyncio
    async def test_finish_node(self):
        from agent.nodes.finish import finish_node

        state = create_initial_state("test", "test_uid_001", "测试")

        result = await finish_node(state)

        assert result["metadata"]["completed"] is True
        assert "final_response" not in result


class TestAgentGraph:
    """Agent图测试"""

    def test_graph_compilation(self):
        from agent.graph import workflow

        expected_nodes = {
            "reasoning", "tool_exec", "generate", "finish",
        }
        actual_nodes = set(workflow.nodes.keys())

        assert expected_nodes == actual_nodes


class TestAgentIntegration:
    """Agent集成测试"""

    @pytest.mark.asyncio
    async def test_full_flow_no_interrupt(self):
        from agent.graph import run_agent

        mock_result = {
            "final_response": "这是回复内容",
            "messages": [],
            "metadata": {"completed": True},
            "node_trace": [],
            "human_offer": None,
            "ticket_offer": None,
        }

        with patch("agent.graph.get_graph") as mock_get_graph, \
             patch("app.services.session_store.expire_session_if_needed",
                   new=AsyncMock(return_value=True)):
            mock_graph = AsyncMock()
            mock_graph.ainvoke = AsyncMock(return_value=mock_result)
            mock_get_graph.return_value = mock_graph

            result = await run_agent("test_session", "test_uid_001", "如何获得原石？")

            assert result["final_response"] == "这是回复内容"
            assert result["session_id"] == "test_session"
