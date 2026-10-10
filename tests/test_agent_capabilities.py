"""Agent READ capability tools (S24) — the registry the running app never had.

These tests hold two lines that are easy to lose:

1. **The tools wrap existing code, they do not re-implement it.** Where a test
   can assert that the SAME service call was made with the SAME arguments the
   shortcut path uses, it does — a wrapper that quietly diverges is how the
   agent's answer and the shortcut's answer start disagreeing in one session.
2. **Three failures are three different truths.** Not connected, connected but
   unavailable, and connected but ignorant must never collapse into each other.
   That is the DEFERRED rail (SARA pattern, D-014 spirit), and a model handed
   the wrong one of the three writes a confident wrong answer.
"""

import pytest
from _fakes import FakeEnrichmentService, FakeKnowledgeService

from auspex.agent.capabilities import MAX_TOOL_ARG_ITEMS, SNIPPET_CHARS, build_capability_registry
from auspex.agent.registry import ToolLevel
from auspex.classify.observables import extract
from auspex.enrich.service import CAP_SKIP, ENRICH_MAX_OBSERVABLES
from auspex.enrich.types import (
    EnrichmentOutcome,
    ObservableEnrichment,
    ProviderSignal,
    VerdictLabel,
)
from auspex.kb.types import KBHit

TOOL_NAMES = ("enrich_observable", "lookup_cve", "search_knowledge")


def _obs(text: str):
    return extract(text).observables


def _cve_hit(cve="CVE-2021-44228", **over) -> KBHit:
    return KBHit(
        chunk_id=f"{cve}#0",
        doc_id=cve,
        title=cve,
        text=over.pop("text", "Apache Log4j2 JNDI lookups reach attacker-controlled endpoints."),
        doc_type="cve",
        source="nvd",
        source_ref=f"https://nvd.nist.gov/vuln/detail/{cve}",
        ids=over.pop("ids", (cve,)),
        severity=over.pop("severity", "CRITICAL"),
        cvss_score=over.pop("cvss_score", 10.0),
        score=10.0,
        **over,
    )


def _concept_hit() -> KBHit:
    return KBHit(
        chunk_id="CONCEPT-LATERAL-MOVEMENT#0",
        doc_id="CONCEPT-LATERAL-MOVEMENT",
        title="Lateral movement",
        text="Lateral movement is the phase of an intrusion where an adversary moves on.",
        doc_type="concept",
        source="auspex-seed",
        source_ref="",
        ids=(),
        severity="",
        cvss_score=None,
        score=4.0,
    )


def _build(*, enrichment=None, kb=None, observables=()):
    return build_capability_registry(
        enrichment=enrichment or FakeEnrichmentService(EnrichmentOutcome(items=())),
        kb=kb or FakeKnowledgeService(),
        observables=observables,
    )


# -- the registry itself ------------------------------------------------------


def test_the_running_app_can_build_a_registry_that_is_not_empty():
    """The blocker this module exists to clear: `ToolRegistry()` had no caller,
    so a loop wired into a route would have had nothing to call. The floor is
    explicit (S21's lesson) — `len(registry) >= 3` reports green with every tool
    removed if it is written as a truthiness check."""
    registry = _build()
    assert len(registry) == len(TOOL_NAMES)
    assert sorted(registry.names()) == sorted(TOOL_NAMES)


@pytest.mark.parametrize("name", TOOL_NAMES)
def test_every_capability_tool_is_read(name):
    """D-014: READ auto-executes, WRITE/DESTRUCTIVE are gated into proposals. A
    tool that fetches must never be filed under a level that lets it act, and a
    level is checked here rather than trusted to review."""
    assert _build().level(name) is ToolLevel.READ


