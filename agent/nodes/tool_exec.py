"""
执行 MCP 工具节点
根据reasoning节点的决策，调用MCP工具获取知识
"""

import json
from datetime import datetime, timezone
from typing import Dict, Any
from langchain_core.messages import ToolMessage

from ..state import AgentState
from ..tools.mcp_adapter import create_knowledge_tool


# 工具执行节点，根据reasoning节点的决策，决定是否调用工具，调用MCP工具获取知识
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
    knowledge_tool = create_knowledge_tool()
    
    # 记录工具调用开始
    tool_call_record = {
        "tool": "query_knowledge",
        "input": user_query,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "status": "started"
    }
    
    try:
        # 调用MCP工具并解析JSON结果
        # MCPKnowledgeTool._arun 返回 JSON 字符串
        raw_result = await knowledge_tool._arun(user_query)
        knowledge_result = json.loads(raw_result)
        if not isinstance(knowledge_result, dict):
            raise ValueError("MCP工具返回结果不是JSON对象")
        
        # 更新调用记录
        tool_call_record["status"] = "completed"
        tool_call_record["output"] = knowledge_result
        tool_call_record["has_answer"] = bool(knowledge_result.get("has_answer", False))
        
        # 创建ToolMessage记录结果
        tool_message = ToolMessage(
            content=json.dumps(knowledge_result, ensure_ascii=False),
            name="query_knowledge",
            tool_call_id=f"call_{len(tool_calls)}"
        )

        # 更新状态
        return {
            "messages": [tool_message],
            "tool_calls": tool_calls + [tool_call_record],
            "metadata": {
                **state.get("metadata", {}),
                "knowledge_result": knowledge_result,
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

