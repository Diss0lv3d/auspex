FROM python:3.12-slim

WORKDIR /srv/auspex

# Dependency layer: install deps from pyproject against an empty package skeleton so
# this layer is cached and only re-runs when pyproject changes — not on every code edit.
# Deps still come solely from pyproject (no hand-maintained requirements to drift).
COPY pyproject.toml ./
# Skeleton must satisfy every declared package/package-data in pyproject so the
# metadata build succeeds with no real source present (deps-only layer).
RUN mkdir -p auspex/routes auspex/agent auspex/llm auspex/classify \
             auspex/enrich/providers auspex/static \
    && touch auspex/__init__.py auspex/routes/__init__.py auspex/agent/__init__.py \
             auspex/llm/__init__.py auspex/classify/__init__.py \
             auspex/enrich/__init__.py auspex/enrich/providers/__init__.py \
             auspex/static/placeholder.html server.py \
    && pip install --no-cache-dir . \
    && rm -rf auspex server.py

# App layer: real source, reinstall the package only (deps already satisfied above).
COPY auspex ./auspex
COPY server.py ./
RUN pip install --no-cache-dir --no-deps .

EXPOSE 8000
CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8000"]
