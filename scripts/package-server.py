"""Create a deployment bundle; excluded local models and developer tools."""
from pathlib import Path
import sqlite3
import tarfile
import secrets
from dotenv import dotenv_values

root = Path(__file__).resolve().parents[1]
rag = root.parent / 'enterprise-rag'
out = root / '.cache/server-deploy'
out.mkdir(parents=True, exist_ok=True)
source = sqlite3.connect(root / 'data/game_support_docker.db')
dest = sqlite3.connect(out / 'game_support_docker.db')
source.backup(dest)
dest.close()
source.close()

# Keep existing access secrets. Replace development authentication defaults.
config = dotenv_values(root / '.env')
config.update({'AGENT_RAG_SERVICE_URL': 'http://rag-api:8000',
               'MCP_RAG_SERVICE_URL': 'http://rag-api:8000',
               'RAG_SERVICE_URL': 'http://rag-api:8000',
               'DEBUG': 'false', 'GAME_JWT_SECRET': secrets.token_urlsafe(48)})
def env_text(values):
    return ''.join(k + "='" + str(v).replace("'", "\\'") + "'\n"
                   for k,v in values.items() if v is not None)
(out / 'server.env').write_text(env_text(config), encoding='utf-8')

excluded = {'__pycache__', 'node_modules', '.git', '.cache', '.venv', 'venv'}
def add_tree(archive, path, prefix):
    for file in path.rglob('*'):
        if file.is_file() and not any(p in excluded for p in file.relative_to(path).parts):
            archive.add(file, arcname=str(Path(prefix) / file.relative_to(path)))

with tarfile.open(out / 'bundle.tar.gz', 'w:gz') as archive:
    for folder in ['app', 'agent', 'scripts/mysql']:
        add_tree(archive, root / folder, 'game-support-agent/' + folder)
    for name in ['Dockerfile', 'requirements.txt', 'mcp_server.py']:
        archive.add(root/name, arcname='game-support-agent/' + name)
    add_tree(archive, root/'player-chat/dist', 'game-support-agent/player-chat/dist')
    archive.add(root/'player-chat/nginx.conf', arcname='game-support-agent/player-chat/nginx.conf')
    archive.add(root/'deploy/Dockerfile.frontend', arcname='game-support-agent/deploy/Dockerfile.frontend')
    archive.add(root/'deploy/vultr/compose.server.yml', arcname='game-support-agent/compose.yml')
    archive.add(out/'server.env', arcname='game-support-agent/.env')
    archive.add(out/'game_support_docker.db', arcname='game-support-agent/data/game_support_docker.db')
    add_tree(archive, rag/'app', 'enterprise-rag/app')
    for name in ['.env', 'requirements-cloud.txt', 'Dockerfile.cloud']:
        archive.add(rag/name, arcname='enterprise-rag/' + name)
print('bundle_bytes', (out/'bundle.tar.gz').stat().st_size)
