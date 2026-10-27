#!/bin/bash
# Start/stop a local SearXNG for LeadDesk web enrichment, reachable only from this computer.
# Usage: scripts/searxng.sh start | stop | status
set -eu
cd "$(dirname "$0")/.."
name=leaddesk-searxng
case "${1:-status}" in
  start)
    if docker ps -a --format '{{.Names}}' | grep -qx "$name"; then docker start "$name" >/dev/null
    else
      docker run -d --name "$name" --restart unless-stopped -p 127.0.0.1:8888:8080 \
        -e SEARXNG_SECRET="$(openssl rand -hex 32)" \
        -v "$PWD/deploy/searxng/settings.yml:/etc/searxng/settings.yml:ro" searxng/searxng:latest >/dev/null
    fi
    echo "SearXNG starting on http://127.0.0.1:8888 (give it ~10 seconds)";;
  stop) docker stop "$name" >/dev/null && echo "SearXNG stopped";;
  status) curl -s -o /dev/null -w "SearXNG HTTP %{http_code}\n" "http://127.0.0.1:8888/search?q=test&format=json" || echo "SearXNG not reachable";;
  *) echo "Usage: $0 start|stop|status" >&2; exit 2;;
esac
