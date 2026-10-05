"""基于检索片段生成知识库答案。"""

from __future__ import annotations

import re
import unicodedata
import json
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage

from app.core.config import get_settings
from app.core.llm import get_chat_model, llm_invoke

def verified_knowledge_history(messages: list) -> list:
    """保留原始审计记录，但不让失败检索的候选答案进入后续模型上下文。"""
    safe = []
    for message in messages:
        if isinstance(message, ToolMessage) and message.name == "query_knowledge":
            try:
                result = json.loads(message.content)
            except (TypeError, ValueError):
                result = None
            if isinstance(result, dict) and result.get("has_answer") is False:
                message = message.model_copy(update={"content": json.dumps({
                    "has_answer": False,
                    "message": "该次检索未通过证据校验，没有可确认的答案。后续追问需要重新检索，不能宣称已经查实。",
                }, ensure_ascii=False)})
        safe.append(message)
    return safe


SYSTEM_PROMPT = """You are an enterprise knowledge-base assistant.
Rules:
- Answer ONLY using the "Retrieved passages" section. Do not use outside knowledge.
- If the passages are insufficient to answer, say clearly that the information is not in the provided sources, and briefly say what the passages do contain.
- For how-to/acquisition questions, include every stated prerequisite, named quest, location and item/chest type from the relevant detailed instructions. Do not stop at a short introduction if a more complete "How to Obtain" passage is present.
- Do not fabricate citations, page numbers, or facts.
- Project terminology translations (vocabulary only, not additional facts): Veluriyam Mirage = 琉形蜃境; Secret Summer Paradise = 秘密夏日乐园; The Black Nacre and the All-Devouring Kraken = 黑珍珠与吞噬一切的克拉肯; Precious Chest = 珍贵宝箱. Use these Chinese names for Chinese questions; preserve other proper names unless the passages or question establish their translation.
- You MUST answer in the same language as the user's question. Never switch languages regardless of the passages' language."""

LANGUAGE_CONSTRAINT = (
    "\n\nYou MUST answer in the EXACT same language as the 'User question' above. "
    "Do NOT switch languages."
)

QUOTE_FORMAT_INSTRUCTION = (
    "\n\nCRITICAL: Locate the EXACT sentence(s) in the passages that answer the question. "
    "Copy ONLY those key sentences into <QUOTE> tags — do NOT copy entire paragraphs, "
    "markdown tables, images, or formatting. Include the complete relevant prerequisite sentence when present, not merely an introductory sentence. Quote briefly.\n"
    "If the passages do NOT contain the answer, output <QUOTE></QUOTE> (empty).\n"
    "Then write your answer in <ANSWER> tags. "
    "You MUST close every tag: <QUOTE>...</QUOTE> and <ANSWER>...</ANSWER>."
)


def _format_context(sources: list[dict[str, Any]]) -> str:
    parts: list[str] = []
    for i, src in enumerate(sources, start=1):
        text = (src.get("text") or "").strip()
        name = src.get("source") or None
        page = src.get("page")
        parts.append(f"[{i}] (source={name!r}, page={page!r})\n{text}")
    return "\n\n".join(parts)


def _parse_quote_answer(raw_text: str) -> tuple[str, str]:
    quote_match = re.search(
        r"<QUOTE>\s*(.*?)\s*</QUOTE>", raw_text, re.DOTALL | re.IGNORECASE
    )
    answer_match = re.search(
        r"<ANSWER>\s*(.*?)\s*</ANSWER>", raw_text, re.DOTALL | re.IGNORECASE
    )
    if quote_match and answer_match:
        return quote_match.group(1).strip(), answer_match.group(1).strip()

    loose_quote = re.search(
        r"<QUOTE>\s*(.+?)(?:</QUOTE>|$)", raw_text, re.DOTALL | re.IGNORECASE
    )
    loose_answer = re.search(
        r"<ANSWER>\s*(.+?)(?:</ANSWER>|$)", raw_text, re.DOTALL | re.IGNORECASE
    )
    source_quote = loose_quote.group(1).strip() if loose_quote else ""
    answer = loose_answer.group(1).strip() if loose_answer else ""
    if not answer:
        answer = re.sub(
            r"</?(?:QUOTE|ANSWER)\s*>", "", raw_text, flags=re.IGNORECASE
        ).strip()
    return source_quote, answer


def _max_score(sources: list[dict[str, Any]], fallback: float = 0.0) -> float:
    scores = [
        float(s["score"])
        for s in sources
        if s.get("score") is not None
    ]
    if scores:
        return max(scores)
    return float(fallback or 0.0)


def _quote_matches_source(quote: str, sources: list[dict[str, Any]]) -> bool:
    """PDF 换行和兼容字形不应使原文引用校验失败。"""
    if not quote.strip():
        return False
    normalized_quote = re.sub(r"\s+", "", unicodedata.normalize("NFKC", quote))
    return any(
        normalized_quote in re.sub(
            r"\s+", "", unicodedata.normalize("NFKC", str(src.get("text") or ""))
        )
        for src in sources
    )


async def answer_from_sources(
    question: str,
    sources: list[dict[str, Any]],
    *,
    max_score: float = 0.0,
) -> dict[str, Any]:
    """依据检索片段生成答案；无片段时直接返回无结果。"""
    if not sources:
        return {
            "has_answer": False,
            "answer": "",
            "confidence": 0.0,
            "source_quote": "",
            "sources": [],
        }

    context = _format_context(sources)
    user_content = (
        f"User question:\n{question}\n\n"
        f"Retrieved passages:\n{context if context.strip() else '(no passages retrieved)'}\n\n"
        "Answer based only on the passages above."
        f"{LANGUAGE_CONSTRAINT}"
        f"{QUOTE_FORMAT_INSTRUCTION}"
    )

    settings = get_settings()
    llm = get_chat_model(model_name=settings.REASONING_MODEL_NAME)
    result = await llm_invoke(llm, [
        SystemMessage(content=SYSTEM_PROMPT),
        HumanMessage(content=user_content),
    ])
    raw_text = (result.content or "") if result else ""
    source_quote, answer = _parse_quote_answer(str(raw_text))
    quote_supported = _quote_matches_source(source_quote, sources)

    raw_confidence = _max_score(sources, max_score)
    if not quote_supported:
        confidence = min(raw_confidence, 0.49)
    else:
        confidence = min(raw_confidence, 1.0)

    return {
        "has_answer": bool(answer) and quote_supported and confidence >= 0.3,
        "answer": answer if quote_supported else "",
        "confidence": confidence,
        "source_quote": source_quote if quote_supported else "",
        "sources": sources,
    }