@pytest.mark.parametrize("name", TOOL_NAMES)
def test_every_tool_offers_a_well_formed_wire_spec(name):
    """The envelope is what the endpoint actually receives. A required arg that
    is not in `properties` is the shape a model silently fails to call."""
    spec = next(s for s in _build().specs() if s["function"]["name"] == name)
    fn = spec["function"]
    assert fn["description"].strip()
    props = fn["parameters"]["properties"]
    assert props, f"{name} declares no parameters"
    for arg in fn["parameters"].get("required", []):
        assert arg in props, f"{name} requires {arg!r} but does not declare it"


# -- enrich_observable --------------------------------------------------------


async def test_enrichment_resolves_the_turns_own_observables_by_short_id():
    """The S2 harness finding, honoured: every model tested mangled long hashes
    in arguments, so the turn's observables are addressable by short id. The
    assertion that matters is the one about the SERVICE CALL — the tool must
    hand the real Observable through, not a string it re-parsed."""
    observables = _obs("check 185.220.101.5 please")
    obs = observables[0]
    service = FakeEnrichmentService(
        EnrichmentOutcome(
            items=(
                ObservableEnrichment(
                    observable=obs,
                    signals=(
                        ProviderSignal(
                            provider="ThreatFox",
                            label=VerdictLabel.MALICIOUS,
                            confidence=0.9,
                            summary="listed as a C2 host",
                        ),
                    ),
                    sources_answered=2,
                ),
            )
        )
    )
    registry = _build(enrichment=service, observables=observables)

    result = await registry.get("enrich_observable").handler({"observables": [obs.obs_id]})

    assert service.enrich_calls == [(obs,)]  # the same object, not a re-parse
    assert len(result["results"]) == 1
    entry = result["results"][0]
    assert entry["observable"]["id"] == obs.obs_id
    assert entry["signals"][0]["source"] == "ThreatFox"
    assert entry["signals"][0]["label"] == VerdictLabel.MALICIOUS
    assert "not_checked" not in entry


async def test_enrichment_also_accepts_an_indicator_the_message_never_carried():
    """A loop may reason its way to an indicator that was not in the message.
    Refusing that would make the agent strictly less capable than the shortcut
    path it wraps — and the parse goes through the SAME extractor, so a defanged
    form is handled without a second opinion about what a domain is."""
    service = FakeEnrichmentService(EnrichmentOutcome(items=()))
    registry = _build(enrichment=service, observables=())

    await registry.get("enrich_observable").handler({"observables": ["evil[.]example[.]com"]})

    assert len(service.enrich_calls) == 1
    (called,) = service.enrich_calls
    assert len(called) == 1
    assert called[0].value == "evil.example.com"  # refanged by the shared extractor
    assert called[0].defanged is True


async def test_an_indicator_that_does_not_parse_is_reported_not_dropped():
    """A model that mangled a hash must SEE that it did. Silently dropping the
    argument returns a confident answer about a different question."""
    service = FakeEnrichmentService(EnrichmentOutcome(items=()))
    registry = _build(enrichment=service, observables=())

    result = await registry.get("enrich_observable").handler(
        {"observables": ["8.8.8.8", "not an indicator at all"]}
    )

    assert result["unresolved"] == ["not an indicator at all"]
    assert len(service.enrich_calls[0]) == 1  # the good one still went through


async def test_one_argument_holding_three_indicators_checks_all_three():
    """S25 review. The original kept `parsed[0]` per argument item, so an
    analyst's "check these three" came back answered about ONE — with
    `unresolved` empty and nothing in the payload saying two were never looked
    up. That is not-checked rendering as no-signals, the exact collapse this
    module exists to prevent, and the enrichment service never even saw them.

    Arithmetic control: the shared extractor finds three in this string, so a
    result of one cannot be blamed on the input.
    """
    packed = "185.220.101.5 and 45.83.64.1 and 91.219.236.166"
    assert len(_obs(packed)) == 3, "control broken: the input does not hold three"
    service = FakeEnrichmentService(EnrichmentOutcome(items=()))
    registry = _build(enrichment=service, observables=())

    result = await registry.get("enrich_observable").handler({"observables": [packed]})

    assert len(service.enrich_calls[0]) == 3, "the service was asked about a subset"
    assert {o.value for o in service.enrich_calls[0]} == {
        "185.220.101.5",
        "45.83.64.1",
        "91.219.236.166",
    }
    assert "unresolved" not in result


