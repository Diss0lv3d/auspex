"""KnowledgeService — the one object the app holds (app.state.kb). S6.

Same shape as EnrichmentService (S5): settings-built, hermetic-test seam,
one circuit breaker (single backend), lazily created shared httpx client,
honest failure semantics — a KB problem raises KBUnavailable and the caller
keeps the deferred copy; nothing here ever 500s a chat turn.

Bootstrap is idempotent and NEVER raises (app startup must survive a cold or
air-gapped OpenSearch): cluster setting → model register+deploy (ONNX pinned,
D-018) → index create → seed ingest. Every step no-ops when reality already
matches. Fresh-volume first boot downloads the model (~12 s, probed); warm
boots are 4 cheap round trips.

Retrieval rails (probe: docs/probes/2026-07-17-sara-rrf-retriever-pattern.md):
- `lookup_ids` — term/prefix on the `ids` keyword field. Exact-ID answers
  never depend on vector similarity (analyzer probe: CVE ids shatter into
  3 tokens; parent technique ids don't prefix-match sub-techniques in text).
- `search` — ID-dominant queries take the ID rail (BM25 fallback, no neural);
  everything else fuses BM25 + neural with client-side RRF, then a
  regime-aware floor. Legs degrade independently (S5 fan-out spirit): a dead
  neural leg (missing model) demotes to BM25-only instead of failing the turn.
"""

import asyncio
import json
import logging
from datetime import UTC, datetime

import httpx

from auspex import __version__
from auspex.config import Settings
from auspex.enrich.breaker import CircuitBreaker
from auspex.kb.chunking import chunk_doc
from auspex.kb.fuse import apply_floor, neural_leg_floor, rrf_fuse
from auspex.kb.idquery import extract_kb_ids, is_id_query
from auspex.kb.mapping import (
    EMBED_MODEL_FORMAT,
    EMBED_MODEL_NAME,
    EMBED_MODEL_VERSION,
    KNOWLEDGE_INDEX,
    KNOWLEDGE_MAPPING,
    SOURCE_EXCLUDES,
)
from auspex.kb.seed import load_seed_docs
from auspex.kb.types import KBDoc, KBHit, KBUnavailable

logger = logging.getLogger("auspex.kb")

CALL_TIMEOUT_SECONDS = 6.0
BOOTSTRAP_CALL_TIMEOUT_SECONDS = 30.0
TASK_POLL_INTERVAL_SECONDS = 2.0
TASK_POLL_BUDGET_SECONDS = 180.0  # fresh-volume register+deploy measured ~15 s; 12x headroom
EMBED_BATCH_SIZE = 16  # probed sweet spot: ~8 ms/text amortized

# Technique-shaped ids get a prefix clause so a parent id (T1059) also pulls
# its sub-techniques (T1059.001) — term alone can't (keyword field).
_TECHNIQUE_PARENT_LEN = 5  # "T1059"


