from concurrent.futures import ThreadPoolExecutor
from app.services.visitor_store import VisitorStore, sign_visitor, verify_visitor

def test_signed_visitor_cannot_be_replaced():
    value = sign_visitor('a'*32, 'test-secret')
    assert verify_visitor(value,'test-secret') == 'a'*32
    assert verify_visitor(value.replace('a'*32,'b'*32),'test-secret') is None

def test_fifth_failure_is_persistent_even_with_correct_password(tmp_path):
    path = tmp_path/'visitors.db'
    store = VisitorStore(path)
    store.ensure('visitor')
    for i in range(4):
        assert store.login_result('visitor',False) == {'blocked':False,'remaining':4-i}
    assert store.login_result('visitor',False)['blocked']
    restarted = VisitorStore(path)
    assert restarted.login_result('visitor',True)['blocked']
    assert restarted.reserve('visitor','turn') == 'blocked'

def test_success_resets_failures_and_ip_limit_expires(tmp_path):
    store = VisitorStore(tmp_path/'visitors.db')
    store.ensure('visitor')
    store.login_result('visitor',False)
    assert store.login_result('visitor',True)['remaining'] == 5
    for _ in range(5):
        assert store.ip_attempt('test-ip',100) == 0
    assert store.ip_attempt('test-ip',110) == 50
    assert store.ip_attempt('test-ip',161) == 0

def test_concurrent_quota_exactly_fifty_survives_restarts(tmp_path):
    path = tmp_path/'visitors.db'
    store = VisitorStore(path)
    store.ensure('visitor-a')
    with ThreadPoolExecutor(max_workers=8) as workers:
        results=list(workers.map(lambda i:store.reserve('visitor-a',str(i)),range(80)))
    assert results.count('accepted') == 50
    assert results.count('exhausted') == 30
    restarted=VisitorStore(path)
    assert restarted.state('visitor-a')['used'] == 50
    assert restarted.reserve('visitor-a','new') == 'exhausted'
    store.ensure('visitor-b')
    assert store.reserve('visitor-b','first') == 'accepted'
    assert store.reserve('visitor-b','first') == 'duplicate'
    assert store.state('visitor-b')['used'] == 1
