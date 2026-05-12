"""
MCP 工具转 LangGraph 工具适配器
将MCP Server的工具封装为LangChain兼容的工具
"""

import json
import os
from typing import Type, Optional

from pydantic import BaseModel, Field
from langchain.tools import BaseTool
from mcp.client.sse import sse_client
from mcp.client.session import ClientSession


class KnowledgeQueryInput(BaseModel):
    """知识查询工具输入参数"""
    question: str = Field(
        ...,
        description="用户要查询的问题，例如'原神如何获得原石？'"
    )


def _fallback(message: str) -> str:
    """返回统一的降级 JSON，避免 LangGraph 崩溃"""
    return json.dumps(
        {
            "has_answer": False,
            "message": message,
            "confidence": 0.0,
            "_health": {"ok": False, "confidence": 0.0, "message": message},
        },
        ensure_ascii=False,
    )


def _inject_health(json_str: str) -> str:
    """向工具返回的 JSON 注入 _health 字段，供升等检测器通用判断"""
    try:
        data = json.loads(json_str)
    except (json.JSONDecodeError, ValueError):
        return json_str
    has_answer = data.get("has_answer", True)
    confidence = data.get("confidence")
    data["_health"] = {
        "ok": has_answer,
        "confidence": confidence,
        "message": None if has_answer else "知识库未找到相关答案",
    }
    return json.dumps(data, ensure_ascii=False)


class MCPKnowledgeTool(BaseTool):
    """
    MCP知识库查询工具适配器

    职责：
    1. 封装对MCP Server的query_knowledge工具调用
    2. 提供LangChain兼容的接口
    3. 处理输入输出转换
    """

    # ── 基础定义 ─────────────────────────────────────────────
    name: str = "query_knowledge"
    description: str = (
        "查询游戏知识库，获取准确的游戏相关信息。"
        "当用户问题涉及具体游戏机制、活动规则、角色信息时，使用此工具查询。"
        "输入：用户查询问题（字符串）；"
        "输出：JSON格式的知识检索结果，包含answer和confidence。"
    )
    args_schema: Type[BaseModel] = KnowledgeQueryInput

    # Pydantic 类字段（BaseTool 本质是 BaseModel，必须在类级别声明）
    mcp_server_url: str = "http://localhost:8001"

    def _run(self, question: str) -> str:
        """同步包装，供非 async 环境调用"""
        import asyncio
        try:
            return asyncio.run(self._arun(question))
        except RuntimeError:
            loop = asyncio.get_event_loop()
            return loop.run_until_complete(self._arun(question))

    async def _arun(self, question: str) -> str:
        """
        异步执行：通过 SSE 协议连接 MCP 知识库服务器并查询

        Args:
            question: 用户查询问题

        Returns:
            JSON格式的查询结果
        """
        sse_url = f"{self.mcp_server_url.rstrip('/')}/sse"

        # ── 安全连接：注入 API Key 请求头 ───────────────────
        api_key = os.getenv("MCP_API_KEY", "")
        headers = {"X-MCP-API-Key": api_key} if api_key else {}

        try:
            async with sse_client(sse_url, headers=headers) as streams:
                async with ClientSession(*streams) as session:
                    # ── 握手 ────────────────────────────────
                    await session.initialize()

                    # ── 调用工具 ─────────────────────────────
                    result = await session.call_tool(
                        "query_knowledge",
                        arguments={"question": question},
                    )

            # ── 结果提取 ─────────────────────────────────────
            if getattr(result, "content", None):
                for item in result.content:
                    text = getattr(item, "text", None)
                    if text:
                        return _inject_health(text)

            return _fallback("MCP 服务返回内容为空")

        # ── 安全降级：分层捕获，不让异常崩溃 LangGraph ────────
        except ConnectionRefusedError:
            print(f"[MCPKnowledgeTool] 连接被拒绝，MCP Server 未启动: {sse_url}")
            return _fallback("知识服务连接失败（连接被拒绝），建议转人工")

        except TimeoutError:
            print(f"[MCPKnowledgeTool] 连接超时: {sse_url}")
            return _fallback("知识服务连接超时，建议稍后重试或转人工")

        except Exception as e:
            err_str = str(e).lower()
            if "401" in err_str or "unauthorized" in err_str or "api key" in err_str:
                print(f"[MCPKnowledgeTool] 认证失败（API Key 错误）: {e}")
                return _fallback("知识服务认证失败，请检查 MCP_API_KEY 配置")
            print(f"[MCPKnowledgeTool] 未知错误 [{type(e).__name__}]: {e}")
            return _fallback(f"知识服务发生未知错误，建议转人工")


def create_knowledge_tool(mcp_server_url: Optional[str] = None) -> MCPKnowledgeTool:
    """
    工厂函数：创建知识查询工具实例

    Args:
        mcp_server_url: MCP服务器地址

    Returns:
        配置好的MCPKnowledgeTool实例
    """
    url = mcp_server_url or os.getenv("MCP_SERVER_URL", "http://localhost:8001")
    return MCPKnowledgeTool(mcp_server_url=url)