class KnowledgeService:
    def __init__(
        self,
        base_url: str,
        *,
        auth: tuple[str, str] | None = None,
        enabled: bool = True,
        client: httpx.AsyncClient | None = None,
        breaker: CircuitBreaker | None = None,
        call_timeout: float = CALL_TIMEOUT_SECONDS,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._auth = auth
        self._enabled = enabled and bool(base_url)
        self._client = client
        self._owns_client = client is None
        self._breaker = breaker or CircuitBreaker()
        self._call_timeout = call_timeout
        self._model_id: str | None = None
        self._model_lookup_failed = False

    @classmethod
    def from_settings(cls, settings: Settings) -> "KnowledgeService":
        auth = None
        if settings.opensearch_user and settings.opensearch_pass:
            auth = (settings.opensearch_user, settings.opensearch_pass)
        return cls(settings.opensearch_url, auth=auth, enabled=settings.kb_enabled)

    @property
    def active(self) -> bool:
        return self._enabled

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self._base_url,
                auth=self._auth,
                timeout=self._call_timeout,
                headers={"User-Agent": f"Auspex/{__version__}"},
            )
        return self._client

    async def aclose(self) -> None:
        if self._client is not None and self._owns_client:
            await self._client.aclose()
        self._client = None

    # ── Bootstrap (idempotent, never raises) ─────────────────────────────

    async def bootstrap(self) -> str:
        """Make reality match the design; report what was done. App startup
        calls this and logs the summary — a failure leaves the service up
        with the breaker/deferred rail handling requests honestly."""
        if not self._enabled:
            return "kb disabled"
        steps: list[str] = []
        try:
            await self._ensure_ml_settings()
            self._model_id, model_step = await self._ensure_model()
            steps.append(model_step)
            steps.append(await self._ensure_index())
            steps.append(await self._ensure_seed())
            self._breaker.record_success()
            return "; ".join(steps)
        except Exception as err:  # noqa: BLE001 — startup must survive anything
            logger.exception("kb bootstrap failed")
            return f"kb bootstrap failed after [{'; '.join(steps) or 'nothing'}]: {err}"

    async def _ensure_ml_settings(self) -> None:
        # Single-node dev/CI: ML must run on the data node. Persistent, but a
        # fresh volume forgets it — hence re-applied every boot (probed).
        resp = await self._get_client().put(
            "/_cluster/settings",
            json={"persistent": {"plugins.ml_commons.only_run_on_ml_node": False}},
            timeout=BOOTSTRAP_CALL_TIMEOUT_SECONDS,
        )
        resp.raise_for_status()

    async def _find_model(self) -> tuple[str, str] | None:
        """(model_id, model_state) of the pinned model, or None. The model
        binary's chunks are docs in the same index — the real model doc is the
        one WITHOUT chunk_number (probe addendum)."""
        resp = await self._get_client().post(
            "/_plugins/_ml/models/_search",
            json={
                "size": 1,
                "query": {
                    "bool": {
                        "must": [{"term": {"name.keyword": EMBED_MODEL_NAME}}],
                        "must_not": [{"exists": {"field": "chunk_number"}}],
                    }
                },
                "_source": ["name", "model_state"],
            },
        )
        resp.raise_for_status()
        hits = resp.json()["hits"]["hits"]
        if not hits:
            return None
        return hits[0]["_id"], hits[0]["_source"].get("model_state", "")

    async def _poll_task(self, task_id: str) -> dict:
        deadline = asyncio.get_event_loop().time() + TASK_POLL_BUDGET_SECONDS
        while True:
            resp = await self._get_client().get(f"/_plugins/_ml/tasks/{task_id}")
            resp.raise_for_status()
            task = resp.json()
            if task.get("state") in ("COMPLETED", "FAILED"):
                return task
            if asyncio.get_event_loop().time() >= deadline:
                raise TimeoutError(f"ML task {task_id} still {task.get('state')!r}")
            await asyncio.sleep(TASK_POLL_INTERVAL_SECONDS)

    async def _deploy_model(self, model_id: str) -> None:
        resp = await self._get_client().post(
            f"/_plugins/_ml/models/{model_id}/_deploy",
            timeout=BOOTSTRAP_CALL_TIMEOUT_SECONDS,
        )
        resp.raise_for_status()
        task = await self._poll_task(resp.json()["task_id"])
        if task.get("state") != "COMPLETED":
            raise RuntimeError(f"model deploy failed: {task.get('error', 'unknown')}")

    async def _ensure_model(self) -> tuple[str, str]:
        found = await self._find_model()
        if found is not None:
            model_id, state = found
            if state in ("DEPLOYED", "PARTIALLY_DEPLOYED"):
                return model_id, f"model {model_id} already deployed"
            # Registered but not deployed (fresh restore, prior deploy failure).
            # model_auto_deploy would also cover this on first predict; doing it
            # here makes the first turn warm instead of 3 s slow.
            await self._deploy_model(model_id)
            return model_id, f"model {model_id} deployed (was {state or 'unknown'})"
        register = await self._get_client().post(
            "/_plugins/_ml/models/_register",
            json={
                "name": EMBED_MODEL_NAME,
                "version": EMBED_MODEL_VERSION,
                "model_format": EMBED_MODEL_FORMAT,  # ONNX pinned — D-018
            },
            timeout=BOOTSTRAP_CALL_TIMEOUT_SECONDS,
        )
        register.raise_for_status()
        task = await self._poll_task(register.json()["task_id"])
        if task.get("state") != "COMPLETED" or "model_id" not in task:
            raise RuntimeError(f"model register failed: {task.get('error', 'unknown')}")
        model_id = task["model_id"]
        await self._deploy_model(model_id)
        return model_id, f"model {model_id} registered + deployed"

    async def _ensure_index(self) -> str:
        client = self._get_client()
        head = await client.head(f"/{KNOWLEDGE_INDEX}")
        if head.status_code == 200:
            return f"index {KNOWLEDGE_INDEX} exists"
        resp = await client.put(
            f"/{KNOWLEDGE_INDEX}", json=KNOWLEDGE_MAPPING, timeout=BOOTSTRAP_CALL_TIMEOUT_SECONDS
        )
        resp.raise_for_status()
        return f"index {KNOWLEDGE_INDEX} created"

    async def _ensure_seed(self) -> str:
        docs = load_seed_docs()
        expected = sum(len(chunk_doc(d)) for d in docs)
        resp = await self._get_client().get(f"/{KNOWLEDGE_INDEX}/_count")
        resp.raise_for_status()
        count = resp.json()["count"]
        if count >= expected:
            return f"seed present ({count} chunks)"
        # Upsert by chunk_id ⇒ re-ingesting after a partial seed self-heals.
        ingested = await self.ingest_docs(docs)
        return f"seeded {ingested} chunks (found {count})"

    # ── Ingestion (bootstrap now; S7 feeds call this too) ────────────────

    async def embed(self, texts: list[str]) -> list[list[float]]:
        if self._model_id is None:
            raise KBUnavailable("embedding model not resolved")
        resp = await self._get_client().post(
            f"/_plugins/_ml/_predict/text_embedding/{self._model_id}",
            json={
                "text_docs": texts,
                "return_number": True,
                "target_response": ["sentence_embedding"],
            },
            timeout=BOOTSTRAP_CALL_TIMEOUT_SECONDS,
        )
        resp.raise_for_status()
        results = resp.json()["inference_results"]
        return [r["output"][0]["data"] for r in results]

    async def ingest_docs(self, docs: list[KBDoc]) -> int:
        """Chunk, embed (batched), bulk-index. Returns chunk count."""
        chunks = [c for d in docs for c in chunk_doc(d)]
        now = datetime.now(UTC).isoformat()
        total = 0
        for start in range(0, len(chunks), EMBED_BATCH_SIZE):
            batch = chunks[start : start + EMBED_BATCH_SIZE]
            vectors = await self.embed([c.text for c in batch])
            lines: list[str] = []
            for chunk, vector in zip(batch, vectors, strict=True):
                lines.append(
                    _json_line({"index": {"_index": KNOWLEDGE_INDEX, "_id": chunk.chunk_id}})
                )
                lines.append(
                    _json_line(
                        {
                            "doc_id": chunk.doc.doc_id,
                            "chunk_index": chunk.chunk_index,
                            "ids": list(chunk.doc.ids),
                            "title": chunk.doc.title,
                            "content": chunk.text,
                            "doc_type": chunk.doc.doc_type,
                            "source": chunk.doc.source,
                            "source_ref": chunk.doc.source_ref,
                            "severity": chunk.doc.severity,
                            "cvss_score": chunk.doc.cvss_score,
                            "workspace_id": "",
                            "ingested_at": now,
                            "embedding": vector,
                        }
                    )
                )
            resp = await self._get_client().post(
                "/_bulk",
                content="\n".join(lines) + "\n",
                headers={"Content-Type": "application/x-ndjson"},
                params={"refresh": "true"},
                timeout=BOOTSTRAP_CALL_TIMEOUT_SECONDS,
            )
            resp.raise_for_status()
            body = resp.json()
            if body.get("errors"):
                failed = [
                    item["index"].get("error", {}).get("reason", "?")
                    for item in body.get("items", ())
                    if item.get("index", {}).get("error")
                ]
                raise RuntimeError(f"bulk ingest errors: {failed[:3]}")
            total += len(batch)
        return total

    # ── Retrieval ─────────────────────────────────────────────────────────

    async def lookup_ids(self, ids: tuple[str, ...], *, top_k: int = 8) -> list[KBHit]:
        """Exact-ID rail: term (boosted) + technique-parent prefix on `ids`.
        No CVE prefix clauses ever — CVE-2021-4 must not match CVE-2021-44228."""
        if not ids:
            return []
        should: list[dict] = []
        for id_ in ids:
            normalized = id_.upper()
            should.append({"term": {"ids": {"value": normalized, "boost": 10}}})
            if _is_parent_technique(normalized):
                should.append({"prefix": {"ids": {"value": f"{normalized}.", "boost": 2}}})
        body = {
            "size": top_k,
            "_source": {"excludes": SOURCE_EXCLUDES},
            "query": {"bool": {"should": should, "minimum_should_match": 1}},
            "sort": [{"_score": "desc"}, {"chunk_index": "asc"}],
        }
        return await self._search_call(body)

    async def search(self, query: str, *, top_k: int = 5) -> list[KBHit]:
        """The retrieval front door. ID-dominant → ID rail only (an unknown ID
        is an honest miss — no fuzzy-prose fallback; SARA's BM25 fallback
        existed for its prefixed doc-id zoo, which our `ids` field replaces);
        otherwise hybrid BM25+neural RRF with a regime-aware floor.
        Raises KBUnavailable when the KB can't answer."""
        if is_id_query(query):
            return await self.lookup_ids(extract_kb_ids(query), top_k=top_k)
        bm25_task = self._bm25(query, top_k * 2)
        neural_task = self._neural(query, top_k * 2)
        bm25, neural = await asyncio.gather(bm25_task, neural_task, return_exceptions=True)
        if isinstance(bm25, BaseException) and isinstance(neural, BaseException):
            self._breaker.record_failure()
            raise KBUnavailable(f"search failed: {bm25}")
        if isinstance(neural, BaseException):
            # Missing/undeployed model etc. — BM25 alone is still a KB answer.
            logger.warning("kb neural leg failed, serving BM25 only: %s", neural)
            return apply_floor(bm25[:top_k])
        if not neural:
            # Neural ran and nothing in the corpus is semantically near the
            # query (post-floor). BM25 hits here are fuzzy/stopword noise —
            # live-caught 2026-07-17: "what is quantum entanglement" scored
            # 4.4 on a C2 doc via "what"/"is". Disagreement ⇒ honest miss;
            # only neural UNAVAILABILITY (above) degrades to BM25-only.
            return []
        if isinstance(bm25, BaseException):
            logger.warning("kb bm25 leg failed, serving neural only: %s", bm25)
            return apply_floor(neural[:top_k])
        return apply_floor(rrf_fuse(bm25, neural, top_k=top_k))

    async def _bm25(self, query: str, size: int) -> list[KBHit]:
        return await self._search_call(
            {
                "size": size,
                "_source": {"excludes": SOURCE_EXCLUDES},
                "query": {
                    "multi_match": {
                        "query": query,
                        "fields": ["content^3", "title^2"],
                        "type": "best_fields",
                        "fuzziness": "AUTO",
                        # Damp stopword-only matches ("what is …" hits every
                        # doc): >2 terms ⇒ 75% must match.
                        "minimum_should_match": "2<75%",
                    }
                },
            }
        )

    async def _neural(self, query: str, size: int) -> list[KBHit]:
        model_id = await self._resolve_model_id()
        if model_id is None:
            raise KBUnavailable("embedding model not available")
        hits = await self._search_call(
            {
                "size": size,
                "_source": {"excludes": SOURCE_EXCLUDES},
                "query": {
                    "neural": {"embedding": {"query_text": query, "model_id": model_id, "k": size}}
                },
            }
        )
        # kNN returns k neighbors for ANY query — cut noise before fusion so an
        # off-corpus question yields an honest miss, not a fabricated answer.
        return neural_leg_floor(hits)

    async def _resolve_model_id(self) -> str | None:
        """Bootstrap normally sets the id; this lazy path covers a service
        whose bootstrap was skipped. One failed lookup is remembered so the
        neural leg doesn't hammer a model-less cluster every turn."""
        if self._model_id is not None:
            return self._model_id
        if self._model_lookup_failed:
            return None
        try:
            found = await self._find_model()
        except httpx.HTTPError:
            return None
        if found is None:
            self._model_lookup_failed = True
            return None
        self._model_id = found[0]
        return self._model_id

    async def _search_call(self, body: dict) -> list[KBHit]:
        if not self._enabled:
            raise KBUnavailable("knowledge base disabled")
        if not self._breaker.allow():
            raise KBUnavailable("knowledge base temporarily unavailable (breaker open)")
        try:
            resp = await self._get_client().post(f"/{KNOWLEDGE_INDEX}/_search", json=body)
            resp.raise_for_status()
        except httpx.HTTPError as err:
            self._breaker.record_failure()
            raise KBUnavailable(f"knowledge base unreachable: {err.__class__.__name__}") from err
        try:
            hits = [_hit_to_kbhit(h) for h in resp.json()["hits"]["hits"]]
        except (ValueError, KeyError, TypeError) as err:
            # A 200 that isn't a search response (intercepting proxy, truncated
            # body) is a KB-didn't-answer turn, never a 500 (types.KBUnavailable).
            self._breaker.record_failure()
            raise KBUnavailable(
                f"knowledge base answered unusably: {err.__class__.__name__}"
            ) from err
        self._breaker.record_success()
        return hits


def _is_parent_technique(id_: str) -> bool:
    return len(id_) == _TECHNIQUE_PARENT_LEN and id_[0] == "T" and id_[1:].isdigit()


def _hit_to_kbhit(hit: dict) -> KBHit:
    src = hit["_source"]
    return KBHit(
        chunk_id=hit["_id"],
        doc_id=src.get("doc_id", ""),
        title=src.get("title", ""),
        text=src.get("content", ""),
        doc_type=src.get("doc_type", ""),
        source=src.get("source", ""),
        source_ref=src.get("source_ref", ""),
        ids=tuple(src.get("ids", ())),
        severity=src.get("severity", ""),
        cvss_score=src.get("cvss_score"),
        score=float(hit.get("_score") or 0.0),
    )


def _json_line(obj: dict) -> str:
    return json.dumps(obj, ensure_ascii=False)
