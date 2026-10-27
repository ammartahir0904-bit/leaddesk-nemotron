#!/bin/bash
# Runs each prepared browser flow against its own fresh, empty, disposable
# instance on 127.0.0.1:8765. Never uses your normal data directory.
# Usage: scripts/run-browser-flows.sh [main learning files voice screen workers correspondence evaluation]
set -u
cd "$(dirname "$0")/.."
if curl -s -o /dev/null http://127.0.0.1:8765/; then
  echo "Port 8765 is in use. Stop your regular LeadDesk instance first." >&2; exit 2
fi
flows=("$@"); [ ${#flows[@]} -eq 0 ] && flows=(main learning files voice screen workers correspondence evaluation)
mkdir -p .local
failed=0
for flow in "${flows[@]}"; do
  dir=$(mktemp -d "$PWD/.local/browser-flow-$flow.XXXX")
  LEADDESK_DATA_DIR="$dir" setsid -w ./launch.sh > "$dir/server.log" 2>&1 &
  server=$!
  for _ in $(seq 1 60); do curl -s -o /dev/null http://127.0.0.1:8765/ && break; sleep 0.5; done
  script=$([ "$flow" = main ] && echo test:e2e || echo "test:e2e:$flow")
  (cd apps/web && LEADDESK_TEST_TOKEN_FILE="$dir/access-token" timeout 240 npm run -s "$script" > "$dir/flow.log" 2>&1)
  code=$?
  [ $code -eq 0 ] && echo "PASS $flow" || { echo "FAIL $flow (exit $code) — see $dir/flow.log"; failed=1; }
  kill -TERM -- -"$server" 2>/dev/null
  for _ in $(seq 1 20); do curl -s -o /dev/null http://127.0.0.1:8765/ || break; sleep 0.5; done
  [ $code -eq 0 ] && rm -rf "$dir"
done
exit $failed
