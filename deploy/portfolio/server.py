"""Private portfolio, served on loopback behind Nginx. Python 3.10+."""
import hashlib
import base64
import hmac
import json
import mimetypes
import os
import secrets
import threading
import time
from visitor_store import VisitorStore, VISITOR_COOKIE, sign_visitor, verify_visitor
from collections import deque
from http.cookies import SimpleCookie, CookieError
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent / 'public'
PASSWORD_HASH = os.environ['PORTFOLIO_PASSWORD_HASH']
SALT = bytes.fromhex(os.environ['PORTFOLIO_PASSWORD_SALT'])
SECURE = os.environ.get('PORTFOLIO_SECURE_COOKIE', '1') == '1'
SESSION_TTL = 8 * 3600
SESSIONS = {}
ATTEMPTS = {}
LOCK = threading.Lock()
VISITORS = VisitorStore(os.environ['DEMO_VISITOR_DB_PATH'])
PAGES = {'/': 'index.html', '/projects/game-support/': 'game.html',
         '/projects/loading-report/': 'loading.html', '/experience/internship/': 'loading.html',
         '/demo/game-support/': 'demo.html'}


class Handler(BaseHTTPRequestHandler):
    server_version = 'Portfolio'

    def setup(self):
        super().setup()
        self.connection.settimeout(15)

    def token(self):
        try:
            cookie = SimpleCookie(self.headers.get('Cookie', ''))
            return cookie['portfolio_session'].value if 'portfolio_session' in cookie else ''
        except CookieError:
            return ''

    def authenticated(self):
        now = time.time()
        with LOCK:
            for token in list(SESSIONS):
                if SESSIONS[token][1] < now:
                    del SESSIONS[token]
            session = SESSIONS.get(self.token())
        if not session or session[0] != self.visitor():
            return False
        state = VISITORS.state(session[0])
        return bool(state and not state['blocked'])

    def visitor(self):
        if hasattr(self, '_visitor'):
            return self._visitor
        try:
            jar = SimpleCookie(self.headers.get('Cookie',''))
            value = jar[VISITOR_COOKIE].value if VISITOR_COOKIE in jar else ''
        except CookieError:
            value = ''
        secret = os.environ['DEMO_ACCESS_SECRET']
        ident = verify_visitor(value, secret)
        if not ident:
            ident = secrets.token_hex(16)
        ip = '' if urlsplit(self.path).path == '/auth/check' else self.headers.get('X-Real-IP',self.client_address[0])
        VISITORS.ensure(ident, ip)
        self._visitor = ident
        self._visitor_cookie = f'{VISITOR_COOKIE}={sign_visitor(ident,secret)}; Path=/; Max-Age=31536000; HttpOnly; SameSite=Strict' + ('; Secure' if SECURE else '')
        return ident

    def send(self, status, body=b'', content_type='text/html; charset=utf-8', extra=None):
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('X-Frame-Options', 'DENY')
        self.send_header('Referrer-Policy', 'same-origin')
        if hasattr(self, '_visitor_cookie'):
            self.send_header('Set-Cookie', self._visitor_cookie)
        self.send_header('X-Robots-Tag', 'noindex, nofollow, noarchive')
        self.send_header('Content-Security-Policy', "default-src 'none'; style-src 'self'; script-src 'self'; img-src 'self' data:; connect-src 'self'; font-src 'self'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'")
        for key, value in (extra or {}).items():
            for item in (value if isinstance(value, list) else [value]):
                self.send_header(key, item)
        self.end_headers()
        if self.command != 'HEAD':
            self.wfile.write(body)

    def json(self, status, data, extra=None):
        self.send(status, json.dumps(data, ensure_ascii=False).encode(), 'application/json; charset=utf-8', extra)


    def demo_cookie(self):
        secret = os.environ['DEMO_ACCESS_SECRET']
        now = int(time.time())
        def encode(value):
            return base64.urlsafe_b64encode(value).rstrip(b'=')
        head = encode(json.dumps({'alg': 'HS256', 'typ': 'JWT'}).encode())
        body = encode(json.dumps({'sub': 'demo-reviewer', 'aud': 'game-support-demo',
                                  'vid': self.visitor(),
                                  'iat': now, 'exp': now + SESSION_TTL}).encode())
        message = head + b'.' + body
        signature = encode(hmac.new(secret.encode(), message, hashlib.sha256).digest())
        token = (message + b'.' + signature).decode()
        return f'gsa_demo_access={token}; Path=/; Max-Age={SESSION_TTL}; HttpOnly; SameSite=Strict' + ('; Secure' if SECURE else '')

    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        path = urlsplit(self.path).path
        if not path.startswith('/portfolio-assets/') and path != '/health':
            self.visitor()
        if path == '/health':
            return self.json(200, {'ok': True})
        if path == '/auth/check':
            return self.send(204 if self.authenticated() else 401)
        if path == '/robots.txt':
            return self.send(200, b'User-agent: *\nDisallow: /\n', 'text/plain')
        if path.startswith('/portfolio-assets/'):
            if path.startswith('/portfolio-assets/evidence-') and not self.authenticated():
                return self.send(401)
            file = (ROOT / path.lstrip('/')).resolve()
            if file.parent != (ROOT / 'portfolio-assets').resolve() or not file.is_file():
                return self.send(404)
            return self.send(200, file.read_bytes(), mimetypes.guess_type(file.name)[0] or 'application/octet-stream')
        if path == '/login':
            if self.authenticated():
                return self.send(303, extra={'Location': '/'})
            return self.send(200, (ROOT / 'login.html').read_bytes())
        if not self.authenticated():
            return self.send(303, extra={'Location': '/login'})
        if not path.endswith('/') and path + '/' in PAGES:
            return self.send(308, extra={'Location': path + '/'})
        if path == '/demo/game-support/':
            return self.send(303, extra={'Location': '/accounts'})
        file = PAGES.get(path)
        if file:
            return self.send(200, (ROOT / file).read_bytes())
        return self.send(404, (ROOT / '404.html').read_bytes())

    def do_POST(self):
        path = urlsplit(self.path).path
        origin = self.headers.get('Origin', '')
        host = self.headers.get('Host', '')
        if not origin or urlsplit(origin).netloc != host or self.headers.get('X-Portfolio-Request') != '1':
            return self.json(403, {'error': '请从本站页面重新提交。'})
        if path == '/auth/logout':
            with LOCK:
                SESSIONS.pop(self.token(), None)
            return self.json(200, {'ok': True}, {'Set-Cookie': ['portfolio_session=; Path=/; Max-Age=0; HttpOnly; SameSite=Strict' + ('; Secure' if SECURE else ''), 'gsa_demo_access=; Path=/; Max-Age=0; HttpOnly; SameSite=Strict' + ('; Secure' if SECURE else '')]})
        if path != '/auth/login':
            return self.json(404, {'error': '页面不存在。'})
        ip = self.headers.get('X-Real-IP', self.client_address[0])
        now = time.time()
        ident = self.visitor()
        if VISITORS.state(ident)['blocked']:
            return self.json(403, {'error':'此访客编号已停用，请联系作品集作者。'})
        wait = VISITORS.ip_attempt(ip)
        if wait:
            return self.json(429, {'error':'此网络尝试次数较多，请稍后再试。'}, {'Retry-After':str(wait)})
        try:
            length = int(self.headers.get('Content-Length', '0'))
            if length < 1 or length > 1024:
                return self.json(400, {'error': '请输入有效的访问密码。'})
            data = json.loads(self.rfile.read(length))
            password = data.get('password') if isinstance(data, dict) else None
            if not isinstance(password, str) or len(password) > 128:
                raise ValueError()
        except (ValueError, UnicodeError):
            return self.json(400, {'error': '请输入有效的访问密码。'})
        actual = hashlib.pbkdf2_hmac('sha256', password.encode(), SALT, 210000).hex()
        correct = hmac.compare_digest(actual, PASSWORD_HASH)
        result = VISITORS.login_result(ident, correct)
        if result['blocked']:
            return self.json(403, {'error':'连续输错五次，此访客编号已永久停用，请联系作品集作者。'})
        if not correct:
            return self.json(401, {'error':f"密码不正确，请输入简历中手机号的后四位；还可尝试 {result['remaining']} 次。"})
        token = secrets.token_urlsafe(32)
        with LOCK:
            SESSIONS[token] = (ident, now + SESSION_TTL)
        cookie = f'portfolio_session={token}; Path=/; Max-Age={SESSION_TTL}; HttpOnly; SameSite=Strict'
        if SECURE:
            cookie += '; Secure'
        self.json(200, {'ok': True}, {'Set-Cookie': [cookie, self.demo_cookie()]})


if __name__ == '__main__':
    ThreadingHTTPServer(('127.0.0.1', int(os.environ.get('PORTFOLIO_PORT', '15176'))), Handler).serve_forever()
