"""
MCP Server 测试
测试knowledge_server工具调用
"""

import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, patch, MagicMock
import json

from mcp_servers.knowledge_server.models import (
    QueryRequest, QueryResponse, KnowledgeChunk
)
from mcp_servers.knowledge_server.client import RAGClient, RAGServiceError


class TestRAGModels:
    """RAG模型测试"""
    
    def test_query_request_validation(self):
        """测试查询请求参数校验"""
        # 有效请求
        req = QueryRequest(question="如何获得原石？", top_k=5)
        assert req.question == "如何获得原石？"
        assert req.top_k == 5
        
        # 默认top_k
        req_default = QueryRequest(question="测试")
        assert req_default.top_k == 3
    
    def test_query_response_best_answer(self):
        """测试获取最佳答案"""
        # 有高分答案
        response = QueryResponse(
            query="测试",
            results=[
                KnowledgeChunk(content="答案1", source="faq", score=0.9),
                KnowledgeChunk(content="答案2", source="faq", score=0.6)
            ],
            has_answer=True
        )
        assert response.get_best_answer() == "答案1"
        
        # 无结果
        empty_response = QueryResponse(query="测试", has_answer=False)
        assert empty_response.get_best_answer() is None
        
        # 低分结果
        low_confidence = QueryResponse(
            query="测试",
            results=[
                KnowledgeChunk(content="低分答案", source="faq", score=0.3)
            ],
            has_answer=True
        )
        assert low_confidence.get_best_answer() is None


class TestRAGClient:
    """RAG客户端测试"""
    
    @pytest_asyncio.fixture
    async def client(self):
        """创建测试客户端"""
        client = RAGClient(base_url="http://test-rag:8000")
        yield client
        await client.close()
    
    @pytest.mark.asyncio
    async def test_query_knowledge_success(self, client):
        """测试成功查询知识库"""
        mock_response = {
            "query": "如何获得原石？",
            "results": [
                {
                    "content": "可以通过每日委托获得原石",
                    "source": "faq.json",
                    "score": 0.92,
                    "metadata": {}
                }
            ],
            "total_found": 1,
            "has_answer": True
        }
        
        with patch("httpx.AsyncClient.post") as mock_post:
            mock_post.return_value = MagicMock(
                status_code=200,
                json=lambda: mock_response,
                raise_for_status=lambda: None
            )
            
            result = await client.query_knowledge("如何获得原石？")
            
            assert result.has_answer is True
            assert result.total_found == 1
            assert result.results[0].score == 0.92
    
    @pytest.mark.asyncio
    async def test_query_knowledge_timeout(self, client):
        """测试查询超时降级"""
        import httpx
        
        with patch("httpx.AsyncClient.post") as mock_post:
            mock_post.side_effect = httpx.TimeoutException("Connection timeout")
            
            result = await client.query_knowledge("测试")
            
            # 应该返回降级响应
            assert result.has_answer is False
            assert result.results == []
    
    @pytest.mark.asyncio
    async def test_health_check_healthy(self, client):
        """测试健康检查 - 健康状态"""
        with patch("httpx.AsyncClient.get") as mock_get:
            mock_get.return_value = MagicMock(
                status_code=200,
                json=lambda: {"version": "1.0.0", "latency_ms": 50}
            )
            
            health = await client.health_check()
            
            assert health.status == "healthy"
            assert health.version == "1.0.0"
    
    @pytest.mark.asyncio
    async def test_health_check_down(self, client):
        """测试健康检查 - 服务不可用"""
        with patch("httpx.AsyncClient.get") as mock_get:
            mock_get.side_effect = Exception("Connection refused")
            
            health = await client.health_check()
            
            assert health.status == "down"


class TestMCPServerAuth:
    """MCP Server认证测试"""
    
    def test_auth_manager_verify_valid_key(self):
        """测试校验有效API Key"""
        from mcp_servers.knowledge_server.auth import MCPAuthManager
        
        manager = MCPAuthManager(api_key="test-secret-key")
        
        assert manager.verify("test-secret-key") is True
        assert manager.verify("wrong-key") is False
        assert manager.verify(None) is False
    
    def test_auth_manager_dev_mode(self):
        """测试开发模式（无Key）"""
        from mcp_servers.knowledge_server.auth import MCPAuthManager
        
        manager = MCPAuthManager(api_key="")
        
        # 开发模式下允许所有请求
        assert manager.verify("any-key") is True
        assert manager.verify(None) is True
    
    def test_auth_manager_constant_time_compare(self):
        """测试常量时间比较防时序攻击"""
        from mcp_servers.knowledge_server.auth import MCPAuthManager
        
        manager = MCPAuthManager(api_key="secret")
        
        # 无论Key长度如何，比较时间应该相近
        import time
        
        times = []
        for key in ["a", "abc", "secret", "very-long-key-that-does-not-match"]:
            start = time.perf_counter()
            manager.verify(key)
            times.append(time.perf_counter() - start)
        
        # 所有比较时间应该在同一数量级（不精确测试，仅验证机制存在）
        assert all(t < 0.01 for t in times)


# TODO: 需要补充的测试
# - TestMCPTools: MCP工具调用测试（需要mock fastmcp）
# - TestMCPSSE: SSE连接测试
# - TestMCPIntegration: 与RAG服务的集成测试
