"""KnowledgeService vs a scripted OpenSearch — hermetic (httpx.MockTransport).

Response bodies are trimmed copies of live shapes captured in
docs/probes/2026-07-17-opensearch-knn-ml.md (search hits, ML model search,
task states, bulk results). No live cluster in pytest.
"""

import json

import httpx
import pytest

from auspex.enrich.breaker import CircuitBreaker
from auspex.kb.mapping import KNOWLEDGE_INDEX
from auspex.kb.service import KnowledgeService
from auspex.kb.types import KBDoc, KBUnavailable

MODEL_ID = "model-abc123"


def kb_hit(chunk_id: str, score: float, *, ids: list[str] | None = None) -> dict:
    doc_id = chunk_id.split("#")[0]
    return {
        "_id": chunk_id,
        "_score": score,
        "_source": {
            "doc_id": doc_id,
            "title": f"Title of {doc_id}",
            "content": f"Body of {chunk_id}",
            "doc_type": "cve",
            "source": "nvd",
            "source_ref": f"https://nvd.nist.gov/vuln/detail/{doc_id}",
            "ids": ids if ids is not None else [doc_id],
            "severity": "CRITICAL",
            "cvss_score": 9.8,
        },
    }


def search_response(hits: list[dict]) -> dict:
    return {"hits": {"total": {"value": len(hits)}, "hits": hits}}


def model_search_response(found: bool, state: str = "DEPLOYED") -> dict:
    hits = (
        [{"_id": MODEL_ID, "_source": {"name": "the-model", "model_state": state}}] if found else []
    )
    return {"hits": {"hits": hits}}


class Router:
    """Records every request; routes by (method, path) with body-aware search
    routing (multi_match vs neural vs ids-rail)."""

    def __init__(self):
        self.requests: list[tuple[str, str, dict | None]] = []
        self.bm25_hits: list[dict] = []
        self.neural_hits: list[dict] = []
        self.id_hits: list[dict] = []
        self.fail_neural = False
        self.fail_bm25 = False
        self.model_found = True

    def body_of(self, request: httpx.Request) -> dict | None:
        content = request.read()
        if not content:
            return None
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            return {"_raw": content.decode()}

    def __call__(self, request: httpx.Request) -> httpx.Response:
        body = self.body_of(request)
        path = request.url.path
        self.requests.append((request.method, path, body))
        if path == "/_plugins/_ml/models/_search":
            return httpx.Response(200, json=model_search_response(self.model_found))
        if path == f"/{KNOWLEDGE_INDEX}/_search":
            query = body["query"]
            if "multi_match" in query:
                if self.fail_bm25:
                    return httpx.Response(500, json={"error": "bm25 boom"})
                return httpx.Response(200, json=search_response(self.bm25_hits))
            if "neural" in query:
                if self.fail_neural:
                    return httpx.Response(
                        500,
                        json={
                            "error": {"type": "status_exception", "reason": "Failed to find model"}
                        },
                    )
                return httpx.Response(200, json=search_response(self.neural_hits))
            return httpx.Response(200, json=search_response(self.id_hits))
        return httpx.Response(404, json={"error": "unrouted path " + path})


def service_with(router: Router, **kwargs) -> KnowledgeService:
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(router), base_url="http://opensearch.test"
    )
    return KnowledgeService("http://opensearch.test", client=client, **kwargs)


# ── lookup_ids (the exact-ID rail) ─────────────────────────────────────────


async def test_lookup_ids_builds_term_clauses_and_parses_hits():
    router = Router()
    router.id_hits = [kb_hit("CVE-2021-44228#0", 10.0)]
    svc = service_with(router)
    hits = await svc.lookup_ids(("cve-2021-44228",))
    assert len(hits) == 1
    assert hits[0].doc_id == "CVE-2021-44228"
    assert hits[0].severity == "CRITICAL" and hits[0].cvss_score == 9.8
    _, _, body = router.requests[-1]
    clauses = body["query"]["bool"]["should"]
    assert {"term": {"ids": {"value": "CVE-2021-44228", "boost": 10}}} in clauses
    # No prefix clause for CVE ids — CVE-2021-4 must never match CVE-2021-44228
    assert not any("prefix" in c for c in clauses)


async def test_lookup_ids_adds_prefix_only_for_parent_techniques():
    router = Router()
    svc = service_with(router)
    await svc.lookup_ids(("T1059", "T1059.001"))
    _, _, body = router.requests[-1]
    clauses = body["query"]["bool"]["should"]
    assert {"prefix": {"ids": {"value": "T1059.", "boost": 2}}} in clauses
    prefixes = [c for c in clauses if "prefix" in c]
    assert len(prefixes) == 1  # sub-technique id gets term only


async def test_lookup_ids_empty_input_short_circuits():
    router = Router()
    svc = service_with(router)
    assert await svc.lookup_ids(()) == []
    assert router.requests == []


# ── search: ID bypass ──────────────────────────────────────────────────────


