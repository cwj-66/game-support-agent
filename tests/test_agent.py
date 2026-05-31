"""
Agent 测试
测试Agent完整流程
"""

import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from agent.state import AgentState, create_initial_state, InterruptInfo, HumanReviewResult
from agent.checkpointer import get_checkpointer, reset_checkpointer


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
        assert "metadata" in state

    def test_state_with_interrupt_info(self):
        """测试带中断信息的状态"""
        interrupt_info: InterruptInfo = {
            "should_interrupt": True,
            "reason": "检测到敏感词",
            "level": "high",
            "sensitive_words": ["封号"],
            "pending_content": "待审核内容"
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
        """测试checkpointer单例"""
        await reset_checkpointer()

        cp1 = await get_checkpointer()
        cp2 = await get_checkpointer()

        assert cp1 is cp2
        assert cp1 is not None


class TestAgentNodes:
    """Agent节点测试"""

    @pytest.mark.asyncio
    async def test_reasoning_node(self):
        """测试推理节点"""
        from agent.nodes.reasoning import reasoning_node

        state = create_initial_state("test_001", "test_uid_001", "如何获得原石？")
        mock_llm = MagicMock()

        result = await reasoning_node(state, mock_llm)

        # 验证返回结构
        assert "messages" in result
        assert "metadata" in result
        assert "_need_tool" in result
        assert "reasoning" in result["metadata"]

    @pytest.mark.asyncio
    async def test_tool_exec_node(self):
        """测试工具执行节点"""
        from agent.nodes.tool_exec import tool_exec_node

        state = create_initial_state("test_002", "test_uid_001", "原神角色介绍")

        with patch("agent.tools.query_knowledge.KnowledgeTool") as mock_tool:
            mock_instance = MagicMock()
            mock_instance._arun = AsyncMock(return_value='{"has_answer": true}')
            mock_tool.return_value = mock_instance

            result = await tool_exec_node(state)

            assert "messages" in result
            assert "tool_calls" in result
            assert "metadata" in result

    @pytest.mark.asyncio
    async def test_human_node(self):
        """测试人工审核节点"""
        from agent.nodes.human_node import human_node

        state = create_initial_state("test_003", "test_uid_001", "我要投诉封号")
        state["final_response"] = "关于封号问题..."
        state["interrupt_info"] = {
            "should_interrupt": True,
            "reason": "检测到敏感词: 投诉",
            "level": "high",
            "sensitive_words": ["投诉"],
            "pending_content": "关于封号问题..."
        }

        with patch("agent.nodes.human_node.interrupt") as mock_interrupt:
            mock_interrupt.return_value = {
                "action": "APPROVE",
                "reviewer_id": "admin_001",
                "timestamp": "2024-01-01T00:00:00",
                "modified_content": None,
                "notes": "通过",
                "approved": True
            }

            result = await human_node(state)

            assert "human_review" in result
            assert result["human_review"]["action"] == "APPROVE"
            assert result["final_response"] is not None


class TestAgentGraph:
    """Agent图测试"""

    def test_graph_compilation(self):
        """测试图编译"""
        from agent.graph import workflow

        # 验证所有节点已注册
        assert "reasoning" in workflow.nodes
        assert "tool_exec" in workflow.nodes
        assert "detector" in workflow.nodes
        assert "human" in workflow.nodes
        assert "generate" in workflow.nodes

    @pytest.mark.asyncio
    async def test_detector_node_logic(self):
        """测试检测器节点逻辑"""
        from agent.graph import detector_node

        # 测试敏感词触发 → 回复被替换为警告
        state = create_initial_state("test", "test_uid_001", "测试")
        state["final_response"] = "我可以私下转账给你"

        result = await detector_node(state)

        # 不再走中断，而是直接替换 final_response
        assert result.get("final_response") == "抱歉，您的请求涉及违规内容，请遵守游戏社区规范。"
        assert result.get("interrupt_info") is None
        assert "detector_intercepted" in result.get("metadata", {})
        assert result["metadata"]["detector_intercepted"]["type"] == "sensitive"

    @pytest.mark.asyncio
    async def test_generate_response_node(self):
        """测试响应生成节点"""
        from agent.graph import generate_response_node

        state = create_initial_state("test", "test_uid_001", "测试")
        state["metadata"] = {
            "knowledge_result": {
                "has_answer": True,
                "answer": "知识库答案"
            }
        }

        result = await generate_response_node(state)

        assert "messages" in result
        assert "final_response" in result
        assert result["final_response"] is not None


class TestAgentIntegration:
    """Agent集成测试"""

    @pytest.mark.asyncio
    async def test_full_flow_no_interrupt(self):
        """测试无中断的完整流程"""
        from agent.graph import run_agent

        # Mock所有依赖
        mock_result = {
            "final_response": "这是回复内容",
            "messages": [],
            "metadata": {"completed": True}
        }
        with patch("agent.graph.get_graph") as mock_get_graph:
            mock_graph = AsyncMock()
            mock_graph.ainvoke = AsyncMock(return_value=mock_result)
            mock_get_graph.return_value = mock_graph

            result = await run_agent("test_session", "test_uid_001", "如何获得原石？")

            assert "final_response" in result
            assert result["session_id"] == "test_session"

    @pytest.mark.asyncio
    async def test_full_flow_with_interrupt(self):
        """测试带中断的完整流程"""
        # 模拟中断场景
        pass  # TODO: 实现完整中断流程测试


# TODO: 需要补充的测试
# - TestKnowledgeTool: 知识工具适配器测试
# - TestAgentPrompts: 提示词模板测试
# - TestAgentStreaming: 流式输出测试
# - TestAgentConcurrency: 并发会话测试
