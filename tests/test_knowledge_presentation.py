from pathlib import Path
import importlib.util
from unittest.mock import AsyncMock, patch
from langchain_core.messages import AIMessage
import pytest

spec = importlib.util.spec_from_file_location('context_window', Path(__file__).resolve().parents[2] / 'enterprise-rag/app/rag/context_window.py')
context = importlib.util.module_from_spec(spec)
spec.loader.exec_module(context)

def test_article_expansion_recovers_prerequisite_without_crossing_next_article():
    hit = '# Poster\nObtained from a chest.\n## Info'
    source = hit + '\n## How to Obtain\nComplete the named quest first.\n# Other item\nOther rules.'
    expanded = context.expand_markdown_article(hit, source)
    assert 'Complete the named quest first.' in expanded
    assert 'Other rules' not in expanded

def test_article_expansion_preserves_pdf_and_unknown_or_oversized_context():
    assert context.expand_markdown_article('Page 3 text', '# Poster\nText') == 'Page 3 text'
    assert context.expand_markdown_article('# Unknown\nText', '# Poster\nText') == '# Unknown\nText'
    assert context.expand_markdown_article('# Poster\nIntro', '# Poster\n' + 'x' * 7000) == '# Poster\nIntro'

@pytest.mark.asyncio
async def test_knowledge_polish_preserves_full_grounded_answer_and_uses_generation_model():
    from agent.nodes.generate import generate_response_node
    from agent.state import create_initial_state
    from app.core.config import get_settings
    state = create_initial_state('s', '10001', '怎么获得宣传海报？')
    state['tool_calls'] = [{'tool': 'query_knowledge'}]
    answer = '完成活动世界任务后，从珍贵宝箱获得。'
    state['metadata'] = {'knowledge_result': {'has_answer': True, 'answer': answer, 'source_quote': 'Obtained from a chest.', 'sources': []}}
    model = AsyncMock()
    model.ainvoke.return_value = AIMessage(content=answer + '如果还有其他游戏问题，也可以继续问我。')
    with patch('agent.nodes.generate.get_chat_model', return_value=model) as factory:
        result = await generate_response_node(state)
    factory.assert_called_once_with(model_name=get_settings().GENERATE_MODEL_NAME)
    assert answer in model.ainvoke.call_args.args[0][-1].content
    assert '其他游戏问题' in result['final_response']
    assert result['metadata']['reply_generation']['mode'] == 'customer_service_polish'
