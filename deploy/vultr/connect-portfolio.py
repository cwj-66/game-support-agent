"""Connect the existing private portfolio to the verified server Docker deployment."""
from pathlib import Path
import datetime
import shutil
import subprocess
import urllib.request

base = Path('/opt/game-support-deploy')
stamp = datetime.datetime.now().strftime('%Y%m%d-%H%M%S')
backup = base / ('backup-' + stamp)
backup.mkdir(mode=0o700)
with urllib.request.urlopen('http://127.0.0.1:15177/api/v1/access/status', timeout=10) as response:
    assert response.status == 200

portal = Path('/opt/chenwj-portfolio/server.py')
nginx = Path('/etc/nginx/sites-available/game-support-demo')
if not nginx.exists():
    nginx = Path('/etc/nginx/sites-enabled/game-support-demo').resolve()
env = Path('/etc/chenwj-portfolio.env')
for path in [portal, nginx, env]:
    shutil.copy2(path, backup / path.name)

config = {}
for line in (base/'game-support-agent/.env').read_text().splitlines():
    if '=' in line and not line.startswith('#'):
        key, value = line.split('=', 1)
        config[key] = value.strip().strip("'\"")
secret = config['DEMO_ACCESS_SECRET']
assert secret

source = portal.read_text()
source = source.replace('import hashlib\n', 'import hashlib\nimport base64\n')
source = source.replace('            self.send_header(key, value)',
                        '            for item in (value if isinstance(value, list) else [value]):\n                self.send_header(key, item)')
helper = '''
    def demo_cookie(self):
        secret = os.environ['DEMO_ACCESS_SECRET']
        now = int(time.time())
        def encode(value):
            return base64.urlsafe_b64encode(value).rstrip(b'=')
        head = encode(json.dumps({'alg': 'HS256', 'typ': 'JWT'}).encode())
        body = encode(json.dumps({'sub': 'demo-reviewer', 'aud': 'game-support-demo',
                                  'iat': now, 'exp': now + SESSION_TTL}).encode())
        message = head + b'.' + body
        signature = encode(hmac.new(secret.encode(), message, hashlib.sha256).digest())
        token = (message + b'.' + signature).decode()
        return f'gsa_demo_access={token}; Path=/; Max-Age={SESSION_TTL}; HttpOnly; SameSite=Strict' + ('; Secure' if SECURE else '')

'''
assert '    def do_HEAD(self):' in source
source = source.replace('    def do_HEAD(self):', helper + '    def do_HEAD(self):')
source = source.replace("        file = PAGES.get(path)",
                        "        if path == '/demo/game-support/':\n            return self.send(303, extra={'Location': '/accounts'})\n        file = PAGES.get(path)")
assert "self.json(200, {'ok': True}, {'Set-Cookie': cookie})" in source
source = source.replace("self.json(200, {'ok': True}, {'Set-Cookie': cookie})",
                        "self.json(200, {'ok': True}, {'Set-Cookie': [cookie, self.demo_cookie()]})")
logout = "'portfolio_session=; Path=/; Max-Age=0; HttpOnly; SameSite=Strict' + ('; Secure' if SECURE else '')"
source = source.replace(logout, "[" + logout + ", 'gsa_demo_access=; Path=/; Max-Age=0; HttpOnly; SameSite=Strict' + ('; Secure' if SECURE else '')]")
compile(source, str(portal), 'exec')
portal.write_text(source)
values = [line for line in env.read_text().splitlines() if not line.startswith('DEMO_ACCESS_SECRET=')]
values.append('DEMO_ACCESS_SECRET=' + secret)
env.write_text('\n'.join(values) + '\n')
env.chmod(0o600)

conf = nginx.read_text()
assert 'proxy_pass http://127.0.0.1:15175;' in conf
nginx.write_text(conf.replace('proxy_pass http://127.0.0.1:15175;', 'proxy_pass http://127.0.0.1:15177;'))
subprocess.run(['nginx', '-t'], check=True)
subprocess.run(['systemctl', 'restart', 'chenwj-portfolio'], check=True)
subprocess.run(['systemctl', 'reload', 'nginx'], check=True)
for name in ['index.html', 'game.html']:
    path = Path('/opt/chenwj-portfolio/public')/name
    shutil.copy2(path, backup/name)
    text = path.read_text()
    for old,new in [('当前演示暂未启动','在线演示已启动'),
                    ('在线演示待启动','在线演示可体验'),
                    ('查看演示入口','进入在线演示'),
                    ('演示暂未启动','在线演示已启动')]:
        text = text.replace(old,new)
    path.write_text(text)
print('portfolio_connected; rollback_backup:', backup)
