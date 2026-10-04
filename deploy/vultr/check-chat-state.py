import asyncio
import json
import sqlite3
from agent.checkpointer import get_checkpointer, close_checkpointer
from langchain_core.messages import ToolMessage

async def main():
    con = sqlite3.connect('/app/data/game_support_docker.db')
    sessions = con.execute('SELECT thread_id, checkpoint_ns FROM checkpoints ORDER BY rowid DESC LIMIT 1').fetchall()
    cp = await get_checkpointer()
    for sid, ns in sessions:
        state = await cp.aget_tuple({'configurable':{'thread_id':sid, 'checkpoint_ns':ns}})
        value = state.checkpoint['channel_values']
        print('final_response_length',len(value.get('final_response','')))
        print('trace',value.get('node_trace'))
        for m in value.get('messages',[]):
            print('message',m.type,'content_type',type(m.content).__name__,'length',len(m.content),'tools',len(getattr(m,'tool_calls',[])))
            if isinstance(m,ToolMessage):
                print('tool_result',m.name,m.content[:1500])
    await close_checkpointer()
asyncio.run(main())
