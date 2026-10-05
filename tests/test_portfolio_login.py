import hashlib
import importlib.util
import sys
import threading
from pathlib import Path
import requests
from app.services import visitor_store

def test_portfolio_login_cookie_and_permanent_lock(tmp_path,monkeypatch):
    monkeypatch.setenv('DEMO_VISITOR_DB_PATH',str(tmp_path/'visitors.db'))
    monkeypatch.setenv('PORTFOLIO_PASSWORD_SALT',b'test-salt'.hex())
    monkeypatch.setenv('PORTFOLIO_PASSWORD_HASH',hashlib.pbkdf2_hmac('sha256',b'1234',b'test-salt',210000).hex())
    monkeypatch.setenv('DEMO_ACCESS_SECRET','test-only-signing-key')
    monkeypatch.setenv('PORTFOLIO_SECURE_COOKIE','0')
    monkeypatch.setitem(sys.modules,'visitor_store',visitor_store)
    path=Path(__file__).resolve().parents[1]/'deploy/portfolio/server.py'
    spec=importlib.util.spec_from_file_location('test_portal',path)
    portal=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(portal)
    server=portal.ThreadingHTTPServer(('127.0.0.1',0),portal.Handler)
    worker=threading.Thread(target=server.serve_forever,daemon=True);worker.start()
    base='http://127.0.0.1:'+str(server.server_port)
    headers={'Origin':base,'X-Portfolio-Request':'1','X-Real-IP':'test-ip'}
    try:
        client=requests.Session()
        assert client.post(base+'/auth/login',json={'password':'1234'},headers=headers).status_code==200
        assert client.get(base+'/auth/check').status_code==204
        ident=visitor_store.verify_visitor(client.cookies.get(visitor_store.VISITOR_COOKIE),'test-only-signing-key')
        assert ident
        client.post(base+'/auth/logout',headers=headers)
        assert client.cookies.get(visitor_store.VISITOR_COOKIE)
        headers['X-Real-IP']='other-test-ip'
        for _ in range(4):
            assert client.post(base+'/auth/login',json={'password':'0000'},headers=headers).status_code==401
        assert client.post(base+'/auth/login',json={'password':'0000'},headers=headers).status_code==403
        assert client.post(base+'/auth/login',json={'password':'1234'},headers=headers).status_code==403
        assert portal.VISITORS.state(ident)['blocked']==1
        assert client.get(base+'/auth/check').status_code==401
    finally:
        server.shutdown();server.server_close();worker.join()
