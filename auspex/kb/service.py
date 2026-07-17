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
import hashlib
import json
import logging
import time
from collections.abc import Callable
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
from auspex.kb.types import KBChunk, KBDoc, KBHit, KBUnavailable

logger = logging.getLogger("auspex.kb")

CALL_TIMEOUT_SECONDS = 6.0
BOOTSTRAP_CALL_TIMEOUT_SECONDS = 30.0
TASK_POLL_INTERVAL_SECONDS = 2.0
TASK_POLL_BUDGET_SECONDS = 180.0  # fresh-volume register+deploy measured ~15 s; 12x headroom
EMBED_BATCH_SIZE = 16  # probed sweet spot: ~8 ms/text amortized

# A failed model lookup is remembered this long, then retried — not forever
# (S6 review: a cluster that recovered after boot left the neural leg dead
# until app restart).
MODEL_LOOKUP_RETRY_SECONDS = 60.0

# Technique-shaped ids get a prefix clause so a parent id (T1059) also pulls
# its sub-techniques (T1059.001) — term alone can't (keyword field).
_TECHNIQUE_PARENT_LEN = 5  # "T1059"

# Boundary cap for one turn's ID lookup: a 32k-char message can carry ~2000
# CVE ids; unbounded ids would blow OpenSearch's bool-clause limit (1024) and
# trip the shared breaker for every user. Callers that cap MUST say so in the
# rendered copy (render_cve_answer's `omitted`) — a capped CVE must never
# render as a KB miss. S6 review finding.
MAX_IDS_PER_LOOKUP = 25


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
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._auth = auth
        self._enabled = enabled and bool(base_url)
        self._client = client
        self._owns_client = client is None
        self._breaker = breaker or CircuitBreaker()
        self._call_timeout = call_timeout
        self._clock = clock
        self._model_id: str | None = None
        self._model_lookup_failed_at: float | None = None
        self._bootstrapped = False

    @classmethod
    def from_settings(cls, settings: Settings) -> "KnowledgeService":
        auth = None
        if settings.opensearch_user and settings.opensearch_pass:
            auth = (settings.opensearch_user, settings.opensearch_pass)
        return cls(settings.opensearch_url, auth=auth, enabled=settings.kb_enabled)

    @property
    def active(self) -> bool:
        return self._enabled

    @property
    def bootstrapped(self) -> bool:
        """True once a bootstrap fully succeeded (or the KB is disabled — no
        work pending). Ingest gates cycles on this: writing through _bulk
        before _ensure_index ran would auto-create a dynamic-mapping index
        that later boots accept as healthy forever (S8 review)."""
        return self._bootstrapped

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
            self._bootstrapped = True  # nothing pending — don't gate ingest forever
            return "kb disabled"
        steps: list[str] = []
        try:
            await self._ensure_ml_settings()
            self._model_id, model_step = await self._ensure_model()
            steps.append(model_step)
            steps.append(await self._ensure_index())
            steps.append(await self._ensure_mapping_fields())
            steps.append(await self._ensure_seed())
            self._breaker.record_success()
            self._bootstrapped = True
            return "; ".join(steps)
        except Exception as err:  # noqa: BLE001 — startup must survive anything
            logger.exception("kb bootstrap failed")
            return f"kb bootstrap failed after [{'; '.join(steps) or 'nothing'}]: {err}"

    async def _ensure_ml_settings(self) -> None:
        # Single-node dev/CI: ML must run on the data node, and a fresh volume
        # forgets the setting (probed). An operator's EXPLICIT persistent choice
        # (either value) is respected — we write only when the key is absent
        # (S6 review: the unconditional PUT stomped cluster-wide config on
        # every boot). Values arrive as strings ("false") — live-verified.
        client = self._get_client()
        resp = await client.get(
            "/_cluster/settings",
            params={"flat_settings": "true"},
            timeout=BOOTSTRAP_CALL_TIMEOUT_SECONDS,
        )
        resp.raise_for_status()
        current = resp.json().get("persistent", {}).get("plugins.ml_commons.only_run_on_ml_node")
        if current is not None:
            return
        resp = await client.put(
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

    async def _ensure_mapping_fields(self) -> str:
        """Additive mapping upgrade for indexes created before a field existed.
        dynamic:strict rejects unknown fields at ingest, so a volume that
        predates S7's KEV/EPSS fields would fail every ingest without this.
        Only ADDS missing properties — never mutates existing ones (OpenSearch
        forbids in-place type changes anyway)."""
        client = self._get_client()
        resp = await client.get(f"/{KNOWLEDGE_INDEX}/_mapping")
        resp.raise_for_status()
        have = resp.json()[KNOWLEDGE_INDEX]["mappings"].get("properties", {})
        wanted: dict = KNOWLEDGE_MAPPING["mappings"]["properties"]
        missing = {name: spec for name, spec in wanted.items() if name not in have}
        if not missing:
            return "mapping current"
        resp = await client.put(
            f"/{KNOWLEDGE_INDEX}/_mapping",
            json={"properties": missing},
            timeout=BOOTSTRAP_CALL_TIMEOUT_SECONDS,
        )
        resp.raise_for_status()
        return f"mapping upgraded (+{len(missing)} fields)"

    async def _ensure_seed(self) -> str:
        docs = load_seed_docs()
        chunks = [c for d in docs for c in chunk_doc(d)]
        fingerprint = seed_fingerprint(chunks)
        client = self._get_client()
        resp = await client.get(f"/{KNOWLEDGE_INDEX}/_mapping")
        resp.raise_for_status()
        meta = resp.json()[KNOWLEDGE_INDEX]["mappings"].get("_meta", {})
        if meta.get("seed_fingerprint") == fingerprint:
            return f"seed present ({len(chunks)} chunks, fingerprint match)"
        # Content — not chunk COUNT — drives re-ingest: an edited seed doc with
        # an unchanged count used to be served stale forever (S6 review).
        # Upsert by chunk_id keeps replays idempotent; the fingerprint stamp
        # lands only after a full successful ingest, so a partial seed (crash
        # mid-bulk) self-heals on the next boot.
        ingested = await self.ingest_docs(docs)
        resp = await client.put(
            f"/{KNOWLEDGE_INDEX}/_mapping",
            # Replaces _meta wholesale (live-verified on strict mappings) —
            # switch to read-merge-write if _meta ever grows more keys.
            json={"_meta": {"seed_fingerprint": fingerprint}},
            timeout=BOOTSTRAP_CALL_TIMEOUT_SECONDS,
        )
        resp.raise_for_status()
        return f"seeded {ingested} chunks"

    # ── Ingestion (bootstrap now; S7 feeds call this too) ────────────────

    async def embed(self, texts: list[str]) -> list[list[float]]:
        # Resolve lazily, exactly like the neural search leg — a bootstrap
        # that failed at boot must not brick ingest until app restart
        # (S8 review: only _neural had the lazy heal).
        model_id = await self._resolve_model_id()
        if model_id is None:
            raise KBUnavailable("embedding model not resolved")
        resp = await self._get_client().post(
            f"/_plugins/_ml/_predict/text_embedding/{model_id}",
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
                    _json_line({**_chunk_payload(chunk), "ingested_at": now, "embedding": vector})
                )
            resp = await self._get_client().post(
                "/_bulk",
                content="\n".join(lines) + "\n",
                headers={"Content-Type": "application/x-ndjson"},
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
        if total:
            # One refresh per ingest call, not one per 16-chunk bulk batch — a
            # catch-up window is thousands of batches and per-batch forced
            # refreshes churn segments on the 1 GiB single node (S8 review).
            # Nothing reads-after-write WITHIN a cycle; searches need the data
            # visible once the call completes.
            resp = await self._get_client().post(
                f"/{KNOWLEDGE_INDEX}/_refresh", timeout=BOOTSTRAP_CALL_TIMEOUT_SECONDS
            )
            resp.raise_for_status()
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

    async def search(
        self, query: str, *, top_k: int = 5, doc_types: tuple[str, ...] | None = None
    ) -> list[KBHit]:
        """The retrieval front door. ID-dominant → ID rail only (an unknown ID
        is an honest miss — no fuzzy-prose fallback; SARA's BM25 fallback
        existed for its prefixed doc-id zoo, which our `ids` field replaces);
        otherwise hybrid BM25+neural RRF with a regime-aware floor.
        Raises KBUnavailable when the KB can't answer.

        `doc_types` filters BOTH legs. This is load-bearing for recall, not
        just relevance (live-probed 2026-07-17 at ~2.5k chunks): unfiltered
        lucene kNN at k=10 returned ten mid-0.5s CVE chunks while the true
        best match (cosine 0.840) wasn't in the list at all — HNSW recall
        collapses at small k on a grown graph — and two noise chunks crossed
        the 0.6 floor for an off-corpus query (max-of-N cosine grows with N).
        A filter over a small doc_type subset makes lucene kNN exact."""
        if is_id_query(query):
            return await self.lookup_ids(extract_kb_ids(query), top_k=top_k)
        bm25_task = self._bm25(query, top_k * 2, doc_types)
        neural_task = self._neural(query, top_k * 2, doc_types)
        bm25, neural = await asyncio.gather(bm25_task, neural_task, return_exceptions=True)
        if isinstance(bm25, BaseException) and isinstance(neural, BaseException):
            # Each leg already recorded its own breaker failure in _search_call —
            # recording a third here made ONE failing turn open the breaker
            # (threshold 3) on a single transient blip. S6 review finding.
            raise KBUnavailable(f"search failed: {bm25}", public="it was unreachable")
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

    async def _bm25(
        self, query: str, size: int, doc_types: tuple[str, ...] | None = None
    ) -> list[KBHit]:
        match: dict = {
            "multi_match": {
                "query": query,
                "fields": ["content^3", "title^2"],
                "type": "best_fields",
                "fuzziness": "AUTO",
                # Damp stopword-only matches ("what is …" hits every
                # doc): >2 terms ⇒ 75% must match.
                "minimum_should_match": "2<75%",
            }
        }
        if doc_types:
            match = {"bool": {"must": match, "filter": {"terms": {"doc_type": list(doc_types)}}}}
        return await self._search_call(
            {"size": size, "_source": {"excludes": SOURCE_EXCLUDES}, "query": match}
        )

    async def _neural(
        self, query: str, size: int, doc_types: tuple[str, ...] | None = None
    ) -> list[KBHit]:
        model_id = await self._resolve_model_id()
        if model_id is None:
            raise KBUnavailable("embedding model not available")
        embedding: dict = {"query_text": query, "model_id": model_id, "k": size}
        if doc_types:
            # lucene kNN evaluates the filter DURING traversal and goes exact
            # on small subsets — this restores recall, it doesn't just trim
            # (probe 2026-07-17: filtered top = cosine 0.840; unfiltered k=10
            # missed that chunk entirely).
            embedding["filter"] = {"terms": {"doc_type": list(doc_types)}}
        hits = await self._search_call(
            {
                "size": size,
                "_source": {"excludes": SOURCE_EXCLUDES},
                "query": {"neural": {"embedding": embedding}},
            }
        )
        # kNN returns k neighbors for ANY query — cut noise before fusion so an
        # off-corpus question yields an honest miss, not a fabricated answer.
        return neural_leg_floor(hits)

    async def _resolve_model_id(self) -> str | None:
        """Bootstrap normally sets the id; this lazy path covers a service
        whose bootstrap was skipped or failed. A no-model result is remembered
        for MODEL_LOOKUP_RETRY_SECONDS — long enough not to hammer a model-less
        cluster every turn, short enough that a cluster which recovers (model
        redeployed, volume restored) heals the neural leg without an app
        restart (S6 review)."""
        if self._model_id is not None:
            return self._model_id
        if (
            self._model_lookup_failed_at is not None
            and self._clock() - self._model_lookup_failed_at < MODEL_LOOKUP_RETRY_SECONDS
        ):
            return None
        try:
            found = await self._find_model()
        except httpx.HTTPError:
            return None
        if found is None:
            self._model_lookup_failed_at = self._clock()
            return None
        self._model_id = found[0]
        self._model_lookup_failed_at = None
        return self._model_id

    async def list_cve_ids(self, *, max_ids: int = 10_000) -> list[str]:
        """Distinct CVE doc ids currently in the KB (terms agg on the keyword
        doc_id). S7 ingestion intersects this with the KEV catalog on its
        first run. Same failure semantics as search: KBUnavailable, never a 500."""
        if not self._enabled:
            raise KBUnavailable(
                "knowledge base disabled", public="it isn't enabled in this deployment"
            )
        if not self._breaker.allow():
            raise KBUnavailable(
                "knowledge base temporarily unavailable (breaker open)",
                public="it's paused briefly after repeated failures and retries on its own",
            )
        body = {
            "size": 0,
            "query": {"term": {"doc_type": "cve"}},
            "aggs": {"cve_ids": {"terms": {"field": "doc_id", "size": max_ids}}},
        }
        try:
            resp = await self._get_client().post(f"/{KNOWLEDGE_INDEX}/_search", json=body)
            resp.raise_for_status()
            buckets = resp.json()["aggregations"]["cve_ids"]["buckets"]
            ids = [b["key"] for b in buckets]
        except httpx.HTTPError as err:
            self._breaker.record_failure()
            raise KBUnavailable(
                f"knowledge base unreachable: {err.__class__.__name__}",
                public="it was unreachable",
            ) from err
        except (ValueError, KeyError, TypeError) as err:
            self._breaker.record_failure()
            raise KBUnavailable(
                f"knowledge base answered unusably: {err.__class__.__name__}",
                public="it returned an unusable response",
            ) from err
        self._breaker.record_success()
        return ids

    async def _search_call(self, body: dict) -> list[KBHit]:
        if not self._enabled:
            raise KBUnavailable(
                "knowledge base disabled", public="it isn't enabled in this deployment"
            )
        if not self._breaker.allow():
            raise KBUnavailable(
                "knowledge base temporarily unavailable (breaker open)",
                public="it's paused briefly after repeated failures and retries on its own",
            )
        try:
            resp = await self._get_client().post(f"/{KNOWLEDGE_INDEX}/_search", json=body)
            resp.raise_for_status()
        except httpx.HTTPError as err:
            self._breaker.record_failure()
            raise KBUnavailable(
                f"knowledge base unreachable: {err.__class__.__name__}",
                public="it was unreachable",
            ) from err
        try:
            hits = [_hit_to_kbhit(h) for h in resp.json()["hits"]["hits"]]
        except (ValueError, KeyError, TypeError) as err:
            # A 200 that isn't a search response (intercepting proxy, truncated
            # body) is a KB-didn't-answer turn, never a 500 (types.KBUnavailable).
            self._breaker.record_failure()
            raise KBUnavailable(
                f"knowledge base answered unusably: {err.__class__.__name__}",
                public="it returned an unusable response",
            ) from err
        self._breaker.record_success()
        return hits


def _is_parent_technique(id_: str) -> bool:
    return len(id_) == _TECHNIQUE_PARENT_LEN and id_[0] == "T" and id_[1:].isdigit()


def _chunk_payload(chunk: KBChunk) -> dict:
    """The indexed body for one chunk, minus per-ingest fields (embedding,
    ingested_at). Shared by ingest and the seed fingerprint so the fingerprint
    can never drift from what actually gets written."""
    return {
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
        "kev_date_added": chunk.doc.kev_date_added,
        "kev_ransomware": chunk.doc.kev_ransomware,
        "epss_score": chunk.doc.epss_score,
        "epss_percentile": chunk.doc.epss_percentile,
        "epss_date": chunk.doc.epss_date,
        "workspace_id": "",
    }


def seed_fingerprint(chunks: list[KBChunk]) -> str:
    """Deterministic content hash of the seed corpus as it would be indexed."""
    payload = json.dumps(
        [_chunk_payload(c) for c in sorted(chunks, key=lambda c: c.chunk_id)],
        sort_keys=True,
        ensure_ascii=False,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


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
        kev_date_added=src.get("kev_date_added") or "",
        kev_ransomware=bool(src.get("kev_ransomware")),
        epss_score=src.get("epss_score"),
        epss_percentile=src.get("epss_percentile"),
        epss_date=src.get("epss_date") or "",
    )


def _json_line(obj: dict) -> str:
    return json.dumps(obj, ensure_ascii=False)
