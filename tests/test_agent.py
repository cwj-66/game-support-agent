"""
Agent 测试
测试Agent完整流程
"""

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


class TestCheckpointer:
    """Checkpointer测试"""

    @pytest.mark.asyncio
    async def test_get_checkpointer_singleton(self):
        """测试checkpointer单例行为（RedisSaver mocked）"""
        from agent import checkpointer

        checkpointer._saver = None

        with patch("agent.checkpointer.RedisSaver") as mock_redis_saver:
            mock_instance = MagicMock()
            mock_redis_saver.return_value = mock_instance

            cp1 = await checkpointer.get_checkpointer()
            cp2 = await checkpointer.get_checkpointer()

            assert cp1 is cp2
            assert cp1 is not None
            assert mock_redis_saver.call_count == 1

        checkpointer._saver = None


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

        with patch("agent.graph.get_graph") as mock_get_graph:
            mock_graph = AsyncMock()
            mock_graph.ainvoke = AsyncMock(return_value=mock_result)
            mock_get_graph.return_value = mock_graph

            result = await run_agent("test_session", "test_uid_001", "如何获得原石？")

            assert result["final_response"] == "这是回复内容"
            assert result["session_id"] == "test_session"
