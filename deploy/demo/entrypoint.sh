#!/bin/sh
# Fresh fictional data on every start, then serve the public demo.
set -eu
rm -rf /data/* && cp -r /app/demo-template/. /data/
if [ -z "${NEBIUS_API_KEY:-}" ]; then echo "Note: NEBIUS_API_KEY is not set, so AI rewording with NVIDIA Nemotron is unavailable in this demo."; fi
exec python -m uvicorn backend.main:app --host 0.0.0.0 --port 8765 --workers 1 --no-access-log --proxy-headers