async def test_id_dominant_query_never_touches_neural():
    router = Router()
    router.id_hits = [kb_hit("CVE-2021-44228#0", 10.0)]
    svc = service_with(router)
    hits = await svc.search("what is CVE-2021-44228")
    assert [h.chunk_id for h in hits] == ["CVE-2021-44228#0"]
    search_bodies = [b for _, p, b in router.requests if p == f"/{KNOWLEDGE_INDEX}/_search"]
    assert len(search_bodies) == 1
    assert "neural" not in json.dumps(search_bodies)


async def test_id_query_with_no_id_hits_falls_back_to_bm25_only():
    router = Router()
    router.id_hits = []
    router.bm25_hits = [kb_hit("T1059#0", 4.2)]
    svc = service_with(router)
    hits = await svc.search("what is CVE-2099-9999")
    assert [h.chunk_id for h in hits] == ["T1059#0"]
    search_bodies = [b for _, p, b in router.requests if p == f"/{KNOWLEDGE_INDEX}/_search"]
    assert len(search_bodies) == 2  # id rail, then bm25 — still no neural
    assert "neural" not in json.dumps(search_bodies)


# ── search: hybrid RRF ─────────────────────────────────────────────────────


async def test_hybrid_fuses_bm25_and_neural_with_rrf():
    router = Router()
    router.bm25_hits = [kb_hit("A#0", 12.0), kb_hit("B#0", 6.0)]
    router.neural_hits = [kb_hit("B#0", 0.9), kb_hit("C#0", 0.8)]
    svc = service_with(router)
    hits = await svc.search("how does lateral movement work")
    assert [h.chunk_id for h in hits][0] == "B#0"  # in both legs ⇒ top
    kinds = [
        ("neural" if "neural" in b["query"] else "bm25")
        for _, p, b in router.requests
        if p == f"/{KNOWLEDGE_INDEX}/_search"
    ]
    assert sorted(kinds) == ["bm25", "neural"]
    assert all(h.score < 0.1 for h in hits)  # RRF regime scores


async def test_hybrid_excludes_embedding_from_source():
    router = Router()
    svc = service_with(router)
    await svc.search("beaconing detection approaches")
    for _, path, body in router.requests:
        if path == f"/{KNOWLEDGE_INDEX}/_search":
            assert body["_source"] == {"excludes": ["embedding"]}


async def test_dead_neural_leg_degrades_to_bm25_only():
    router = Router()
    router.bm25_hits = [kb_hit("A#0", 5.0)]
    router.fail_neural = True
    svc = service_with(router)
    hits = await svc.search("how does lateral movement work")
    assert [h.chunk_id for h in hits] == ["A#0"]  # the turn still gets a KB answer


async def test_dead_bm25_leg_degrades_to_neural_only():
    router = Router()
    router.neural_hits = [kb_hit("A#0", 0.8)]
    router.fail_bm25 = True
    svc = service_with(router)
    hits = await svc.search("how does lateral movement work")
    assert [h.chunk_id for h in hits] == ["A#0"]


async def test_both_legs_dead_raises_unavailable_and_counts_breaker_failure():
    router = Router()
    router.fail_bm25 = True
    router.fail_neural = True
    breaker = CircuitBreaker(threshold=1, clock=lambda: 0.0)
    svc = service_with(router, breaker=breaker)
    with pytest.raises(KBUnavailable):
        await svc.search("how does lateral movement work")
    assert breaker.state == "open"


async def test_missing_model_makes_hybrid_serve_bm25_only():
    router = Router()
    router.model_found = False  # cold volume: no model registered
    router.bm25_hits = [kb_hit("A#0", 5.0)]
    svc = service_with(router)
    hits = await svc.search("how does lateral movement work")
    assert [h.chunk_id for h in hits] == ["A#0"]
    # the failed lookup is remembered — the next turn must not re-search models
    await svc.search("more prose about beacons")
    model_searches = [p for _, p, _ in router.requests if p == "/_plugins/_ml/models/_search"]
    assert len(model_searches) == 1


# ── breaker + disabled rails ───────────────────────────────────────────────


async def test_open_breaker_short_circuits_without_http():
    router = Router()
    breaker = CircuitBreaker(threshold=1, cooldown_seconds=60, clock=lambda: 0.0)
    breaker.record_failure()  # opens at threshold 1
    svc = service_with(router, breaker=breaker)
    with pytest.raises(KBUnavailable, match="temporarily unavailable"):
        await svc.lookup_ids(("CVE-2021-44228",))
    assert router.requests == []


async def test_disabled_service_raises_unavailable():
    svc = KnowledgeService("http://opensearch.test", enabled=False)
    assert svc.active is False
    with pytest.raises(KBUnavailable):
        await svc.lookup_ids(("CVE-2021-44228",))


# ── bootstrap (idempotent, never raises) ───────────────────────────────────