async def test_a_bare_comma_separated_string_is_not_answered_about_its_first_indicator():
    """The shape `_as_list` explicitly exists to accommodate is the shape most
    likely to carry several indicators: a bare string arrives as ONE item.
    Measured on the live endpoint at S25, Scout sends separate array items — so
    this is latent there, and the platform's premise is whatever endpoint the
    customer brings (the same argument that ratified the S24 carry fix)."""
    csv = "8.8.8.8, 1.1.1.1, 9.9.9.9"
    assert len(_obs(csv)) == 3, "control broken: the input does not hold three"
    service = FakeEnrichmentService(EnrichmentOutcome(items=()))
    registry = _build(enrichment=service, observables=())

    # Not a list — the bare-string branch, exactly as a model would send it.
    result = await registry.get("enrich_observable").handler({"observables": csv})

    assert len(service.enrich_calls[0]) == 3
    assert "unresolved" not in result


async def test_more_indicators_than_the_boundary_carries_says_how_many_it_dropped():
    """An answer over a truncated set must say it was truncated (the S21
    lesson). Over-cap indicators are a different truth from over-cap argument
    ITEMS, so they get their own key rather than being folded into `omitted`."""
    packed = " ".join(f"10.0.0.{i}" for i in range(1, MAX_TOOL_ARG_ITEMS + 6))
    assert len(_obs(packed)) == MAX_TOOL_ARG_ITEMS + 5, "control broken"
    service = _LooksUpEverything()
    registry = _build(enrichment=service, observables=())

    result = await registry.get("enrich_observable").handler({"observables": [packed]})

    # The boundary carries MAX_TOOL_ARG_ITEMS; of those, the turn's budget is
    # looked up and the rest are NAMED as not checked (review of 1b86070 moved
    # that split from the service into the tool — it used to hand all 25 over).
    assert len(result["results"]) == MAX_TOOL_ARG_ITEMS
    assert len(service.enrich_calls[0]) == ENRICH_MAX_OBSERVABLES
    assert sum(1 for r in result["results"] if r.get("not_checked") == CAP_SKIP) == (
        MAX_TOOL_ARG_ITEMS - ENRICH_MAX_OBSERVABLES
    )
    assert result["omitted_observables"] == 5
    assert "omitted" not in result  # one argument item went in; none was dropped


@pytest.mark.parametrize("scalar", [5, 3.5, True])
async def test_a_bare_number_is_an_honest_miss_rather_than_a_crash(scalar):
    """S25 review. `list(5)` raises, and the loop turns any handler exception
    into `tool raised TypeError` — which tells the model nothing it can act on
    and costs it a step. A formatting choice deserves the same honest answer a
    mangled hash gets, with the value echoed back."""
    service = FakeEnrichmentService(EnrichmentOutcome(items=()))
    registry = _build(enrichment=service, observables=())

    result = await registry.get("enrich_observable").handler({"observables": scalar})

    assert result["error"] == "unparsable"
    assert result["unresolved"] == [str(scalar)]
    assert service.enrich_calls == []  # nothing was looked up


async def test_an_observable_that_was_not_checked_never_reads_as_no_signals():
    """The distinction the DEFERRED rail exists for. An observable with a
    `skip_reason` was never sent to a provider; reporting it as an empty signal
    list would have the model call it benign."""
    observables = _obs("check 10.0.0.1")
    service = FakeEnrichmentService(
        EnrichmentOutcome(
            items=(
                ObservableEnrichment(
                    observable=observables[0], signals=(), skip_reason="private address"
                ),
            )
        )
    )
    registry = _build(enrichment=service, observables=observables)

    entry = (await registry.get("enrich_observable").handler({"observables": ["10.0.0.1"]}))[
        "results"
    ][0]

    assert entry["not_checked"] == "private address"
    assert "signals" not in entry


