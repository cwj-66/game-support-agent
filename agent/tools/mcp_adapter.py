"""
MCP 工具转 LangGraph 工具适配器
将MCP Server的工具封装为LangChain兼容的工具
"""

import json
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


class MCPKnowledgeTool(BaseTool):
    """
    MCP知识库查询工具适配器
    
    职责：
    1. 封装对MCP Server的query_knowledge工具调用
    2. 提供LangChain兼容的接口
    3. 处理输入输出转换
    
    TODO:
    - 实现真实的MCP客户端调用
    - 添加工具结果缓存
    - 支持批量查询
    """
    
    name: str = "query_knowledge"
    description: str = """
    查询游戏知识库，获取准确的游戏相关信息。
    当用户问题涉及具体游戏机制、活动规则、角色信息时，使用此工具查询。
    
    输入：用户查询问题（字符串）
    输出：JSON格式的知识检索结果，包含answer和confidence
    """
    args_schema: Type[BaseModel] = KnowledgeQueryInput
    
    def __init__(self, mcp_server_url: Optional[str] = None):
        super().__init__()
        self.mcp_server_url = mcp_server_url or "http://localhost:8001"
        self._mcp_client = None
    
    def _run(self, question: str) -> str:
        """
        同步执行工具（LangChain接口要求）
        
        注意：MCP工具主要使用异步，这里提供同步包装
        """
        import asyncio
        try:
            return asyncio.run(self._arun(question))
        except RuntimeError:
            # 如果已有事件循环，使用它
            loop = asyncio.get_event_loop()
            return loop.run_until_complete(self._arun(question))
    
    async def _arun(self, question: str) -> str:
        """
        异步执行工具查询，通过 SSE 协议连接 MCP 知识库服务器

        Args:
            question: 用户查询问题

        Returns:
            JSON格式的查询结果
        """
        sse_url = f"{self.mcp_server_url.rstrip('/')}/sse"

        try:
            async with sse_client(sse_url) as streams:
                async with ClientSession(*streams) as session:
                    await session.initialize()
                    result = await session.call_tool(
                        "query_knowledge",
                        arguments={"question": question},
                    )

            if getattr(result, "content", None):
                first_item = result.content[0]
                text = getattr(first_item, "text", None)
                if text:
                    return text

            return json.dumps(
                {
                    "has_answer": False,
                    "message": "MCP 服务返回内容为空",
                    "confidence": 0.0,
                },
                ensure_ascii=False,
            )
        except Exception as e:
            print(f"[MCPKnowledgeTool] 连接 MCP Server 失败: {e}")
            return json.dumps(
                {
                    "has_answer": False,
                    "message": "未找到相关知识，建议转人工",
                    "confidence": 0.0,
                },
                ensure_ascii=False,
            )
    
    async def _get_mcp_client(self):
        """获取或创建MCP客户端"""
        if self._mcp_client is None:
            # TODO: 初始化真实MCP客户端
            pass
        return self._mcp_client


def create_knowledge_tool(mcp_server_url: Optional[str] = None) -> MCPKnowledgeTool:
    """
    工厂函数：创建知识查询工具实例
    
    Args:
        mcp_server_url: MCP服务器地址
        
    Returns:
        配置好的MCPKnowledgeTool实例
    """
    return MCPKnowledgeTool(mcp_server_url=mcp_server_url)


# TODO: 未来扩展
# - 实现工具结果缓存（避免重复查询）
# - 支持多MCP Server负载均衡
# - 添加工具调用链路追踪
