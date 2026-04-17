#!/usr/bin/env bash
# Fresh UI build + API server (one command). From repo root: ./dev.sh
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

rm -rf web/dist
( cd web && npm run build )

exec uv run uvicorn talenthawk.web_api:app --host 127.0.0.1 --port 8000 --reload "$@"
