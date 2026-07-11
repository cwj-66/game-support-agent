"""
客服回复生成节点
结合工具查询结果和客服提示词，生成最终用户回复
"""

from typing import Dict, Any

from langchain_core.messages import SystemMessage, AIMessage

from ..state import AgentState
from ..prompts.system import CUSTOMER_SERVICE_PROMPT
from app.core.llm import get_chat_model
from app.core.config import get_settings


async def generate_response_node(state: AgentState) -> Dict[str, Any]:
    """
    生成最终回复节点

    结合用户问题和完整对话历史，用客服提示词生成最终回复
    """
    messages = state.get("messages", [])

    if messages:
        settings = get_settings()
        llm = get_chat_model(model_name=settings.GENERATE_MODEL_NAME)

        # messages 已含完整会话原文（Human / AI / Tool），不再重复追加 user_query
        ai_result = await llm.ainvoke([
            SystemMessage(content=CUSTOMER_SERVICE_PROMPT),
            *messages,
        ])
        final_response = ai_result.content

    else:
        final_response = "抱歉，我暂时无法回答这个问题，建议联系人工客服。"

    ai_message = AIMessage(content=final_response)

    metadata = state.get("metadata", {})

    # 若有关联工单，回写 agent_reply（数据库不可用时静默跳过）
    ticket_id = state.get("ticket_id")
    if ticket_id:
        try:
            from app.repositories.database import update_ticket
            update_ticket(ticket_id, agent_reply=final_response)
        except Exception:
            pass

    return {
        "messages": [ai_message],
        "final_response": final_response,
        "metadata": metadata,
        "node_trace": ["generate"],
    }
