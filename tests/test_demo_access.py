import hashlib
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from app.services import demo_access as access
from app.api.deps import CurrentPlayer, require_reviewer_token

@pytest.fixture
def client(monkeypatch):
    salt = b'test-salt'
    monkeypatch.setenv('DEMO_ACCESS_PASSWORD_HASH', salt.hex() + ':' + hashlib.pbkdf2_hmac('sha256', b'test-password', salt, 310000).hex())
    monkeypatch.setenv('DEMO_ACCESS_SECRET', 'test-only-signing-key-not-for-production')
    access._attempts.clear()
    monkeypatch.setattr(access, "_get_rate_redis", AsyncMock(return_value=None))
    app = FastAPI()
    app.add_middleware(access.DemoAccessMiddleware)
    app.include_router(access.router)
    @app.post('/api/v1/human/review/test')
    def reviewer(token=Depends(require_reviewer_token)):
        return {'reviewer': token}
    return TestClient(app)


def test_gate_blocks_direct_and_default_reviewer_requests(client):
    assert client.post('/api/v1/human/review/test', headers={'X-Reviewer-Token': 'dev'}).status_code == 401
    assert client.get('/api/v1/demo/players').status_code == 401
    assert not client.get('/api/v1/access/status').json()['authenticated']


def test_password_grants_server_side_reviewer_access(client):
    assert client.post('/api/v1/access/session', json={'password': 'wrong'}).status_code == 401
    response = client.post('/api/v1/access/session', json={'password': 'test-password'})
    assert response.status_code == 200
    assert 'HttpOnly' in response.headers['set-cookie']
    assert client.get('/api/v1/access/status').json()['authenticated']
    assert client.post('/api/v1/human/review/test').json() == {'reviewer': 'demo_reviewer'}
    assert client.post('/api/v1/human/review/test', headers={'Origin': 'http://untrusted.example'}).status_code == 403


def test_forged_cookie_and_bruteforce_rejected(client):
    client.cookies.set(access.COOKIE, 'forged')
    assert client.post('/api/v1/human/review/test').status_code == 401
    for _ in range(10):
        assert client.post('/api/v1/access/session', json={'password': 'wrong'}).status_code == 401
    assert client.post('/api/v1/access/session', json={'password': 'wrong'}).status_code == 429


@pytest.mark.asyncio
async def test_end_conversation_enforces_ownership_and_closes_human_session():
    from fastapi import HTTPException
    from app.api.v1.chat import EndConversationRequest, end_conversation
    player = CurrentPlayer(user_id='10001')
    with pytest.raises(HTTPException) as error:
        await end_conversation(EndConversationRequest(session_id='10002_test'), player)
    assert error.value.status_code == 403
    with patch('app.api.v1.chat.is_human_mode', new=AsyncMock(return_value=True)), patch('app.api.v1.chat.close_human_session', new=AsyncMock()) as close:
        result = await end_conversation(EndConversationRequest(session_id='10001_test'), player)
    close.assert_awaited_once_with('10001_test')
    assert result['status'] == 'ended'


@pytest.mark.asyncio
async def test_manual_ticket_update_is_recorded_as_human_review():
    from app.api.v1.ticket import update_ticket_detail
    from app.models.ticket import Ticket, TicketUpdate
    ticket = Ticket(ticket_id="test", player_uid="10001", title="test", description="test")
    with patch('app.api.v1.ticket.get_ticket', return_value=ticket), patch('app.api.v1.ticket.update_ticket', return_value=ticket) as update:
        await update_ticket_detail("test", TicketUpdate(status="resolved", reviewer_id="admin_001"), "demo_reviewer")
    assert update.call_args.kwargs['human_reviewed'] is True


@pytest.mark.asyncio
async def test_rate_limit_uses_redis_and_returns_retry_after(monkeypatch):
    redis = AsyncMock()
    redis.eval.return_value = 11
    redis.ttl.return_value = 42
    monkeypatch.setattr(access, "_get_rate_redis", AsyncMock(return_value=redis))
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as error:
        await access._reserve_attempt("test-ip")
    assert error.value.status_code == 429
    assert error.value.headers["Retry-After"] == "42"
    redis.eval.assert_awaited_once()
