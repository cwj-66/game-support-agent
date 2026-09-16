"""
RAG 服务 HTTP 客户端

外部知识库契约（自有 RAG / mock_rag 均需实现）：
  GET  {base}/health
  POST {base}/api/v1/retrieve
       body: {"question": str, "top_k": int}
       resp: {"sources": [{"text","source","page","score"}], "max_score": float, ...}

答案生成在 Agent 侧（knowledge_answer），不依赖 RAG 服务内的 LLM。
"""

from typing import Any, Optional

import httpx

from app.core.config import get_settings


class RAGClient:
    """RAG 服务 HTTP 客户端：只拉检索片段。"""

    def __init__(
        self,
        base_url: str | None = None,
        timeout: float = 10.0,
        api_key: str | None = None,
    ):
        settings = get_settings()
        self.base_url = (base_url or settings.RAG_SERVICE_URL).rstrip("/")
        self.timeout = timeout
        self.api_key = api_key if api_key is not None else settings.RAG_API_KEY
        self._client: Optional[httpx.AsyncClient] = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=self.timeout,
                limits=httpx.Limits(max_keepalive_connections=5, max_connections=10),
                trust_env=False,
            )
        return self._client

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["X-API-Key"] = self.api_key
        return headers

    async def retrieve(
        self, question: str, top_k: int = 10
    ) -> dict[str, Any]:
        """检索知识片段，返回 {sources, max_score, retrieve_mode}；失败时带 error。"""
        client = await self._get_client()
        payload = {"question": question, "top_k": top_k}

        try:
            response = await client.post(
                f"{self.base_url}/api/v1/retrieve",
                json=payload,
                headers=self._headers(),
            )
            response.raise_for_status()
            data = response.json()
            sources = data.get("sources") or []
            return {
                "sources": sources,
                "max_score": float(data.get("max_score", 0.0) or 0.0),
                "retrieve_mode": data.get("retrieve_mode", ""),
            }
        except Exception as e:
            print(f"[RAGClient] 检索失败: {e}")
            return {
                "sources": [],
                "max_score": 0.0,
                "error": str(e),
                "message": "知识服务暂时不可用，建议转人工",
            }

    async def query_knowledge(self, question: str, top_k: int = 10) -> dict:
        """检索片段并在本侧生成答案，返回 {has_answer, answer, confidence, sources}。"""
        from agent.tools.knowledge_answer import answer_from_sources

        retrieved = await self.retrieve(question, top_k=top_k)
        if retrieved.get("error"):
            return {
                "has_answer": False,
                "error": retrieved["error"],
                "message": retrieved.get("message", "知识服务暂时不可用，建议转人工"),
                "confidence": 0.0,
                "sources": [],
            }

        sources = retrieved.get("sources") or []
        if not sources:
            return {
                "has_answer": False,
                "answer": "",
                "confidence": 0.0,
                "sources": [],
                "message": "知识库未找到相关内容",
            }

        return await answer_from_sources(
            question,
            sources,
            max_score=float(retrieved.get("max_score", 0.0) or 0.0),
        )

    async def health_check(self) -> dict:
        """检查 RAG 服务健康状态"""
        client = await self._get_client()
        try:
            response = await client.get(
                f"{self.base_url}/health",
                timeout=2.0,
                headers=self._headers(),
            )
            if response.status_code == 200:
                return {"status": "healthy", **response.json()}
            return {"status": "degraded"}
        except Exception:
            return {"status": "down"}

    async def close(self):
        if self._client:
            await self._client.aclose()
            self._client = None