async def test_sources_that_failed_are_named_separately_from_sources_that_knew_nothing():
    """"Nobody had anything" and "the sources that would have known did not
    answer" must not read alike to the model writing the verdict."""
    observables = _obs("check 185.220.101.5")
    service = FakeEnrichmentService(
        EnrichmentOutcome(
            items=(ObservableEnrichment(observable=observables[0], signals=()),),
            provider_failures={"OTX": "timeout"},
        )
    )
    registry = _build(enrichment=service, observables=observables)

    result = await registry.get("enrich_observable").handler({"observables": ["185.220.101.5"]})

    assert result["sources_unavailable"] == {"OTX": "timeout"}
    assert result["results"][0]["signals"] == []


async def test_enrichment_that_is_not_configured_says_so_and_calls_nothing():
    service = FakeEnrichmentService(EnrichmentOutcome(items=()), active=False)
    registry = _build(enrichment=service)

    result = await registry.get("enrich_observable").handler({"observables": ["8.8.8.8"]})

    assert result["error"] == "enrichment_inactive"
    assert service.enrich_calls == []


async def test_an_empty_enrichment_argument_is_an_error_not_a_lookup():
    service = FakeEnrichmentService(EnrichmentOutcome(items=()))
    registry = _build(enrichment=service)

    assert (await registry.get("enrich_observable").handler({}))["error"] == "no_observables"
    assert service.enrich_calls == []


# -- lookup_cve ---------------------------------------------------------------


async def test_cve_lookup_splits_what_the_kb_holds_from_what_it_does_not():
    """An id the KB has never heard of is an honest MISS. A model handed silence
    about it invents a CVE, which is the failure this split prevents."""
    kb = FakeKnowledgeService(hits=[_cve_hit()])
    registry = _build(kb=kb)

    result = await registry.get("lookup_cve").handler(
        {"cve_ids": ["CVE-2021-44228", "CVE-1999-0001"]}
    )

    assert list(result["found"]) == ["CVE-2021-44228"]
    assert result["not_found"] == ["CVE-1999-0001"]
    assert result["found"]["CVE-2021-44228"][0]["severity"] == "CRITICAL"
    assert result["found"]["CVE-2021-44228"][0]["cvss_score"] == 10.0


async def test_cve_lookup_sizes_its_fetch_the_way_the_shortcut_path_does():
    """The S6 review finding, re-used rather than re-derived: the default top_k
    rendered CVEs past it as false 'not in the knowledge base' misses. If this
    wrapper takes the default, the agent reports misses the shortcut path does
    not — the two answers disagree, which is the whole risk of a wrapper."""
    kb = FakeKnowledgeService(hits=[])
    registry = _build(kb=kb)
    ids = ["CVE-2021-44228", "CVE-2021-45046", "CVE-2022-22965"]

    await registry.get("lookup_cve").handler({"cve_ids": ids})

    assert kb.lookup_calls == [tuple(ids)]
    assert kb.lookup_topks == [max(8, 4 * len(ids))]


async def test_cve_ids_are_matched_case_insensitively():
    kb = FakeKnowledgeService(hits=[_cve_hit()])
    registry = _build(kb=kb)

    result = await registry.get("lookup_cve").handler({"cve_ids": ["cve-2021-44228"]})

    assert result["not_found"] == []
    assert list(result["found"]) == ["CVE-2021-44228"]


async def test_a_bare_string_where_an_array_was_specified_still_works():
    """Models send a scalar where an array is declared often enough that failing
    the turn for it would be a formatting choice deciding an investigation."""
    kb = FakeKnowledgeService(hits=[_cve_hit()])
    registry = _build(kb=kb)

    result = await registry.get("lookup_cve").handler({"cve_ids": "CVE-2021-44228"})

    assert list(result["found"]) == ["CVE-2021-44228"]


