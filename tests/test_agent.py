"""
Agent 测试
测试Agent完整流程
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from agent.state import AgentState, create_initial_state, InterruptInfo, HumanReviewResult
from langchain_core.messages import AIMessage, ToolMessage


class TestAgentState:
    """Agent状态测试"""

    def test_create_initial_state(self):
        """测试创建初始状态"""
        state = create_initial_state("session_123", "test_uid_001", "如何获得原石？")

        assert state["session_id"] == "session_123"
        assert state["user_id"] == "test_uid_001"
        assert state["user_query"] == "如何获得原石？"
        assert state["messages"] == []
        assert state["interrupt_info"] is None
        assert state["human_review"] is None
        assert state["human_reply"] is None
        assert state["tool_calls"] == []
        assert state["final_response"] is None
        assert state["node_trace"] == []
        assert "metadata" in state

    def test_state_with_interrupt_info(self):
        """测试带中断信息的状态"""
        interrupt_info: InterruptInfo = {
            "should_interrupt": True,
            "reason": "检测到敏感词",
            "level": "high",
            "sensitive_words": ["封号"],
            "pending_content": "待审核内容",
        }

        state = create_initial_state("test", "test_uid_001", "测试")
        state["interrupt_info"] = interrupt_info

        assert state["interrupt_info"]["should_interrupt"] is True
        assert state["interrupt_info"]["level"] == "high"

    def test_state_with_human_review(self):
        """测试带人工审核结果的状态"""
        review: HumanReviewResult = {
            "action": "MODIFY",
            "reviewer_id": "admin_001",
            "modified_content": "修改后的内容",
            "notes": "测试",
        }

        state = create_initial_state("test", "test_uid_001", "测试")
        state["human_review"] = review

        assert state["human_review"]["action"] == "MODIFY"
        assert state["human_review"]["modified_content"] == "修改后的内容"


class TestCheckpointer:
    """Checkpointer测试"""

    @pytest.mark.asyncio
    async def test_get_checkpointer_singleton(self):
        """测试checkpointer单例行为（RedisSaver mocked）"""
        from agent import checkpointer

        # 重置单例
        checkpointer._saver = None

        with patch("agent.checkpointer.RedisSaver") as mock_redis_saver:
            mock_instance = MagicMock()
            mock_redis_saver.return_value = mock_instance

            cp1 = await checkpointer.get_checkpointer()
            cp2 = await checkpointer.get_checkpointer()

            assert cp1 is cp2
            assert cp1 is not None
            # init_checkpointer 只会被调用一次
            assert mock_redis_saver.call_count == 1

        checkpointer._saver = None


class TestAgentNodes:
    """Agent节点测试"""

    @staticmethod
    def _make_mock_llm(ai_msg_return):
        """创建 mock LLM，使 bind_tools 返回自身，ainvoke 返回指定消息"""
        mock_llm = MagicMock()
        # bind_tools 返回自身，这样 ainvoke 链能接上
        mock_llm.bind_tools.return_value = mock_llm
        mock_llm.ainvoke = AsyncMock(return_value=ai_msg_return)
        return mock_llm

    @pytest.mark.asyncio
    async def test_reasoning_node_no_tool(self):
        """测试推理节点：无工具调用"""
        from agent.nodes.reasoning import reasoning_node

        state = create_initial_state("test_001", "test_uid_001", "如何获得原石？")

        mock_ai_msg = MagicMock(spec=AIMessage)
        mock_ai_msg.tool_calls = []
        mock_ai_msg.content = "可以通过完成每日委托、开启宝箱等方式获得原石。"
        mock_llm = self._make_mock_llm(mock_ai_msg)

        with patch("agent.nodes.reasoning._build_llm_from_settings", return_value=mock_llm):
            result = await reasoning_node(state)

        assert "messages" in result
        assert "metadata" in result
        assert "node_trace" in result
        assert result["node_trace"] == ["reasoning"]
        assert result["metadata"]["reasoning"]["need_tool"] is False

    @pytest.mark.asyncio
    async def test_reasoning_node_with_tool(self):
        """测试推理节点：触发了工具调用"""
        from agent.nodes.reasoning import reasoning_node

        state = create_initial_state("test_001", "test_uid_001", "帮我查一下账号状态")

        mock_ai_msg = MagicMock(spec=AIMessage)
        mock_ai_msg.tool_calls = [
            {"name": "lookup_account", "args": {"fields": ["status"]}, "id": "call_1", "type": "tool_call"},
        ]
        mock_llm = self._make_mock_llm(mock_ai_msg)

        with patch("agent.nodes.reasoning._build_llm_from_settings", return_value=mock_llm):
            result = await reasoning_node(state)

        assert result["metadata"]["reasoning"]["need_tool"] is True

    @pytest.mark.asyncio
    async def test_tool_exec_node(self):
        """测试工具执行节点"""
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

        assert "messages" in result
        assert "tool_calls" in result
        assert len(result["tool_calls"]) == 1
        assert result["tool_calls"][0]["tool"] == "lookup_account"
        assert result["tool_calls"][0]["status"] == "completed"
        assert len(result["messages"]) == 1
        assert isinstance(result["messages"][0], ToolMessage)
        assert result["messages"][0].name == "lookup_account"

    @pytest.mark.asyncio
    async def test_human_node(self):
        """测试人工审核节点"""
        from agent.nodes.human_node import human_node

        state = create_initial_state("test_003", "test_uid_001", "我要投诉封号")
        state["interrupt_info"] = {
            "should_interrupt": True,
            "reason": "检测到敏感词: 投诉",
            "level": "high",
            "sensitive_words": ["投诉"],
            "pending_content": "关于封号问题...",
        }

        with patch("agent.nodes.human_node.interrupt") as mock_interrupt:
            mock_interrupt.return_value = "已处理，请放心"

            result = await human_node(state)

            assert "human_reply" in result
            assert result["human_reply"] == "已处理，请放心"
            assert result["node_trace"] == ["human"]

    @pytest.mark.asyncio
    async def test_detector_node_sensitive(self):
        """测试检测器节点：敏感词命中 → 回复替换为违规警告"""
        from agent.nodes.detector import detector_node

        state = create_initial_state("test", "test_uid_001", "测试")
        state["final_response"] = "我可以私下转账给你"
        state["metadata"] = {"tool_calls": []}

        result = await detector_node(state)

        assert result.get("final_response") == "抱歉，您的请求涉及违规内容，请遵守游戏社区规范。"
        assert result.get("interrupt_info") is None
        assert "detector_intercepted" in result.get("metadata", {})
        assert result["metadata"]["detector_intercepted"]["type"] == "sensitive"

    @pytest.mark.asyncio
    async def test_detector_node_pass(self):
        """测试检测器节点：无敏感词时透传"""
        from agent.nodes.detector import detector_node

        state = create_initial_state("test", "test_uid_001", "测试")
        state["final_response"] = "正常回复内容"
        state["metadata"] = {"tool_calls": []}

        result = await detector_node(state)

        assert result.get("interrupt_info") is None
        assert "node_trace" in result
        assert result["node_trace"] == ["detector"]

    @pytest.mark.asyncio
    async def test_generate_response_node_fallback(self):
        """测试响应生成节点：无消息时走 fallback"""
        from agent.nodes.generate import generate_response_node

        state = create_initial_state("test", "test_uid_001", "测试")

        result = await generate_response_node(state)

        assert "messages" in result
        assert "final_response" in result
        assert result["final_response"] == "抱歉，我暂时无法回答这个问题，建议联系人工客服。"

    @pytest.mark.asyncio
    async def test_finish_node_with_human_reply(self):
        """测试结束节点：有人工回复时作为最终回复"""
        from agent.nodes.finish import finish_node

        state = create_initial_state("test", "test_uid_001", "测试")
        state["human_reply"] = "人工回复内容"

        result = await finish_node(state)

        assert result["final_response"] == "人工回复内容"
        assert result["metadata"]["completed"] is True

    @pytest.mark.asyncio
    async def test_finish_node_without_human_reply(self):
        """测试结束节点：无人工回复"""
        from agent.nodes.finish import finish_node

        state = create_initial_state("test", "test_uid_001", "测试")

        result = await finish_node(state)

        assert "final_response" not in result
        assert result["metadata"]["completed"] is True


class TestAgentGraph:
    """Agent图测试"""

    def test_graph_compilation(self):
        """测试图结构完整性"""
        from agent.graph import workflow

        expected_nodes = {
            "reasoning", "tool_exec", "detector",
            "human", "generate", "finish", "human_handoff",
        }
        actual_nodes = set(workflow.nodes.keys())

        missing = expected_nodes - actual_nodes
        extra = actual_nodes - expected_nodes
        assert not missing, f"图中缺少节点: {missing}"
        assert not extra, f"图中存在未预期的节点: {extra}"


class TestAgentIntegration:
    """Agent集成测试"""

    @pytest.mark.asyncio
    async def test_full_flow_no_interrupt(self):
        """测试无中断的完整流程（mocked graph）"""
        from agent.graph import run_agent

        mock_result = {
            "final_response": "这是回复内容",
            "messages": [],
            "metadata": {"completed": True},
            "node_trace": [],
        }

        with patch("agent.graph.get_graph") as mock_get_graph:
            mock_graph = AsyncMock()
            mock_graph.ainvoke = AsyncMock(return_value=mock_result)
            mock_get_graph.return_value = mock_graph

            result = await run_agent("test_session", "test_uid_001", "如何获得原石？")

            assert result["final_response"] == "这是回复内容"
            assert result["session_id"] == "test_session"

    @pytest.mark.asyncio
    async def test_full_flow_with_interrupt(self):
        """测试带中断的完整流程"""
        pass  # TODO: 实现完整中断流程测试
