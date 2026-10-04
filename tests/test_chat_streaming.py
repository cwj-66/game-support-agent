from types import SimpleNamespace
from unittest.mock import patch, AsyncMock

import pytest

from agent.state import create_initial_state
from agent.nodes.generate import generate_response_node, _generate_text
from langchain_core.messages import HumanMessage, AIMessage, ToolMessage


@pytest.mark.asyncio
async def test_chinese_answer_is_not_replaced_by_english_source_quote():
    state = create_initial_state("s", "10001", "黑珍珠宣传海报怎么获得？")
    state["tool_calls"] = [{"tool": "query_knowledge"}]
    quote = 'One copy of "Black Nacre" Promo Poster can be obtained from a Chest in the Veluriyam Mirage.'
    answer = '可以从琉形蜃境的一个宝箱中获得一份“黑珍珠”宣传海报。'
    state["metadata"] = {"knowledge_result": {"has_answer": True, "answer": answer, "source_quote": quote, "sources": [{"text": quote}]}}
    llm = AsyncMock()
    llm.ainvoke.return_value = SimpleNamespace(content=answer)
    with patch("agent.nodes.generate.get_chat_model", return_value=llm):
        result = await generate_response_node(state)
    assert result["final_response"] == answer
    assert quote in llm.ainvoke.call_args.args[0][-1].content
    assert "客服" in llm.ainvoke.call_args.args[0][0].content


@pytest.mark.asyncio
async def test_generation_emits_only_visible_response_tokens():
    class Model:
        async def astream(self, messages):
            yield SimpleNamespace(content="您好", additional_kwargs={"reasoning_content": "private reasoning"})
            yield SimpleNamespace(content="！", additional_kwargs={})
    events = []
    with patch("agent.nodes.generate.emit_event", side_effect=events.append):
        result = await _generate_text(Model(), [], True)
    assert result == "您好！"
    assert events == [{"type": "delta", "text": "您好"}, {"type": "delta", "text": "！"}]


@pytest.mark.asyncio
async def test_business_polish_receives_final_user_instruction_and_tool_facts():
    state = create_initial_state("s", "10002", "帮我查一下账号状态")
    state["messages"] = [HumanMessage(content=state["user_query"]),
        ToolMessage(content='{"status":"banned","ban_reason":"使用外挂"}',
                    name="lookup_account", tool_call_id="lookup"),
        AIMessage(content="账号因使用外挂被封禁。")]
    llm = AsyncMock()
    llm.ainvoke.return_value = SimpleNamespace(content="账号因使用外挂被封禁。")
    with patch("agent.nodes.generate.get_chat_model", return_value=llm):
        result = await generate_response_node(state)
    sent = llm.ainvoke.call_args.args[0]
    assert isinstance(sent[-1], HumanMessage)
    assert "查询已经完成" in sent[-1].content
    assert any(isinstance(m, ToolMessage) and '"banned"' in m.content for m in sent)
    assert "外挂" in result["final_response"]
