#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.."
python3 -c 'import sys; assert sys.version_info[:2] == (3,12), "Python 3.12 is required"'
node -e 'if (Number(process.versions.node.split(".")[0]) !== 24) throw Error("Use Node 24: nvm use (see .nvmrc)")'
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.lock
(cd apps/web && npm ci --no-audit --no-fund && npm run build)
echo 'Setup complete. Run ./launch.sh'
