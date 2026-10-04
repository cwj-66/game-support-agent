#!/usr/bin/env bash
# Code-only update. Run as root after uploading the reviewed archive to /opt/game-support-deploy/.
set -euo pipefail
cd /opt/game-support-deploy
stamp=$(date -u +%Y%m%d-%H%M%S)
backup="backup-review-$stamp"
install -d -m 700 "$backup"
tar -czf "$backup/code.tar.gz" game-support-agent/app game-support-agent/agent \
  game-support-agent/mcp_server.py game-support-agent/compose.yml \
  game-support-agent/player-chat enterprise-rag/app enterprise-rag/Dockerfile.cloud \
  enterprise-rag/requirements-cloud.txt
cp /opt/chenwj-portfolio/public/game.html "$backup/game.html"
if [ -f /opt/chenwj-portfolio/public/portfolio-assets/agent.css ]; then
  cp /opt/chenwj-portfolio/public/portfolio-assets/agent.css "$backup/agent.css"
fi
docker ps --format '{{.Names}} {{.Image}}' > "$backup/images.txt"
for service in agent-api mcp-server rag-api player-chat; do
  id=$(docker inspect --format '{{.Image}}' "game-support-server-$service-1")
  docker image tag "$id" "game-support-rollback-$service:$stamp"
done
tar -xzf reviewed-release.tar.gz
cd game-support-agent
docker compose -f compose.yml config --quiet
docker compose -f compose.yml build agent-api mcp-server rag-api player-chat
docker compose -f compose.yml up -d
for attempt in $(seq 1 60); do
  if docker exec game-support-server-agent-api-1 python -c \
    'import urllib.request,json; d=json.load(urllib.request.urlopen("http://127.0.0.1:8002/health",timeout=5)); assert d["status"]=="healthy"; assert d["checks"]["capacity"]["max_active"]==3' >/dev/null 2>&1; then
    install -m 644 ../portfolio/agent.css /opt/chenwj-portfolio/public/portfolio-assets/agent.css
    install -m 644 ../portfolio/game.html /opt/chenwj-portfolio/public/game.html
    docker compose -f compose.yml ps
    echo "RELEASE_OK backup=/opt/game-support-deploy/$backup"
    exit 0
  fi
  sleep 2
done
echo "RELEASE_FAILED backup=/opt/game-support-deploy/$backup" >&2
exit 1
