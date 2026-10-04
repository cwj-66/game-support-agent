import asyncio
import json
import sys
from app.core.config import settings
from app.rag import indexer
from app.rag.pipeline import RAGPipeline

async def main():
    assert settings.EMBED_PROVIDER == settings.RERANK_PROVIDER == 'siliconflow'
    indexer.init_settings()
    index = indexer.load_index()
    result = await RAGPipeline(index).retrieve_passages('黑珍珠宣传海报怎么获得？', top_k=1)
    assert result['sources'], 'No sources returned'
    text = result['sources'][0]['text']
    assert 'All-Devouring Kraken' in text and 'Precious Chest' in text, 'Missing prerequisite'
    print(json.dumps({'cloud_retrieval':'passed', 'source_count':len(result['sources']),
                      'local_torch_loaded': 'torch' in sys.modules,
                      'elapsed_ms':result['timing']['total_ms']}))

asyncio.run(main())
