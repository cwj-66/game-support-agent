"""
RAG 客户端测试
测试直接 HTTP 调用 RAG 服务
"""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from agent.tools.rag_client import RAGClient


class TestRAGClient:
    """RAG客户端测试"""

    @pytest.mark.asyncio
    async def test_query_knowledge_success(self):
        """测试成功查询知识库"""
        client = RAGClient(base_url="http://test-rag:8000")

        mock_response = {
            "answer": "可以通过每日委托获得原石",
            "confidence": 0.92,
            "sources": ["faq.json"],
        }

        with patch("httpx.AsyncClient.post") as mock_post:
            mock_post.return_value = MagicMock(
                status_code=200,
                json=lambda: mock_response,
                raise_for_status=lambda: None,
            )

            result = await client.query_knowledge("如何获得原石？")

            assert result["has_answer"] is True
            assert result["answer"] == "可以通过每日委托获得原石"
            assert result["confidence"] == 0.92

        await client.close()

    @pytest.mark.asyncio
    async def test_query_knowledge_failure(self):
        """测试查询失败降级"""
        client = RAGClient(base_url="http://test-rag:8000")

        with patch("httpx.AsyncClient.post") as mock_post:
            mock_post.side_effect = Exception("Connection refused")

            result = await client.query_knowledge("测试")

            assert result["has_answer"] is False
            assert "error" in result

        await client.close()

    @pytest.mark.asyncio
    async def test_health_check_healthy(self):
        """测试健康检查 - 健康"""
        client = RAGClient(base_url="http://test-rag:8000")

        with patch("httpx.AsyncClient.get") as mock_get:
            mock_get.return_value = MagicMock(
                status_code=200,
                json=lambda: {"version": "1.0.0"},
            )

            health = await client.health_check()

            assert health["status"] == "healthy"

        await client.close()

    @pytest.mark.asyncio
    async def test_health_check_down(self):
        """测试健康检查 - 不可用"""
        client = RAGClient(base_url="http://test-rag:8000")

        with patch("httpx.AsyncClient.get") as mock_get:
            mock_get.side_effect = Exception("Connection refused")

            health = await client.health_check()

            assert health["status"] == "down"

        await client.close()
