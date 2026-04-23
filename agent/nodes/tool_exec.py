"""
执行 MCP 工具节点
根据reasoning节点的决策，调用MCP工具获取知识
"""

import json
from typing import Dict, Any
from langchain_core.messages import ToolMessage

from ..state import AgentState
from ..tools.mcp_adapter import MCPKnowledgeTool


async def tool_exec_node(state: AgentState) -> Dict[str, Any]:
    """
    工具执行节点：调用MCP知识库工具
    
    职责：
    1. 根据reasoning结果决定是否调用工具
    2. 调用query_knowledge工具获取知识
    3. 解析工具返回结果
    4. 将知识添加到状态中
    
    Args:
        state: 当前Agent状态
        
    Returns:
        状态更新字典，包含工具调用结果
        
    TODO:
    - 实现真实MCP工具调用
    - 添加工具调用重试和错误处理
    - 支持多个工具调用（并行）
    """
    user_query = state["user_query"]
    tool_calls = state.get("tool_calls", [])
    
    # 创建MCP知识工具实例
    knowledge_tool = MCPKnowledgeTool()
    
    # 记录工具调用开始
    tool_call_record = {
        "tool": "query_knowledge",
        "input": user_query,
        "timestamp": "2024-01-01T00:00:00",  # TODO: 使用真实时间
        "status": "started"
    }
    
    try:
        # 调用MCP工具
        # TODO: 接入真实的MCP Server
        # result = await knowledge_tool.ainvoke({"question": user_query})
        
        # 模拟工具调用结果（开发阶段占位）
        mock_result = {
            "has_answer": True,
            "answer": "完成主线任务、每日委托、开启宝箱、参与活动都可以获得原石。",
            "confidence": 0.92,
            "source": "faq_v1.json",
            "alternatives": []
        }
        
        # 更新调用记录
        tool_call_record["status"] = "completed"
        tool_call_record["output"] = mock_result
        tool_call_record["has_answer"] = mock_result["has_answer"]
        
        # 创建ToolMessage记录结果
        tool_message = ToolMessage(
            content=json.dumps(mock_result, ensure_ascii=False),
            name="query_knowledge",
            tool_call_id=f"call_{len(tool_calls)}"
        )
        
        # 更新状态
        return {
            "messages": [tool_message],
            "tool_calls": tool_calls + [tool_call_record],
            "metadata": {
                **state.get("metadata", {}),
                "knowledge_result": mock_result,
                "tool_exec_complete": True
            }
        }
        
    except Exception as e:
        # 工具调用失败
        tool_call_record["status"] = "failed"
        tool_call_record["error"] = str(e)
        
        # 创建错误消息
        error_message = ToolMessage(
            content=json.dumps({
                "has_answer": False,
                "error": str(e),
                "message": "知识库查询失败"
            }, ensure_ascii=False),
            name="query_knowledge",
            tool_call_id=f"call_{len(tool_calls)}"
        )
        
        return {
            "messages": [error_message],
            "tool_calls": tool_calls + [tool_call_record],
            "metadata": {
                **state.get("metadata", {}),
                "tool_error": str(e),
                "tool_exec_complete": False
            }
        }


async def execute_mcp_tool(
    tool_name: str, 
    params: Dict[str, Any],
    mcp_server_url: str
) -> Dict[str, Any]:
    """
    执行MCP工具（真实实现）
    
    通过SSE连接调用MCP Server的工具
    
    Args:
        tool_name: 工具名称
        params: 工具参数
        mcp_server_url: MCP服务器地址
        
    TODO:
    - 实现MCP客户端连接
    - 处理SSE流式响应
    - 添加超时控制
    """
    pass