async def test_a_truncated_cve_batch_says_it_was_truncated():
    """S21's lesson applied to an ANSWER rather than an assertion: a reply about
    a silently-truncated set is a wrong answer, not a partial one."""
    kb = FakeKnowledgeService(hits=[])
    registry = _build(kb=kb)
    ids = [f"CVE-2021-{i:05d}" for i in range(MAX_TOOL_ARG_ITEMS + 4)]

    result = await registry.get("lookup_cve").handler({"cve_ids": ids})

    assert result["omitted"] == 4
    assert len(kb.lookup_calls[0]) == MAX_TOOL_ARG_ITEMS


async def test_a_knowledge_base_that_is_down_is_not_a_knowledge_base_that_is_off():
    """Two of the three truths, and the public clause is what reaches the model —
    never the diagnostic one, which names internals."""
    down = FakeKnowledgeService(hits=[], unavailable=True)
    off = FakeKnowledgeService(hits=[], active=False)

    down_result = await _build(kb=down).get("lookup_cve").handler({"cve_ids": ["CVE-2021-44228"]})
    off_result = await _build(kb=off).get("lookup_cve").handler({"cve_ids": ["CVE-2021-44228"]})

    assert down_result["error"] == "kb_unavailable"
    assert down_result["detail"] == "it was unreachable"
    assert "SimulatedConnectError" not in down_result["detail"]
    assert off_result["error"] == "kb_inactive"
    assert off.lookup_calls == []


# -- search_knowledge ---------------------------------------------------------


async def test_knowledge_search_reuses_the_definition_path():
    """`search_definition` owns the curated doc-type filter and fuses over
    documents rather than chunks (TD-026). Reusing it is what keeps the agent's
    answer and the shortcut's answer the same answer."""
    kb = FakeKnowledgeService(hits=[_concept_hit()])
    registry = _build(kb=kb)

    result = await registry.get("search_knowledge").handler({"query": "what is lateral movement"})

    assert kb.search_calls == ["what is lateral movement"]
    from auspex.kb.service import DEFINITION_DOC_TYPES

    assert kb.search_doc_types == [DEFINITION_DOC_TYPES]
    assert result["results"][0]["title"] == "Lateral movement"


async def test_a_connected_but_ignorant_knowledge_base_is_a_miss_not_a_deferral():
    """The third truth. Static 'not connected yet' copy would be a lie about a
    KB that is connected and simply has no entry."""
    kb = FakeKnowledgeService(hits=[])
    registry = _build(kb=kb)

    result = await registry.get("search_knowledge").handler({"query": "quokka exfiltration"})

    assert result["results"] == []
    assert result["miss"]
    assert "error" not in result


async def test_an_empty_query_never_reaches_the_knowledge_base():
    kb = FakeKnowledgeService(hits=[])
    registry = _build(kb=kb)

    assert (await registry.get("search_knowledge").handler({"query": "   "}))["error"] == "no_query"
    assert kb.search_calls == []


# -- payload honesty ----------------------------------------------------------


async def test_a_field_the_record_does_not_carry_is_absent_rather_than_null():
    """A `severity: ""` reads to a model as 'measured, and it is nothing' rather
    than 'not known', and that difference ends up in the analyst's answer."""
    kb = FakeKnowledgeService(hits=[_concept_hit()])
    registry = _build(kb=kb)

    hit = (await registry.get("search_knowledge").handler({"query": "lateral movement"}))[
        "results"
    ][0]

    assert "severity" not in hit
    assert "cvss_score" not in hit
    assert "epss_score" not in hit
    assert "kev" not in hit


async def test_a_clipped_chunk_says_it_was_clipped():
    """A model shown a clipped page must be able to tell — otherwise it reasons
    from a sentence that stops mid-thought as though it were the whole record."""
    kb = FakeKnowledgeService(hits=[_cve_hit(text="x" * (SNIPPET_CHARS + 50))])
    registry = _build(kb=kb)

    found = (await registry.get("lookup_cve").handler({"cve_ids": ["CVE-2021-44228"]}))["found"]
    chunk = found["CVE-2021-44228"][0]

    assert chunk["text_truncated"] is True
    assert len(chunk["text"]) == SNIPPET_CHARS


