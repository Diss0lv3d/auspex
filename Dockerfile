FROM python:3.12-slim

WORKDIR /srv/auspex

# Dependency layer: install deps from pyproject against an empty package skeleton so
# this layer is cached and only re-runs when pyproject changes — not on every code edit.
# Deps still come solely from pyproject (no hand-maintained requirements to drift).
COPY pyproject.toml ./
# Skeleton must satisfy every declared package/package-data in pyproject so the
# metadata build succeeds with no real source present (deps-only layer).
RUN mkdir -p auspex/routes auspex/ach auspex/actions auspex/agent auspex/alerts auspex/phishing auspex/llm auspex/classify \
             auspex/enrich/providers auspex/ingest auspex/jobs auspex/retrohunt auspex/tenancy auspex/watchers auspex/timeline auspex/modes \
             auspex/kb/seed_data auspex/static auspex/static/css auspex/static/js \
    && touch auspex/__init__.py auspex/routes/__init__.py auspex/ach/__init__.py \
             auspex/actions/__init__.py auspex/agent/__init__.py \
             auspex/alerts/__init__.py auspex/phishing/__init__.py \
             auspex/llm/__init__.py auspex/classify/__init__.py \
             auspex/enrich/__init__.py auspex/enrich/providers/__init__.py \
             auspex/ingest/__init__.py auspex/jobs/__init__.py auspex/retrohunt/__init__.py auspex/tenancy/__init__.py auspex/timeline/__init__.py \
             auspex/watchers/__init__.py auspex/modes/__init__.py \
             auspex/kb/__init__.py auspex/kb/seed_data/placeholder.json \
             auspex/static/placeholder.html auspex/static/css/placeholder.css \
             auspex/static/js/placeholder.js server.py \
    && pip install --no-cache-dir . \
    && rm -rf auspex server.py build auspex.egg-info

# App layer: real source, reinstall the package only (deps already satisfied above).
COPY auspex ./auspex
COPY server.py ./
# `build` and `auspex.egg-info` MUST NOT survive the layer above. setuptools
# reuses build/lib and skips copying a file whose timestamp looks current, so the
# skeleton's empty __init__.py files were reused into this wheel: every single
# __init__.py in the installed distribution was 0 bytes, for every package, since
# this Dockerfile was written. Nothing failed, because `uvicorn server:app` runs
# with WORKDIR on sys.path and the COPY'd source shadowed site-packages — so the
# app worked while `python -c "import auspex.routes"` from any other directory
# did not. The verify step in ci.sh now checks the installed dist, not just
# liveness (S14).
RUN pip install --no-cache-dir --no-deps . \
    && rm -rf build auspex.egg-info

EXPOSE 8000
CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8000"]
