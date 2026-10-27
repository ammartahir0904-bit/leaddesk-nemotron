#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"
# Optional keys (NEBIUS_API_KEY, TAVILY_API_KEY) from a local .env file; see .env.example.
if [[ -f .env ]]; then set -a; . ./.env; set +a; fi
if [[ ! -x .venv/bin/python || ! -f apps/web/dist/index.html ]]; then
  echo 'Run ./scripts/setup.sh first (Python 3.12 and Node 24 required).'
  exit 1
fi
.venv/bin/python - <<'PY'
from backend.settings import Settings
settings = Settings.load()
print('\nLeadDesk: http://127.0.0.1:8765')
print('Local access key (paste into the workspace): ' + settings.token)
print('Keep this terminal open. Press Ctrl+C to stop.\n')
PY
exec .venv/bin/python -m uvicorn backend.main:app --host 127.0.0.1 --port 8765 --workers 1 --no-access-log
