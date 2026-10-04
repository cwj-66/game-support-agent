"""客服回复生成节点。"""

import json
import logging
import re
from typing import Dict, Any

from langchain_core.messages import SystemMessage, AIMessage, ToolMessage, HumanMessage

from ..state import AgentState
from ..prompts.system import CUSTOMER_SERVICE_PROMPT
from app.core.blocking import run_blocking
from app.core.llm import get_chat_model, llm_invoke, llm_stream
from app.core.config import get_settings

logger = logging.getLogger(__name__)
from langgraph.config import get_config
from ..events import emit_event
from ..tools.knowledge_answer import _quote_matches_source


def _same_language_quote(question: str, quote: str) -> bool:
    return bool(re.search(r"[\u3400-\u9fff]", question)) == bool(re.search(r"[\u3400-\u9fff]", quote))


async def _generate_text(llm, messages, streaming):
    """生成回复文本；模型失败且尚未输出任何片段时返回空串走兜底，已输出片段则抛出（不能从头重来）。"""
    emitted: list[str] = []

    def on_text(text: str) -> None:
        emitted.append(text)
        emit_event({"type": "delta", "text": text})

    try:
        if not streaming:
            result = await llm_invoke(llm, messages)
            return result.content or ""
        return await llm_stream(llm, messages, on_text)
    except Exception as exc:
        if emitted:
            raise
        logger.warning("generate LLM failed, using fallback reply: %s", type(exc).__name__)
        return ""


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
    try:
        streaming = bool(get_config().get("configurable", {}).get("public_stream"))
    except RuntimeError:
        streaming = False
    tokens_emitted = False

    if metadata.get("terminal_response"):
        final_response = metadata["terminal_response"]
    elif metadata.get("knowledge_terminal"):
        final_response = metadata["knowledge_terminal"]
    elif (state.get("tool_calls")
          and all(call.get("tool") == "check_ticket" for call in state["tool_calls"])
          and (pending_response := _pending_ticket_response(messages))):
        final_response = pending_response
    elif (isinstance(knowledge, dict) and knowledge.get("has_answer")
          and state.get("tool_calls")
          and all(call.get("tool") == "query_knowledge" for call in state["tool_calls"])):
        # Knowledge extraction establishes the facts; the dedicated model restores customer-service wording.
        grounded_answer = str(knowledge.get("answer") or "").strip()
        quote = str(knowledge.get("source_quote") or "").strip()
        if quote and _quote_matches_source(quote, knowledge.get("sources") or []):
            grounded_answer = quote
        if grounded_answer:
            settings = get_settings()
            llm = get_chat_model(model_name=settings.GENERATE_MODEL_NAME)
            final_response = await _generate_text(llm, [
                SystemMessage(content=CUSTOMER_SERVICE_PROMPT + "\n\n本轮是知识库咨询。下列已校验原文是唯一事实依据，可忠实翻译；保留其中所有关键前提、任务名、地点、宝箱类型和数值，不要删成一句泛泛的结论。只改善表达与排版，不补充任何依据外的流程、猜测或承诺。用两到四句或必要的简短步骤回答；无关活动副标题可省略，不要堆叠中英对照。依据可表述为「根据知识库记载」，不得宣称「官方资料」或「官方确认」。用用户的语言自然回答，最后加一句简短的继续咨询邀请。不要输出内部标签或来源校验过程。中文提问中的术语统一使用：Veluriyam Mirage=琉形蜃境；Secret Summer Paradise=秘密夏日乐园；The Black Nacre and the All-Devouring Kraken=黑珍珠与吞噬一切的克拉肯；Precious Chest=珍贵宝箱。这是译名表，不是额外事实；其他未知专有名词保留原文，禁止臆造译名。"),
                HumanMessage(content=f"用户提问：{state.get('user_query', '')}\n已核实的知识库答案：\n{grounded_answer}"),
            ], streaming)
            tokens_emitted = streaming and bool(final_response)
            metadata["reply_generation"] = {"mode": "customer_service_polish", "model": settings.GENERATE_MODEL_NAME}
            if not str(final_response).strip():
                final_response = grounded_answer
                if _same_language_quote(state.get("user_query", ""), "中文"):
                    final_response += "\n\n如果还有其他游戏问题，也可以继续问我。"
        else:
            final_response = "当前知识库没有找到足够依据，我无法确认这个问题的答案。"

    elif messages:
        settings = get_settings()
        llm = get_chat_model(model_name=settings.GENERATE_MODEL_NAME)

        final_response = await _generate_text(llm, [
            SystemMessage(content=CUSTOMER_SERVICE_PROMPT),
            *messages,
            HumanMessage(content=(
                f"请根据以上已经执行的工具结果和决策，完整回答玩家本轮问题：{state.get('user_query', '')}。"
                "直接输出给玩家的最终回复，明确告知查到的状态、原因或处理结果；"
                "不能只回复「好的」或说将要查询，查询已经完成。"
                "如有等待确认的操作，仍保留确认按钮说明，不宣称操作已经执行。"
            )),
        ], streaming)
        tokens_emitted = streaming and bool(final_response)

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
    if streaming and not tokens_emitted:
        # Verified source answers are emitted only after citation validation.
        emit_event({"type": "delta", "text": str(final_response)})

    ticket_id = state.get("ticket_id")
    if ticket_id:
        try:
            from app.repositories.database import update_ticket
            await run_blocking(update_ticket, ticket_id, agent_reply=final_response)
        except Exception:
            logger.warning("failed to store agent reply on ticket %s", ticket_id)

    return {
        "messages": [ai_message],
        "final_response": final_response,
        "metadata": metadata,
        "node_trace": ["generate"],
    }
