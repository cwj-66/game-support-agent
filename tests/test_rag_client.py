"""
RAG 客户端测试
测试直接 HTTP 调用 RAG 服务
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from agent.tools.rag_client import RAGClient


class TestRAGClient:
    """RAG客户端测试"""

    @pytest.mark.asyncio
    async def test_retrieve_success(self):
        """测试成功检索片段"""
        client = RAGClient(base_url="http://test-rag:8000", api_key="test-key")

        mock_response = {
            "query": "如何获得原石？",
            "sources": [
                {
                    "text": "可以通过每日委托获得原石",
                    "source": "faq.json",
                    "page": None,
                    "score": 0.92,
                }
            ],
            "max_score": 0.92,
            "retrieve_mode": "vector",
        }

        with patch("httpx.AsyncClient.post") as mock_post:
            mock_post.return_value = MagicMock(
                status_code=200,
                json=lambda: mock_response,
                raise_for_status=lambda: None,
            )

            result = await client.retrieve("如何获得原石？")

            assert len(result["sources"]) == 1
            assert result["max_score"] == 0.92
            mock_post.assert_called_once()
            call_kwargs = mock_post.call_args
            assert call_kwargs.kwargs["headers"].get("X-API-Key") == "test-key"

        await client.close()

    @pytest.mark.asyncio
    async def test_query_knowledge_success(self):
        """测试检索 + 本侧生成答案"""
        client = RAGClient(base_url="http://test-rag:8000", api_key=None)

        retrieve_payload = {
            "sources": [
                {
                    "text": "可以通过每日委托获得原石",
                    "source": "faq.json",
                    "page": None,
                    "score": 0.92,
                }
            ],
            "max_score": 0.92,
        }
        synth_payload = {
            "has_answer": True,
            "answer": "可以通过每日委托获得原石",
            "confidence": 0.92,
            "source_quote": "可以通过每日委托获得原石",
            "sources": retrieve_payload["sources"],
        }

        with patch.object(
            client, "retrieve", new=AsyncMock(return_value=retrieve_payload)
        ), patch(
            "agent.tools.knowledge_answer.answer_from_sources",
            new=AsyncMock(return_value=synth_payload),
        ):
            result = await client.query_knowledge("如何获得原石？")

            assert result["has_answer"] is True
            assert result["answer"] == "可以通过每日委托获得原石"
            assert result["confidence"] == 0.92

        await client.close()

    @pytest.mark.asyncio
    async def test_query_knowledge_failure(self):
        """测试查询失败降级"""
        client = RAGClient(base_url="http://test-rag:8000", api_key=None)

        with patch.object(
            client,
            "retrieve",
            new=AsyncMock(
                return_value={
                    "sources": [],
                    "max_score": 0.0,
                    "error": "Connection refused",
                    "message": "知识服务暂时不可用，建议转人工",
                }
            ),
        ):
            result = await client.query_knowledge("测试")

            assert result["has_answer"] is False
            assert "error" in result

        await client.close()

    @pytest.mark.asyncio
    async def test_health_check_healthy(self):
        """测试健康检查 - 健康"""
        client = RAGClient(base_url="http://test-rag:8000", api_key=None)

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
        client = RAGClient(base_url="http://test-rag:8000", api_key=None)

        with patch("httpx.AsyncClient.get") as mock_get:
            mock_get.side_effect = Exception("Connection refused")

            health = await client.health_check()

            assert health["status"] == "down"

        await client.close()
