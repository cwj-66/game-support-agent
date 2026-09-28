"""客服回复生成节点。"""

import json
from typing import Dict, Any

from langchain_core.messages import SystemMessage, AIMessage, ToolMessage

from ..state import AgentState
from ..prompts.system import CUSTOMER_SERVICE_PROMPT
from app.core.llm import get_chat_model
from app.core.config import get_settings


def _pending_ticket_response(messages: list) -> str | None:
    """对待处理工单直接使用数据库状态，避免润色时误写为处理中。"""
    for message in reversed(messages):
        if not isinstance(message, ToolMessage) or message.name != "check_ticket":
            continue
        try:
            data = json.loads(message.content)
        except (TypeError, ValueError):
            return None
        if not isinstance(data, dict):
            return None
        tickets = data.get("tickets")
        if tickets is None and data.get("found"):
            tickets = [data]
        if not tickets or not all(t.get("status") == "pending" for t in tickets):
            return None
        parts = []
        for ticket in tickets:
            part = f"工单 {ticket['ticket_id']} 当前状态为待处理"
            if ticket.get("title"):
                part += f"（{ticket['title']}）"
            reply = ticket.get("agent_reply")
            part += f"，客服回复：{reply}。" if reply else "，尚无客服回复。"
            parts.append(part)
        return "\n".join(parts)
    return None


async def generate_response_node(state: AgentState) -> Dict[str, Any]:
    """结合对话历史生成最终客服回复。"""
    messages = state.get("messages", [])
    metadata = state.get("metadata", {})
    knowledge = metadata.get("knowledge_result")

    if metadata.get("knowledge_terminal"):
        final_response = metadata["knowledge_terminal"]
    elif (state.get("tool_calls")
          and all(call.get("tool") == "check_ticket" for call in state["tool_calls"])
          and (pending_response := _pending_ticket_response(messages))):
        final_response = pending_response
    elif (isinstance(knowledge, dict) and knowledge.get("has_answer")
          and state.get("tool_calls")
          and all(call.get("tool") == "query_knowledge" for call in state["tool_calls"])):
        # 纯知识咨询直接使用知识工具的答案，避免润色模型添加来源外的步骤。
        final_response = str(knowledge.get("answer") or "").strip()
        quote = str(knowledge.get("source_quote") or "").strip()
        if quote and any(quote in str(src.get("text") or "") for src in knowledge.get("sources") or []):
            final_response = quote
        if not final_response:
            final_response = "当前知识库没有找到足够依据，我无法确认这个问题的答案。"

    elif messages:
        settings = get_settings()
        llm = get_chat_model(model_name=settings.GENERATE_MODEL_NAME)

        ai_result = await llm.ainvoke([
            SystemMessage(content=CUSTOMER_SERVICE_PROMPT),
            *messages,
        ])
        final_response = ai_result.content or ""

        if not str(final_response).strip():
            for msg in reversed(messages):
                if isinstance(msg, AIMessage) and msg.content and str(msg.content).strip():
                    final_response = msg.content
                    break
        if not str(final_response).strip():
            if state.get("human_offer"):
                final_response = (
                    "很抱歉没能为您解决问题。您可通过下方按钮确认是否转接人工客服，"
                    "也可以继续向我求助。"
                )
            elif state.get("ticket_offer"):
                final_response = (
                    "很抱歉没能为您解决问题。您可通过下方按钮确认是否创建工单，"
                    "也可以继续向我求助。"
                )
            else:
                final_response = "很抱歉没能为您解决问题，您可以继续向我求助。"

    else:
        final_response = "抱歉，我暂时无法回答这个问题，建议联系人工客服。"

    ai_message = AIMessage(content=final_response)

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
