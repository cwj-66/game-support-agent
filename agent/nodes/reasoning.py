"""
LLM 自主决策节点
分析用户意图，决定是否需要调用工具，评估置信度
"""

import json
from typing import Dict, Any
from langchain_core.messages import AIMessage, SystemMessage

from ..state import AgentState
from ..prompts.system import GAME_SUPPORT_SYSTEM_PROMPT, build_reasoning_prompt


class ReasoningResult:
    """推理结果数据结构"""
    def __init__(
        self,
        intent: str,
        need_tool: bool,
        confidence: float,
        has_sensitive: bool,
        sensitive_words: list,
        reasoning: str
    ):
        self.intent = intent
        self.need_tool = need_tool
        self.confidence = confidence
        self.has_sensitive = has_sensitive
        self.sensitive_words = sensitive_words
        self.reasoning = reasoning


async def reasoning_node(state: AgentState, llm) -> Dict[str, Any]:
    """
    推理节点：分析用户意图并决策
    
    这是Agent的第一个节点，负责：
    1. 理解用户问题
    2. 评估是否需要调用知识库工具
    3. 检测敏感内容
    4. 输出置信度评分
    
    Args:
        state: 当前Agent状态
        llm: LangChain LLM实例
        
    Returns:
        状态更新字典
        
    TODO: 
    - 接入真实的LLM
    - 添加工具选择逻辑（未来可能有多个工具）
    - 优化敏感词检测（与detector模块复用逻辑）
    """
    user_query = state["user_query"]
    messages = state["messages"]
    
    # 构建推理提示词
    reasoning_prompt = build_reasoning_prompt(user_query, messages)
    
    # 构造LLM输入
    llm_messages = [
        SystemMessage(content=GAME_SUPPORT_SYSTEM_PROMPT),
        *messages,
        # 添加推理指令
        ("user", reasoning_prompt)
    ]
    
    # 调用LLM进行推理
    # TODO: 接入真实LLM
    # response = await llm.ainvoke(llm_messages)
    # 模拟推理结果（开发阶段占位）
    mock_result = ReasoningResult(
        intent="查询游戏机制",
        need_tool=True,  # 假设需要查询知识库
        confidence=0.75,
        has_sensitive=False,
        sensitive_words=[],
        reasoning="用户询问具体游戏机制，需要查询知识库获取准确信息"
    )
    
    # 将推理结果存入metadata
    reasoning_data = {
        "intent": mock_result.intent,
        "need_tool": mock_result.need_tool,
        "confidence": mock_result.confidence,
        "has_sensitive": mock_result.has_sensitive,
        "sensitive_words": mock_result.sensitive_words,
        "reasoning": mock_result.reasoning,
        "node": "reasoning"
    }
    
    # 更新metadata
    metadata = state.get("metadata", {})
    metadata["reasoning"] = reasoning_data
    
    # 构建AI消息记录推理结果
    ai_message = AIMessage(
        content=f"[推理] 意图：{mock_result.intent}，需要工具：{mock_result.need_tool}"
    )
    
    return {
        "messages": [ai_message],
        "metadata": metadata,
        # 标记是否需要工具调用（用于条件路由）
        "_need_tool": mock_result.need_tool
    }


async def analyze_intent_llm(llm, messages, user_query: str) -> ReasoningResult:
    """
    使用LLM分析意图（真实实现时的函数）
    
    TODO: 
    - 实现结构化输出（使用PydanticOutputParser）
    - 处理LLM返回JSON解析失败的情况
    - 添加重试逻辑
    """
    pass
