"""
RAG服务 HTTP 客户端封装
使用httpx异步调用 enterprise-rag 服务 (localhost:8000)
"""

import httpx
from typing import Optional, List
from .models import HealthResponse


class RAGClient:
    """
    RAG服务客户端
    
    职责：
    1. 封装对localhost:8000的HTTP调用
    2. 处理超时、重试、错误转换
    3. 响应数据转换为Pydantic模型
    
    TODO: 实现连接池和断路器模式
    TODO: 添加请求日志记录
    """
    
    def __init__(
        self, 
        base_url: str = "http://localhost:8000",
        timeout: float = 10.0,
        max_retries: int = 2
    ):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.max_retries = max_retries
        self._client: Optional[httpx.AsyncClient] = None
    
    async def _get_client(self) -> httpx.AsyncClient:
        """获取或创建httpx客户端（延迟初始化）"""
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=self.timeout,
                limits=httpx.Limits(max_keepalive_connections=5, max_connections=10)
            )
        return self._client
    
    async def query_knowledge(
        self,
        question: str,
        top_k: int = 3
    ) -> dict:
        """
        查询RAG知识库

        Args:
            question: 用户问题
            top_k: 返回结果数量

        Returns:
            包含 has_answer、answer、confidence、sources 的字典；
            失败时返回含 error 字段的降级字典
        """
        client = await self._get_client()
        payload = {"question": question, "mode": "hybrid", "top_k": top_k}

        try:
            response = await client.post(
                f"{self.base_url}/api/v1/query",
                json=payload,
                headers={
                    "Content-Type": "application/json",
                    "X-API-Key": "test-api-key"  # TODO: 生产环境应从配置读取
                },
            )
            response.raise_for_status()
            data = response.json()

            return {
                "has_answer": True,
                "answer": data.get("answer", ""),
                "confidence": data.get("confidence", 0.0),
                "sources": data.get("sources", []),
            }

        except Exception as e:
            print(f"[RAGClient] 调用失败: {e}")
            return {
                "has_answer": False,
                "error": str(e),
                "message": "知识服务暂时不可用，建议转人工",
                "confidence": 0.0,
            }
    
    async def health_check(self) -> HealthResponse:
        """检查RAG服务健康状态"""
        client = await self._get_client()
        
        try:
            response = await client.get(
                f"{self.base_url}/health",
                timeout=2.0
            )
            if response.status_code == 200:
                return HealthResponse(status="healthy", **response.json())
            return HealthResponse(status="degraded")
        except Exception:
            return HealthResponse(status="down")
    
    async def close(self):
        """关闭客户端连接"""
        if self._client:
            await self._client.aclose()
            self._client = None


# 全局客户端实例（单例模式）
_rag_client: Optional[RAGClient] = None


def get_rag_client() -> RAGClient:
    """获取RAG客户端单例"""
    global _rag_client
    if _rag_client is None:
        _rag_client = RAGClient()
    return _rag_client


async def close_rag_client():
    """关闭全局RAG客户端"""
    global _rag_client
    if _rag_client:
        await _rag_client.close()
        _rag_client = None
