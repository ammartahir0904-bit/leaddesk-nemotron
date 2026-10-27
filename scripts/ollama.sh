#!/bin/bash
# Run Ollama in Docker for LeadDesk AI analysis, reachable only from this computer.
# Usage: scripts/ollama.sh start | pull <model> | stop | status
# Add "--gpus all" to the docker run line on a PC with an NVIDIA GPU and the NVIDIA container toolkit.
set -eu
name=leaddesk-ollama
case "${1:-status}" in
  start)
    if docker ps -a --format '{{.Names}}' | grep -qx "$name"; then docker start "$name" >/dev/null
    else
      gpu=(); if command -v nvidia-smi >/dev/null && docker info 2>/dev/null | grep -qi nvidia; then gpu=(--gpus all); fi
      docker run -d --name "$name" --restart unless-stopped "${gpu[@]}" -p 127.0.0.1:11434:11434 -v leaddesk-ollama:/root/.ollama ollama/ollama:latest >/dev/null
    fi
    echo "Ollama starting on http://127.0.0.1:11434";;
  pull) docker exec "$name" ollama pull "${2:?model name, e.g. llama3.2:3b}";;
  stop) docker stop "$name" >/dev/null && echo "Ollama stopped";;
  status) curl -s --max-time 3 http://127.0.0.1:11434/api/tags || echo "Ollama not reachable";;
  *) echo "Usage: $0 start|pull <model>|stop|status" >&2; exit 2;;
esac
