#!/usr/bin/env bash
# Auspex CI gate — exactly what CI will run: lint, tests against live deps, then a
# real container build + liveness check (D-003 'docker compose up green' invariant).
set -euo pipefail
cd "$(dirname "$0")"

VENV=.venv
if [ ! -d "$VENV" ]; then python3 -m venv "$VENV"; fi
# shellcheck disable=SC1091
source "$VENV/bin/activate"
# The SDK first (R1): the core does not declare it as a dependency, because the name is
# unowned on PyPI and a declared dependency could resolve to someone else's package.
pip install -q -e ./sdk
pip install -q -e ".[dev]"

echo "== ruff =="
ruff check auspex tests scripts server.py sdk $([ -d examples ] && echo examples)

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

# Liveness alone does NOT prove the image is sound: uvicorn runs with WORKDIR on
# sys.path, so the COPY'd source shadows site-packages and the app serves happily
# on top of a broken install. That hid two real defects until S14 — an undeclared
# package (auspex.retrohunt, auspex.modes) and every __init__.py installed at
# 0 bytes from a stale build/lib. Import the INSTALLED distribution from a
# directory that cannot shadow it.
echo "== installed distribution matches the source tree (not just liveness) =="
docker compose exec -T --workdir /tmp app python -c "
from importlib import import_module
from pathlib import Path
import auspex

installed = Path(auspex.__file__).parent
assert 'site-packages' in str(installed), f'shadowed, not testing the install: {installed}'
# The whole app, imported from a directory that cannot shadow site-packages.
import_module('auspex.app')

source = Path('/srv/auspex/auspex')
missing, differing = [], []
for src in sorted(source.rglob('*.py')):
    if '__pycache__' in src.parts:
        continue
    dst = installed / src.relative_to(source)
    if not dst.exists():
        missing.append(str(src.relative_to(source)))
    elif dst.read_bytes() != src.read_bytes():
        differing.append(f'{src.relative_to(source)} (src {src.stat().st_size}B vs installed {dst.stat().st_size}B)')
assert not missing, f'source modules absent from the install: {missing}'
assert not differing, f'installed copies differ from source: {differing}'
print(f'installed dist == source tree ({len(list(source.rglob(\"*.py\")))} modules), app imports clean')
"

echo "CI green."
