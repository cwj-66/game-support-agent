import os
import secrets
from functools import lru_cache
import jwt
from fastapi import HTTPException
from app.core.blocking import run_blocking
from app.services.visitor_store import VisitorStore

def managed():
    return os.getenv('DEMO_VISITOR_REQUIRED') == '1'

@lru_cache(maxsize=4)
def store(path):
    return VisitorStore(path)

def get_store():
    return store(os.environ.get('DEMO_VISITOR_DB_PATH', '/app/data/demo-visitors.sqlite3'))

def visitor_claim(request):
    try:
        payload = jwt.decode(request.cookies.get('gsa_demo_access', ''), os.environ['DEMO_ACCESS_SECRET'],
                             algorithms=['HS256'], audience='game-support-demo',
                             options={'require': ['exp','sub','vid']})
        return payload['vid'] if payload['sub']=='demo-reviewer' else None
    except (jwt.PyJWTError, KeyError):
        return None

async def quota_state(request):
    ident = visitor_claim(request)
    if not ident:
        raise HTTPException(401, '请从作品集首页重新登录')
    try:
        state = await run_blocking(get_store().state, ident)
    except Exception:
        raise HTTPException(503, '访问额度服务暂时不可用，请稍后再试')
    if not state or state['blocked']:
        raise HTTPException(403, '此访客编号已停用，请联系作品集作者')
    return {'limit': 50, 'used': state['used'], 'remaining': max(0,50-state['used'])}

async def reserve_chat_quota(request, session_id, request_id):
    if not managed():
        return
    ident = visitor_claim(request)
    if not ident:
        raise HTTPException(401, '请从作品集首页重新登录')
    try:
        result = await run_blocking(get_store().reserve, ident, session_id+':'+(request_id or secrets.token_hex(16)))
    except Exception:
        raise HTTPException(503, '访问额度服务暂时不可用，请稍后再试')
    if result == 'blocked':
        raise HTTPException(403, '此访客编号已停用，请联系作品集作者')
    if result == 'exhausted':
        raise HTTPException(429, '对话体验额度已用完，请联系作品集作者')
    if result == 'duplicate':
        raise HTTPException(409, '此请求已经受理，请查看已有回复或发送新的问题')
