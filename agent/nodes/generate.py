"""
客服回复生成节点
结合工具查询结果和客服提示词，生成最终用户回复
"""

from typing import Dict, Any

from langchain_core.messages import SystemMessage, HumanMessage, AIMessage

from ..state import AgentState
from ..prompts.system import CUSTOMER_SERVICE_PROMPT
from app.core.llm import get_chat_model


async def generate_response_node(state: AgentState) -> Dict[str, Any]:
    """
    生成最终回复节点

    结合用户问题和完整对话历史，用客服提示词生成最终回复
    """
    human_review = state.get("human_review")
    user_query = state.get("user_query", "")
    messages = state.get("messages", [])

    # 人工干预优先：OVERRIDE 或 MODIFY 直接使用人工内容
    if human_review and human_review.get("action") in ["OVERRIDE", "MODIFY"]:
        final_response = human_review.get("modified_content", "[人工处理完成]")

    elif messages:
        llm = get_chat_model()

        session_summary = state.get("session_summary")
        summary_messages = []
        if session_summary:
            summary_messages = [SystemMessage(content=f"【上一轮对话摘要】{session_summary}")]

        ai_result = await llm.ainvoke([
            SystemMessage(content=CUSTOMER_SERVICE_PROMPT),
            *summary_messages,
            HumanMessage(content=user_query),
            *messages,
        ])
        final_response = ai_result.content

    else:
        final_response = "抱歉，我暂时无法回答这个问题，建议联系人工客服。"

    ai_message = AIMessage(content=final_response)

    # 评估最终回复的置信度
    confidence = None
    if final_response and not (human_review and human_review.get("action") in ["OVERRIDE", "MODIFY"]):
        try:
            llm = get_chat_model()
            score_result = await llm.ainvoke([
                SystemMessage(content=(
                    "你是一个回复质量评估助手。"
                    "请根据以下用户问题和客服回复，评估回复的准确性和完整性，"
                    "返回一个0到1之间的置信度分数（如0.9表示非常确定，0.4表示不太确定）。"
                    "只输出一个纯数字，不要加任何文字。"
                )),
                HumanMessage(content=f"用户问题：{user_query}\n客服回复：{final_response}"),
            ])
            confidence = float(score_result.content.strip())
            confidence = max(0.0, min(1.0, confidence))
        except (ValueError, Exception):
            confidence = None

    metadata = state.get("metadata", {})
    metadata["confidence"] = confidence

    return {
        "messages": [ai_message],
        "final_response": final_response,
        "metadata": metadata,
    }
