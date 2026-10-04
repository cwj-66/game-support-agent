#!/bin/sh
set -eu
cd /opt/game-support-deploy/game-support-agent
docker compose exec -T mysql sh -c 'MYSQL_PWD=root_pass mysql -uroot' < ../mysql.sql
qdrant_container=$(docker compose ps -q qdrant)
qdrant_ip=$(docker inspect -f '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' "$qdrant_container")
collection=$(cat ../collection.txt)
curl --fail --silent --show-error -X POST "http://$qdrant_ip:6333/collections/$collection/snapshots/upload?priority=snapshot" -F 'snapshot=@/opt/game-support-deploy/qdrant.snapshot'
printf '\n'
curl --fail --silent --show-error "http://$qdrant_ip:6333/collections/$collection" | python3 -c 'import json,sys; r=json.load(sys.stdin)["result"]; print("restored_vector_count",r["points_count"])'
docker compose exec -T mysql sh -c 'MYSQL_PWD=root_pass mysql -uroot -N -e "SELECT COUNT(*) FROM game_support.game_players; SELECT COUNT(*) FROM rag_database.knowledge_documents;"' || true