async def test_an_exploited_vulnerability_carries_its_kev_flag():
    """KEV is the field that changes what an analyst does next, so it travels
    with the record rather than being left for the model to infer from prose."""
    kb = FakeKnowledgeService(
        hits=[
            _cve_hit(
                kev_listed=True, kev_date_added="2021-12-10", kev_ransomware=True, epss_score=0.97
            )
        ]
    )
    registry = _build(kb=kb)

    found = (await registry.get("lookup_cve").handler({"cve_ids": ["CVE-2021-44228"]}))["found"]
    chunk = found["CVE-2021-44228"][0]

    assert chunk["kev"] == {
        "listed": True,
        "date_added": "2021-12-10",
        "known_ransomware_use": True,
    }
    assert chunk["epss_score"] == 0.97


async def test_no_tool_result_names_the_engine_or_the_provider_behind_it():
    """Brand rule (CLAUDE.md, D-002), and it applies to tool results because the
    model writes its answer FROM them — a leaked engine name arrives in the
    analyst's pane one hop later."""
    kb = FakeKnowledgeService(hits=[_cve_hit()])
    registry = _build(kb=kb)
    blob = repr(
        [
            await registry.get("lookup_cve").handler({"cve_ids": ["CVE-2021-44228"]}),
            await registry.get("search_knowledge").handler({"query": "lateral movement"}),
            [s for s in registry.specs()],
        ]
    ).lower()

    for forbidden in ("llama", "scout", "qwen", "ollama", "northflank", "openai", "gpt"):
        assert forbidden not in blob


# -- the turn's enrichment budget (review of 1b86070) -------------------------


class _LooksUpEverything(FakeEnrichmentService):
    """Answers every observable it is handed as looked up — so the count of
    observables it was handed IS the count of third-party lookups."""

    def __init__(self):
        super().__init__(EnrichmentOutcome(items=()))

    async def enrich(self, observables):
        self.enrich_calls.append(observables)
        return EnrichmentOutcome(
            items=tuple(ObservableEnrichment(observable=o, sources_answered=1) for o in observables)
        )


def _ips(start: int, n: int) -> list[str]:
    return [f"203.0.113.{i}" for i in range(start, start + n)]


async def test_a_turn_enriches_no_more_indicators_than_the_shortcut_path_would():
    """Review of 1b86070, Medium. The enrichment cap applied PER CALL, and a loop
    makes up to nine calls — re-asking for what came back over the cap is the
    natural thing for a model to do. One deep turn could drive hundreds of
    lookups against provider keys and breakers every tenant shares, while TD-018
    counted nine inference calls. The registry is built per turn, so the turn's
    budget is the shortcut path's per-turn bound: ENRICH_MAX_OBSERVABLES."""
    service = _LooksUpEverything()
    registry = _build(enrichment=service)
    enrich = registry.get("enrich_observable").handler

    for start in (1, 5, 9):
        last = await enrich({"observables": _ips(start, 4)})

    sent = [o for call in service.enrich_calls for o in call]
    assert len(sent) == ENRICH_MAX_OBSERVABLES
    # What the budget refused is NAMED as not checked, never as no signals.
    refused = [r for r in last["results"] if "not_checked" in r]
    assert [r["not_checked"] for r in refused] == [CAP_SKIP] * 4
    assert [r["observable"]["value"] for r in refused] == _ips(9, 4)


async def test_the_budget_belongs_to_one_turn():
    """A fresh registry is a fresh turn — the bound is per turn, not per process."""
    first = _LooksUpEverything()
    await _build(enrichment=first).get("enrich_observable").handler(
        {"observables": _ips(1, ENRICH_MAX_OBSERVABLES)}
    )
    second = _LooksUpEverything()
    await _build(enrichment=second).get("enrich_observable").handler(
        {"observables": _ips(1, 4)}
    )

    assert len(second.enrich_calls[0]) == 4
