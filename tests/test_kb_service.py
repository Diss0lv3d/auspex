"""KnowledgeService vs a scripted OpenSearch — hermetic (httpx.MockTransport).

Response bodies are trimmed copies of live shapes captured in
docs/probes/2026-07-17-opensearch-knn-ml.md (search hits, ML model search,
task states, bulk results). No live cluster in pytest.
"""

import json

import httpx
import pytest

from auspex.enrich.breaker import CircuitBreaker
from auspex.kb.chunking import chunk_doc
from auspex.kb.mapping import KNOWLEDGE_INDEX
from auspex.kb.seed import load_seed_docs
from auspex.kb.service import MODEL_LOOKUP_RETRY_SECONDS, KnowledgeService, seed_fingerprint
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
        self.garbage_search = False  # 200 with a non-search body (proxy page)

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
            if self.garbage_search:
                return httpx.Response(200, text="<html>502 Bad Gateway</html>")
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


async def test_id_query_with_unknown_id_is_an_honest_miss():
    # No fuzzy-prose fallback: "what is CVE-2099-9999" with the ID absent must
    # miss, not surface whatever doc "what is" fuzzily matches (live-caught
    # failure mode 2026-07-17 on the free-text path; same rail here).
    router = Router()
    router.id_hits = []
    router.bm25_hits = [kb_hit("T1059#0", 4.2)]  # would be noise if consulted
    svc = service_with(router)
    assert await svc.search("what is CVE-2099-9999") == []
    search_bodies = [b for _, p, b in router.requests if p == f"/{KNOWLEDGE_INDEX}/_search"]
    assert len(search_bodies) == 1  # the ID rail only — no BM25, no neural


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


async def test_off_corpus_query_is_an_honest_miss_not_fabricated():
    # Live-caught 2026-07-17: "what is quantum entanglement" → BM25 4.4 on a
    # C2 doc (stopword/fuzzy noise) while every neural score sat below the 0.6
    # floor (top 0.586). The post-floor-empty neural leg is the relevance
    # gate: BM25 hits without neural agreement are noise, not an answer.
    router = Router()
    router.bm25_hits = [kb_hit("CONCEPT-C2#0", 4.4)]
    router.neural_hits = [kb_hit("CONCEPT-C2#0", 0.586), kb_hit("T1055#0", 0.553)]
    svc = service_with(router)
    assert await svc.search("what is quantum entanglement") == []


async def test_unavailable_public_detail_stays_analyst_calm():
    # S6 review: "(breaker open)" / "ConnectTimeout" were reaching chat copy.
    # Every KBUnavailable path must carry a jargon-free `public` clause; the
    # diagnostic stays on the exception message (logs/tests only).
    jargon = ("breaker", "Error", "Timeout", "Exception", "http", "OpenSearch", ":")

    async def public_of(svc) -> str:
        with pytest.raises(KBUnavailable) as excinfo:
            await svc.lookup_ids(("CVE-2021-44228",))
        return excinfo.value.public

    open_breaker = CircuitBreaker(threshold=1, clock=lambda: 0.0)
    open_breaker.record_failure()
    garbage = Router()
    garbage.garbage_search = True
    unroutable = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda r: httpx.Response(503)),
        base_url="http://opensearch.test",
    )
    for svc in (
        service_with(Router(), breaker=open_breaker),
        service_with(garbage),
        KnowledgeService("http://opensearch.test", client=unroutable),
        service_with(Router(), enabled=False),
    ):
        public = await public_of(svc)
        assert public, "public clause must exist"
        for term in jargon:
            assert term not in public, f"jargon {term!r} leaked into public copy: {public!r}"


async def test_garbage_200_response_is_kb_unavailable_not_a_crash():
    # S6 review: the never-a-500 invariant (types.KBUnavailable docstring) must
    # survive a 200 whose body is not a search response (intercepting proxy,
    # truncated JSON) — parse errors must not escape to the route layer.
    router = Router()
    router.garbage_search = True
    svc = service_with(router)
    with pytest.raises(KBUnavailable, match="answered unusably"):
        await svc.lookup_ids(("CVE-2021-44228",))


async def test_both_legs_dead_raises_unavailable_and_counts_breaker_failure():
    router = Router()
    router.fail_bm25 = True
    router.fail_neural = True
    breaker = CircuitBreaker(threshold=1, clock=lambda: 0.0)
    svc = service_with(router, breaker=breaker)
    with pytest.raises(KBUnavailable):
        await svc.search("how does lateral movement work")
    assert breaker.state == "open"


async def test_one_failing_turn_does_not_open_the_default_breaker():
    # S6 review: a dead hybrid turn is TWO leg failures, not three — with the
    # default threshold (3) a single transient blip must not cost 60 s of
    # "temporarily unavailable"; the second consecutive dead turn opens it.
    router = Router()
    router.fail_bm25 = True
    router.fail_neural = True
    breaker = CircuitBreaker(clock=lambda: 0.0)  # default threshold = 3
    svc = service_with(router, breaker=breaker)
    with pytest.raises(KBUnavailable):
        await svc.search("how does lateral movement work")
    assert breaker.state == "closed"  # one blip ≠ an outage
    with pytest.raises(KBUnavailable):
        await svc.search("how does lateral movement work")
    assert breaker.state == "open"  # two consecutive dead turns do


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


