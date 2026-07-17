"""S6: KB-backed cve_lookup/definition shortcut turns — LLM-free, KB-mockable
at app.state.kb (the S5 enrichment seam pattern). Three truths, three copies:
inactive ⇒ static deferred; active-but-down ⇒ "didn't answer this turn";
active-but-ignorant ⇒ explicit miss."""

import json

from _fakes import FakeKnowledgeService, StreamingFakeLLMClient

from auspex.kb.echo import CVE_MISS_LINE, DEFINITION_MISS_COPY
from auspex.kb.types import KBHit
from auspex.llm.client import StreamEvent
from auspex.routes.chat import ChatEndpoint, ChatEndpointResolver, get_endpoint_resolver

CHAT_EMAIL = "analyst@auspex.dev"


def _token(client) -> str:
    return client.post("/api/auth/dev-login", json={"email": CHAT_EMAIL}).json()["access_token"]


def _frames(body: str) -> list[dict]:
    out = []
    for line in body.splitlines():
        line = line.strip()
        if line.startswith("data:"):
            out.append(json.loads(line[len("data:") :].strip()))
    return out


def _use(app, fake, *, native_reasoning: bool = True):
    app.dependency_overrides[get_endpoint_resolver] = lambda: ChatEndpointResolver.fixed(
        ChatEndpoint(client=fake, native_reasoning=native_reasoning, id="test")
    )


def _post(client, message: str):
    return client.post(
        "/api/chat",
        json={"message": message},
        headers={"Authorization": f"Bearer {_token(client)}"},
    )


def _content(resp) -> tuple[str, list[dict]]:
    frames = _frames(resp.text)
    return "".join(f["content"] for f in frames if "content" in f), frames


def log4shell_hit() -> KBHit:
    return KBHit(
        chunk_id="CVE-2021-44228#0",
        doc_id="CVE-2021-44228",
        title="CVE-2021-44228",
        text="Apache Log4j2 JNDI features do not protect against attacker controlled endpoints.",
        doc_type="cve",
        source="nvd",
        source_ref="https://nvd.nist.gov/vuln/detail/CVE-2021-44228",
        ids=("CVE-2021-44228",),
        severity="CRITICAL",
        cvss_score=10.0,
        score=10.0,
    )


def concept_hit() -> KBHit:
    return KBHit(
        chunk_id="CONCEPT-LATERAL-MOVEMENT#0",
        doc_id="CONCEPT-LATERAL-MOVEMENT",
        title="Lateral movement",
        text="Lateral movement is the phase of an intrusion where an adversary moves…",
        doc_type="concept",
        source="auspex-seed",
        source_ref="",
        ids=(),
        severity="",
        cvss_score=None,
        score=0.016,
    )


def _swap_kb(app, fake):
    real = app.state.kb
    app.state.kb = fake
    return real


def test_cve_lookup_with_active_kb_answers_with_zero_llm_calls(client):
    fake_llm = StreamingFakeLLMClient([StreamEvent(kind="content", text="NEVER SENT")])
    _use(client.app, fake_llm)
    fake_kb = FakeKnowledgeService(hits=[log4shell_hit()])
    real_kb = _swap_kb(client.app, fake_kb)
    try:
        resp = _post(client, "CVE-2021-44228")
        assert resp.status_code == 200
        content, frames = _content(resp)
        assert frames[-1]["done"]["path"] == "shortcut"
        assert fake_llm.stream_calls == []  # the KB answered; the model never ran
        assert fake_kb.lookup_calls == [("CVE-2021-44228",)]
        assert fake_kb.search_calls == []  # exact-ID rail, not free-text search
        assert "CVE-2021-44228 — CRITICAL (CVSS 10.0)" in content
        assert "Log4j2" in content
        assert "Source: NVD" in content
        assert "NEVER SENT" not in content and "deferred" not in content
    finally:
        _swap_kb(client.app, real_kb)
        client.app.dependency_overrides.clear()


def test_cve_lookup_caps_per_turn_and_says_so_instead_of_false_misses(client):
    # S6 review: unbounded id lists blow OpenSearch's bool-clause limit, and the
    # default top_k (8 chunks) rendered overflow CVEs as false "not in the
    # knowledge base" misses. 27 requested ⇒ 25 read (scaled fetch), the other
    # 2 explicitly deferred to a follow-up — never claimed absent.
    _use(client.app, StreamingFakeLLMClient([]))
    fake_kb = FakeKnowledgeService(hits=[])
    real_kb = _swap_kb(client.app, fake_kb)
    try:
        cves = [f"CVE-2024-{1000 + i}" for i in range(27)]
        content, _ = _content(_post(client, " ".join(cves)))
        assert len(fake_kb.lookup_calls) == 1
        assert fake_kb.lookup_calls[0] == tuple(cves[:25])
        assert fake_kb.lookup_topks == [100]  # 4 chunks per requested CVE
        assert "2 more were requested — I read up to 25 per turn" in content
        assert cves[25] not in content and cves[26] not in content  # no false miss lines
    finally:
        _swap_kb(client.app, real_kb)
        client.app.dependency_overrides.clear()