class BootstrapRouter:
    """Fresh-volume cluster: no model, no index, empty count. Scripted to
    exercise register → poll → deploy → index create → seed ingest."""

    def __init__(self):
        self.requests: list[tuple[str, str]] = []
        self.model_registered = False
        self.index_created = False
        self.bulk_batches = 0

    def __call__(self, request: httpx.Request) -> httpx.Response:
        path, method = request.url.path, request.method
        self.requests.append((method, path))
        if path == "/_cluster/settings":
            return httpx.Response(200, json={"acknowledged": True})
        if path == "/_plugins/_ml/models/_search":
            return httpx.Response(200, json=model_search_response(False))
        if path == "/_plugins/_ml/models/_register":
            body = json.loads(request.read())
            assert body["model_format"] == "ONNX"  # D-018 pin
            self.model_registered = True
            return httpx.Response(200, json={"task_id": "task-reg", "status": "CREATED"})
        if path == "/_plugins/_ml/tasks/task-reg":
            return httpx.Response(200, json={"state": "COMPLETED", "model_id": MODEL_ID})
        if path == f"/_plugins/_ml/models/{MODEL_ID}/_deploy":
            return httpx.Response(200, json={"task_id": "task-dep"})
        if path == "/_plugins/_ml/tasks/task-dep":
            return httpx.Response(200, json={"state": "COMPLETED"})
        if path == f"/{KNOWLEDGE_INDEX}" and method == "HEAD":
            return httpx.Response(200 if self.index_created else 404)
        if path == f"/{KNOWLEDGE_INDEX}" and method == "PUT":
            self.index_created = True
            return httpx.Response(200, json={"acknowledged": True})
        if path == f"/{KNOWLEDGE_INDEX}/_count":
            return httpx.Response(200, json={"count": 0})
        if path.startswith(f"/_plugins/_ml/_predict/text_embedding/{MODEL_ID}"):
            body = json.loads(request.read())
            n = len(body["text_docs"])
            vec = [0.1] * 4  # dim doesn't matter to the client code
            return httpx.Response(
                200,
                json={"inference_results": [{"output": [{"data": vec}]} for _ in range(n)]},
            )
        if path == "/_bulk":
            self.bulk_batches += 1
            return httpx.Response(200, json={"errors": False, "items": []})
        return httpx.Response(404, json={"error": f"unrouted {method} {path}"})


async def test_bootstrap_fresh_volume_runs_all_steps():
    router = BootstrapRouter()
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(router), base_url="http://opensearch.test"
    )
    svc = KnowledgeService("http://opensearch.test", client=client)
    summary = await svc.bootstrap()
    assert "registered + deployed" in summary
    assert "created" in summary
    assert "seeded" in summary
    assert router.model_registered and router.index_created
    assert router.bulk_batches >= 1
    # model id is now resolved — hybrid search would use it without re-lookup
    assert await svc._resolve_model_id() == MODEL_ID


async def test_bootstrap_warm_volume_no_ops():
    router = Router()  # model found + DEPLOYED
    seeded = {"count": 999}

    original_call = router.__call__

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/_cluster/settings":
            return httpx.Response(200, json={"acknowledged": True})
        if request.url.path == f"/{KNOWLEDGE_INDEX}" and request.method == "HEAD":
            return httpx.Response(200)
        if request.url.path == f"/{KNOWLEDGE_INDEX}/_count":
            return httpx.Response(200, json=seeded)
        return original_call(request)

    client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="http://opensearch.test"
    )
    svc = KnowledgeService("http://opensearch.test", client=client)
    summary = await svc.bootstrap()
    assert "already deployed" in summary
    assert "exists" in summary
    assert "seed present" in summary


async def test_bootstrap_never_raises_on_dead_cluster():
    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    client = httpx.AsyncClient(
        transport=httpx.MockTransport(refuse), base_url="http://opensearch.test"
    )
    svc = KnowledgeService("http://opensearch.test", client=client)
    summary = await svc.bootstrap()
    assert "failed" in summary  # reported, not raised


async def test_bootstrap_disabled_is_a_no_op():
    svc = KnowledgeService("http://opensearch.test", enabled=False)
    assert await svc.bootstrap() == "kb disabled"


# ── ingest ─────────────────────────────────────────────────────────────────


async def test_ingest_upserts_by_chunk_id_and_flags_bulk_errors():
    captured: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/_bulk":
            captured.append(request.read().decode())
            return httpx.Response(
                200,
                json={
                    "errors": True,
                    "items": [{"index": {"error": {"reason": "mapper_parsing_exception"}}}],
                },
            )
        if path.startswith("/_plugins/_ml/_predict"):
            body = json.loads(request.read())
            return httpx.Response(
                200,
                json={
                    "inference_results": [{"output": [{"data": [0.1]}]} for _ in body["text_docs"]]
                },
            )
        return httpx.Response(404)

    client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="http://opensearch.test"
    )
    svc = KnowledgeService("http://opensearch.test", client=client)
    svc._model_id = MODEL_ID
    doc = KBDoc(
        doc_id="CVE-2000-0001",
        title="CVE-2000-0001",
        content="An ancient bug.",
        doc_type="cve",
        source="nvd",
        source_ref="",
        ids=("CVE-2000-0001",),
    )
    with pytest.raises(RuntimeError, match="bulk ingest errors"):
        await svc.ingest_docs([doc])
    action_line = json.loads(captured[0].splitlines()[0])
    assert action_line["index"]["_id"] == "CVE-2000-0001#0"  # deterministic upsert id
