#!/usr/bin/env bash
# Auspex CI gate — exactly what CI will run: lint, tests against live deps, then a
# real container build + liveness check (D-003 'docker compose up green' invariant).
set -euo pipefail
cd "$(dirname "$0")"

VENV=.venv
if [ ! -d "$VENV" ]; then python3 -m venv "$VENV"; fi
# shellcheck disable=SC1091
source "$VENV/bin/activate"
pip install -q -e ".[dev]"

echo "== ruff =="
ruff check auspex tests server.py

echo "== deps up (postgres + opensearch) =="
# --wait blocks until healthchecks pass; no hardcoded container names to drift.
docker compose up -d --wait postgres opensearch

echo "== pytest =="
export DATABASE_URL="${DATABASE_URL:-postgresql://auspex:auspex@localhost:55432/auspex}"
export OPENSEARCH_URL="${OPENSEARCH_URL:-http://localhost:9200}"
pytest -q

echo "== app container build + liveness (D-003) =="
docker compose up -d --build --wait app
curl -sf http://localhost:8000/api/health >/dev/null
echo "app container serves /api/health"

echo "CI green."