def test_cve_lookup_dedupes_repeated_ids(client):
    _use(client.app, StreamingFakeLLMClient([]))
    fake_kb = FakeKnowledgeService(hits=[log4shell_hit()])
    real_kb = _swap_kb(client.app, fake_kb)
    try:
        content, _ = _content(_post(client, "CVE-2021-44228 and CVE-2021-44228 again"))
        assert fake_kb.lookup_calls == [("CVE-2021-44228",)]
        assert content.count("CVE-2021-44228 — CRITICAL") == 1  # one block, not two
        assert "more were requested" not in content  # dedupe is not an omission
    finally:
        _swap_kb(client.app, real_kb)
        client.app.dependency_overrides.clear()


def test_cve_lookup_kb_miss_is_explicit_not_deferred(client):
    _use(client.app, StreamingFakeLLMClient([]))
    fake_kb = FakeKnowledgeService(hits=[])  # connected, knows nothing
    real_kb = _swap_kb(client.app, fake_kb)
    try:
        content, _ = _content(_post(client, "CVE-2099-9999"))
        assert CVE_MISS_LINE in content
        assert "deferred" not in content  # connected-but-ignorant ≠ not connected
    finally:
        _swap_kb(client.app, real_kb)
        client.app.dependency_overrides.clear()


def test_cve_lookup_kb_down_says_didnt_answer_this_turn(client):
    _use(client.app, StreamingFakeLLMClient([]))
    fake_kb = FakeKnowledgeService(unavailable=True)
    real_kb = _swap_kb(client.app, fake_kb)
    try:
        content, frames = _content(_post(client, "CVE-2021-44228"))
        assert frames[-1]["done"]["path"] == "shortcut"  # still no model fallback
        assert "didn't answer this turn" in content
        assert "unreachable" in content  # the honest detail (the calm public clause)
        # S6 review: the DIAGNOSTIC half (exception text, class names) is for
        # logs — the analyst sees only the public clause.
        assert "SimulatedConnectError" not in content
        assert "deferred" not in content
    finally:
        _swap_kb(client.app, real_kb)
        client.app.dependency_overrides.clear()


def test_cve_lookup_inactive_kb_keeps_the_deferred_copy(client):
    """Host runs pin KB_ENABLED=false — the S4 static copy must still stand."""
    assert client.app.state.kb.active is False  # the premise, explicit
    _use(client.app, StreamingFakeLLMClient([]))
    try:
        content, _ = _content(_post(client, "CVE-2021-44228"))
        assert "deferred" in content
        assert "CVE-2021-44228" in content
    finally:
        # the app is session-scoped: a failed assert must not leak the LLM
        # override into every later test (S6 review)
        client.app.dependency_overrides.clear()


def test_definition_with_active_kb_streams_the_kb_answer(client):
    fake_llm = StreamingFakeLLMClient([StreamEvent(kind="content", text="NEVER SENT")])
    _use(client.app, fake_llm)
    fake_kb = FakeKnowledgeService(hits=[concept_hit()])
    real_kb = _swap_kb(client.app, fake_kb)
    try:
        content, frames = _content(_post(client, "what is lateral movement"))
        assert frames[-1]["done"]["path"] == "shortcut"
        assert fake_llm.stream_calls == []
        assert fake_kb.search_calls == ["what is lateral movement"]
        # Definitions retrieve from curated docs only — never CVE record chunks
        # (live-caught 2026-07-17: at ~2.5k chunks the unfiltered kNN answered
        # "what is credential dumping" with a random CVE and off-corpus queries
        # crossed the floor — recall AND honesty depend on this filter).
        assert fake_kb.search_doc_types == [("concept", "technique", "tactic")]
        assert content.startswith("Lateral movement — from the knowledge base:")
        assert "Source: Auspex seed corpus" in content
    finally:
        _swap_kb(client.app, real_kb)
        client.app.dependency_overrides.clear()


def test_definition_kb_miss_gets_the_miss_copy_not_deferred(client):
    _use(client.app, StreamingFakeLLMClient([]))
    fake_kb = FakeKnowledgeService(hits=[])
    real_kb = _swap_kb(client.app, fake_kb)
    try:
        content, _ = _content(_post(client, "what is quantum hardening"))
        assert content == DEFINITION_MISS_COPY
    finally:
        _swap_kb(client.app, real_kb)
        client.app.dependency_overrides.clear()


def test_definition_kb_down_says_didnt_answer(client):
    _use(client.app, StreamingFakeLLMClient([]))
    fake_kb = FakeKnowledgeService(unavailable=True)
    real_kb = _swap_kb(client.app, fake_kb)
    try:
        content, _ = _content(_post(client, "what is lateral movement"))
        assert "didn't answer this turn" in content
    finally:
        _swap_kb(client.app, real_kb)
        client.app.dependency_overrides.clear()


def test_definition_inactive_kb_keeps_the_deferred_copy(client):
    assert client.app.state.kb.active is False
    _use(client.app, StreamingFakeLLMClient([]))
    try:
        content, _ = _content(_post(client, "what is lateral movement"))
        assert "deferred" in content
    finally:
        client.app.dependency_overrides.clear()