async def test_model_lookup_retries_after_cooldown_and_heals():
    # S6 review: the no-model memo was permanent — a cluster that recovered
    # (model redeployed) left the neural leg dead until app restart. After the
    # cooldown the lookup retries; a healed cluster restores hybrid search.
    router = Router()
    router.model_found = False
    router.bm25_hits = [kb_hit("A#0", 5.0)]
    now = {"t": 0.0}
    svc = service_with(router, clock=lambda: now["t"])
    await svc.search("how does lateral movement work")  # memoized miss at t=0
    await svc.search("more prose about beacons")  # inside cooldown: no re-lookup

    def searches() -> int:
        return len([p for _, p, _ in router.requests if p == "/_plugins/_ml/models/_search"])

    assert searches() == 1
    router.model_found = True  # cluster healed
    router.neural_hits = [kb_hit("A#0", 0.9)]
    now["t"] = MODEL_LOOKUP_RETRY_SECONDS + 1
    hits = await svc.search("prose about lateral movement")
    assert searches() == 2  # cooldown elapsed ⇒ one retry
    assert [h.chunk_id for h in hits] == ["A#0"]
    neural_bodies = [
        b
        for _, p, b in router.requests
        if p == f"/{KNOWLEDGE_INDEX}/_search" and "neural" in b.get("query", {})
    ]
    assert neural_bodies, "neural leg must be live again after the model heals"


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
        self.seed_fp: str | None = None  # what PUT _mapping stamped
        self.cluster_setting: str | None = None  # operator-set value, if any

    def __call__(self, request: httpx.Request) -> httpx.Response:
        path, method = request.url.path, request.method
        self.requests.append((method, path))
        if path == "/_cluster/settings" and method == "GET":
            persistent = (
                {"plugins.ml_commons.only_run_on_ml_node": self.cluster_setting}
                if self.cluster_setting is not None
                else {}
            )
            return httpx.Response(200, json={"persistent": persistent, "transient": {}})
        if path == "/_cluster/settings":
            return httpx.Response(200, json={"acknowledged": True})
        if path == f"/{KNOWLEDGE_INDEX}/_mapping" and method == "GET":
            meta = {"_meta": {"seed_fingerprint": self.seed_fp}} if self.seed_fp else {}
            return httpx.Response(
                200, json={KNOWLEDGE_INDEX: {"mappings": {"dynamic": "strict", **meta}}}
            )
        if path == f"/{KNOWLEDGE_INDEX}/_mapping" and method == "PUT":
            self.seed_fp = json.loads(request.read())["_meta"]["seed_fingerprint"]
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
    # fingerprint stamps only AFTER the ingest — a crash mid-bulk must leave
    # no stamp, so the next boot re-ingests (self-heal)
    assert router.seed_fp is not None
    assert router.requests.index(("PUT", f"/{KNOWLEDGE_INDEX}/_mapping")) > router.requests.index(
        ("POST", "/_bulk")
    )
    # model id is now resolved — hybrid search would use it without re-lookup
    assert await svc._resolve_model_id() == MODEL_ID


def _real_seed_fingerprint() -> str:
    return seed_fingerprint([c for d in load_seed_docs() for c in chunk_doc(d)])


async def test_bootstrap_warm_volume_no_ops():
    router = BootstrapRouter()
    router.index_created = True
    router.seed_fp = _real_seed_fingerprint()  # index already carries this seed
    original_call = router.__call__

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/_plugins/_ml/models/_search":
            return httpx.Response(200, json=model_search_response(True))  # DEPLOYED
        return original_call(request)

    client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="http://opensearch.test"
    )
    svc = KnowledgeService("http://opensearch.test", client=client)
    summary = await svc.bootstrap()
    assert "already deployed" in summary
    assert "exists" in summary
    assert "seed present" in summary
    assert router.bulk_batches == 0  # matching fingerprint ⇒ no re-ingest


async def test_bootstrap_reingests_when_seed_content_changed():
    # S6 review: the old count>=expected check served EDITED seed text stale
    # forever (same chunk count, different content). A stale fingerprint must
    # re-ingest and re-stamp.
    router = BootstrapRouter()
    router.index_created = True
    router.seed_fp = "stale-fingerprint-from-an-older-seed-corpus"
    original_call = router.__call__

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/_plugins/_ml/models/_search":
            return httpx.Response(200, json=model_search_response(True))
        return original_call(request)

    client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="http://opensearch.test"
    )
    svc = KnowledgeService("http://opensearch.test", client=client)
    summary = await svc.bootstrap()
    assert "seeded" in summary
    assert router.bulk_batches >= 1
    assert router.seed_fp == _real_seed_fingerprint()  # re-stamped to current


async def test_bootstrap_respects_operator_set_ml_node_setting():
    # S6 review: bootstrap must never stomp an EXPLICIT persistent cluster
    # setting — write only when the key is absent.
    router = BootstrapRouter()
    router.cluster_setting = "true"  # operator chose dedicated ML nodes
    router.index_created = True
    router.seed_fp = _real_seed_fingerprint()
    original_call = router.__call__

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/_plugins/_ml/models/_search":
            return httpx.Response(200, json=model_search_response(True))
        return original_call(request)

    client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="http://opensearch.test"
    )
    svc = KnowledgeService("http://opensearch.test", client=client)
    await svc.bootstrap()
    assert ("PUT", "/_cluster/settings") not in router.requests
    # absent key ⇒ the dev-single-node default IS written
    fresh = BootstrapRouter()
    client2 = httpx.AsyncClient(
        transport=httpx.MockTransport(fresh), base_url="http://opensearch.test"
    )
    await KnowledgeService("http://opensearch.test", client=client2).bootstrap()
    assert ("PUT", "/_cluster/settings") in fresh.requests


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
