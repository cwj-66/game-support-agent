"""
知识库查询工具
通过 HTTP 直接调用 RAG 服务，不再依赖 MCP 协议
"""

import json
import os
from typing import Type, Optional

from pydantic import BaseModel, Field
from langchain.tools import BaseTool

from .rag_client import RAGClient


class KnowledgeQueryInput(BaseModel):
    """知识查询工具输入参数"""
    question: str = Field(
        ...,
        description="用户要查询的问题，例如'原神如何获得原石？'"
    )


RAG_CONFIDENCE_THRESHOLD = 0.5


def _fallback(message: str) -> str:
    """返回统一的降级 JSON，避免 LangGraph 崩溃"""
    return json.dumps(
        {
            "has_answer": False,
            "message": message,
            "confidence": 0.0,
            "_health": {
                "ok": False,
                "confidence": 0.0,
                "needs_escalation": True,
                "message": message,
            },
        },
        ensure_ascii=False,
    )


def _inject_health(json_str: str) -> str:
    """向工具返回的 JSON 注入 _health 字段，供升等检测器和 tool_exec 通用判断"""
    try:
        data = json.loads(json_str)
    except (json.JSONDecodeError, ValueError):
        return json_str
    has_answer = data.get("has_answer", True)
    confidence = data.get("confidence")
    needs_escalation = (
        not has_answer
        or (confidence is not None and confidence < RAG_CONFIDENCE_THRESHOLD)
    )
    data["_health"] = {
        "ok": not needs_escalation,
        "confidence": confidence,
        "needs_escalation": needs_escalation,
        "message": (
            None
            if not needs_escalation
            else (
                "知识库未找到相关答案"
                if not has_answer
                else f"知识库检索置信度过低（{confidence:.2f} < {RAG_CONFIDENCE_THRESHOLD}）"
            )
        ),
    }
    return json.dumps(data, ensure_ascii=False)


class KnowledgeTool(BaseTool):
    """
    知识库查询工具

    通过 HTTP 直接调用 RAG 服务查询游戏知识库。
    """

    name: str = "query_knowledge"
    description: str = (
        "查询内部知识库，获取准确的游戏及客服相关信息。"
        "覆盖范围：游戏攻略/机制/活动、账号操作（注销/换绑/实名）、封号申诉、充值退款、投诉处理等。"
        "绝大多数用户问题都应优先使用此工具查询，包括封号、充值、退款等敏感问题。"
        "输入：用户查询问题（字符串）；"
        "输出：JSON格式的知识检索结果，包含answer和confidence。"
    )
    args_schema: Type[BaseModel] = KnowledgeQueryInput

    rag_service_url: str = "http://localhost:8000"

    def _run(self, question: str) -> str:
        import asyncio
        try:
            return asyncio.run(self._arun(question))
        except RuntimeError:
            loop = asyncio.get_event_loop()
            return loop.run_until_complete(self._arun(question))

    async def _arun(self, question: str) -> str:
        """通过 HTTP 直接调用 RAG 服务查询知识库"""
        client = RAGClient(base_url=self.rag_service_url)

        try:
            result = await client.query_knowledge(question)
        except ConnectionRefusedError:
            print(f"[KnowledgeTool] RAG 服务连接被拒绝: {self.rag_service_url}")
            return _fallback("知识服务连接失败（连接被拒绝），建议转人工")
        except TimeoutError:
            print(f"[KnowledgeTool] RAG 服务连接超时: {self.rag_service_url}")
            return _fallback("知识服务连接超时，建议稍后重试或转人工")
        except Exception as e:
            print(f"[KnowledgeTool] 未知错误 [{type(e).__name__}]: {e}")
            return _fallback(f"知识服务发生未知错误，建议转人工")
        finally:
            await client.close()

        result_str = json.dumps(result, ensure_ascii=False)
        return _inject_health(result_str)


def create_knowledge_tool(rag_service_url: Optional[str] = None) -> KnowledgeTool:
    """工厂函数：创建知识查询工具实例"""
    url = rag_service_url or os.getenv("RAG_SERVICE_URL", "http://localhost:8000")
    return KnowledgeTool(rag_service_url=url)
