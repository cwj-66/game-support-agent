"""
RAG服务 HTTP 客户端
直接调用 enterprise-rag 服务的 HTTP API
"""

import httpx
from typing import Optional


class RAGClient:
    """RAG服务 HTTP 客户端，封装对 RAG 服务的查询请求"""

    def __init__(
        self,
        base_url: str = "http://localhost:8000",
        timeout: float = 10.0,
    ):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._client: Optional[httpx.AsyncClient] = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=self.timeout,
                limits=httpx.Limits(max_keepalive_connections=5, max_connections=10),
                trust_env=False,
            )
        return self._client

    async def query_knowledge(self, question: str, top_k: int = 3) -> dict:
        """查询RAG知识库，返回 {has_answer, answer, confidence, sources}"""
        client = await self._get_client()
        payload = {"question": question, "mode": "hybrid", "top_k": top_k}

        try:
            response = await client.post(
                f"{self.base_url}/api/v1/query",
                json=payload,
                headers={"Content-Type": "application/json"},
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

    async def health_check(self) -> dict:
        """检查RAG服务健康状态"""
        client = await self._get_client()
        try:
            response = await client.get(f"{self.base_url}/health", timeout=2.0)
            if response.status_code == 200:
                return {"status": "healthy", **response.json()}
            return {"status": "degraded"}
        except Exception:
            return {"status": "down"}

    async def close(self):
        if self._client:
            await self._client.aclose()
            self._client = None
