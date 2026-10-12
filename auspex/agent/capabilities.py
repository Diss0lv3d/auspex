"""The platform's existing capabilities, exposed as agent READ tools (S24).

Until this module, `ToolRegistry` had no caller: `grep ToolRegistry()` across
`auspex/` found nothing outside the class, so an agent loop wired into a route
would have had **zero tools** and nothing to do. Enrichment, CVE lookup and KB
retrieval have existed since S5/S6 — but only as shortcut code paths the route
calls directly, which the model can neither reach nor choose.

**This wraps that code; it does not re-implement it.** Every handler calls the
same `EnrichmentService.enrich`, `KnowledgeService.lookup_ids` and
`KnowledgeService.search_definition` the shortcut path calls, and resolves
observables through the same `auspex.classify.observables.extract`. A second
opinion about what an IP is, or about which doc types can answer a definition,
is exactly the drift D-006 and D-025 exist to prevent — and here it would be
worse than drift, because the two answers would disagree in front of the analyst
within one session.

**All three are READ (D-014).** They fetch and they synthesise; nothing here
touches a provider that changes anything. One write is the platform's own
bookkeeping, not an action: since D-049 an enrichment is recorded (observable
and verdict) exactly as the 92/8 IOC check records one, and only for
indicators D-039 let through. The permission
gate auto-executes READ, so a level is a claim about consequences — these have
none beyond outbound lookups the shortcut path already makes.

**What a handler returns is DATA, not prose.** The shortcut path's renderers
(`render_ioc_answer`, `render_cve_answer`, `render_definition_answer`) exist to
speak to an analyst; a tool result is read by the model, which then writes its
own answer. Returning rendered markdown would have the model paraphrasing our
copy back at the analyst, and would put our own configuration-shaped prose into
the turn for the output rail to trip over. Structured fields also give D-031 the
shape it asked for: tool results are left unindexed as data and scanned on their
own channel.

**Honest failure, never a fabricated one.** A service that is inactive or down
returns `{"error": ..., "detail": ...}` and the loop feeds that back to the
model, which is the DEFERRED-rail discipline the shortcut copy already follows:
"not wired up" and "wired up but unavailable" and "connected and it knows
nothing" are three different truths and must stay three different answers.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable

from auspex.agent.registry import ToolLevel, ToolRegistry
from auspex.classify.observables import Observable, extract
from auspex.enrich import EnrichmentOutcome, EnrichmentService
from auspex.enrich.service import CAP_SKIP, ENRICH_MAX_OBSERVABLES
from auspex.kb import MAX_IDS_PER_LOOKUP, KBUnavailable, KnowledgeService

logger = logging.getLogger("auspex.agent.capabilities")

# An INPUT boundary, not a capability cap — the distinction matters and the two
# were nearly conflated here. How many indicators are worth enriching is
# `ENRICH_MAX_OBSERVABLES`, and the enrichment service already applies it AND
# reports each over-cap observable as a `CAP_SKIP` skip reason; how many CVE ids
# one lookup may carry is `MAX_IDS_PER_LOOKUP`, sized to OpenSearch's
# bool-clause limit. Re-declaring either here would be a second opinion about a
# calibrated number — the drift this module exists to avoid.
#
# This bounds what ONE tool argument may turn into: both the strings we will
# attempt to parse, and the observables those strings yield. One boundary, one
# concern — a model emitting a thousand-element array, or twenty-five strings
# each packed with indicators, costs a bounded number of regex passes and hands
# the enrichment service a bounded list either way.
MAX_TOOL_ARG_ITEMS = 25

# Enough of a chunk for the model to reason from, short enough that nine tool
# results do not crowd out the conversation. Truncation is NAMED in the payload
# rather than silent — a model shown a clipped page must be able to tell.
SNIPPET_CHARS = 600

# TD-043 (D-046): how many times one turn may search the knowledge base. A
# free-text search can always be reworded, and on a topic the KB covers thinly
# every rewording still returns a full page of the nearest documents — never a
# miss that would say "stop". Measured at S28 on S27's prompts
# (docs/probes/2026-10-11-s28-td043-search-budget.md): 3 of 6 threat-intel turns
# searched 8 times and hit the step cap; with 3, the same six turns made 23
# calls instead of 37 and every answer still met its contract. The price is
# stated there: on "LockBit initial access" searches 4-5 had found the T1566
# Phishing page, which 3 never reach (the Initial Access tactic page, found
# first every time, names the same vectors). A budget of 5 did not reach it
# either. The id lookups are bounded by their inputs and carry no budget. Code,
# not config (D-026).
SEARCH_KNOWLEDGE_MAX_CALLS = 3

# D-039: why an indicator the model asked about was not looked up. Phrased as a
# reason the model can act on (ask the analyst), and never as "no signals".
NOT_SUPPLIED_SKIP = (
    "not looked up — it does not appear in the analyst's messages or in anything "
    "a tool returned this turn, and the platform only sends third parties "
    "indicators someone other than the model supplied; ask the analyst to paste it"
)


def _snippet(text: str) -> tuple[str, bool]:
    clipped = text[:SNIPPET_CHARS]
    return (clipped, len(text) > SNIPPET_CHARS)


def _observable_payload(o: Observable) -> dict:
    return {"id": o.obs_id, "type": str(o.type), "value": o.value, "defanged": o.defanged}


def _hit_payload(hit) -> dict:
    text, truncated = _snippet(hit.text)
    payload = {
        "title": hit.title,
        "doc_type": hit.doc_type,
        "source": hit.source,
        "source_ref": hit.source_ref,
        "ids": list(hit.ids),
        "text": text,
        "text_truncated": truncated,
    }
    # Only state fields that carry a value. A `severity: ""` or `cvss: null` in
    # a tool result reads to a model as "measured, and it is nothing" rather
    # than "not known", and that difference ends up in the analyst's answer.
    if hit.severity:
        payload["severity"] = hit.severity
    if hit.cvss_score is not None:
        payload["cvss_score"] = hit.cvss_score
    if hit.epss_score is not None:
        payload["epss_score"] = hit.epss_score
    if hit.kev_listed:
        payload["kev"] = {
            "listed": True,
            "date_added": hit.kev_date_added,
            "known_ransomware_use": hit.kev_ransomware,
        }
    return payload


def _resolve(
    values: list[str], known: dict[str, Observable], *, cap: int = MAX_TOOL_ARG_ITEMS
) -> tuple[list[Observable], list[str], int]:
    """Turn model-supplied strings into observables, by id or by value.

    Both forms are accepted for one measured reason. The S2 harness found that
    every model tested mangled long hashes in arguments, which is why the
    registry's authoring convention is short ids — so the turn's already-parsed
    observables are addressable as `ipv4-9c463859`. But a loop may reason its
    way to an indicator that was never in the message, and refusing that would
    make the agent less capable than the shortcut path it wraps. So: try the id
    first, then parse the string with the SAME extractor the route uses.

    Unresolvable strings are returned separately and reported, never dropped —
    a model that mangled a hash must see that it did, not receive a confident
    answer about something it did not ask for.

    **Every observable a string yields is kept, not just the first (S25 review).**
    The original took `parsed[0]`, so one argument item holding three indicators
    was answered about ONE, with `unresolved` empty and nothing in the payload
    saying so — the analyst's "check these three" came back reading as complete
    while two were never looked up. That is the precise failure this module's own
    docstring calls the whole of the DEFERRED rail: not-checked must never render
    as no-signals. It was reachable through the exact shape `_as_list` exists to
    accommodate — a bare comma-separated string arrives as ONE item.

    Over-cap observables are counted and returned so the caller can NAME them
    (the S21 lesson), rather than quietly answering about a subset.
    """
    resolved: list[Observable] = []
    unresolved: list[str] = []
    seen: set[str] = set()
    over_cap = 0
    for raw in values:
        candidate = (raw or "").strip()
        if not candidate:
            continue
        hit = known.get(candidate)
        parsed = [hit] if hit is not None else list(extract(candidate).observables)
        if not parsed:
            unresolved.append(candidate)
            continue
        for obs in parsed:
            if obs.obs_id in seen:
                continue
            if len(resolved) >= cap:
                over_cap += 1
                continue
            seen.add(obs.obs_id)
            resolved.append(obs)
    return resolved, unresolved, over_cap


def _as_list(raw, *, cap: int) -> tuple[list[str], int]:
    """Coerce a tool argument to a capped list of strings.

    Models send a bare string where an array is specified often enough that
    treating it as a contract violation would fail turns for a formatting
    choice. Returns the omitted count so the payload can NAME the cap rather
    than silently answering about a subset (the S21 lesson: an assertion — or an
    answer — over a truncated set must say it was truncated).

    A bare NUMBER or boolean is the same class of formatting choice and is
    treated the same way (S25 review). `list(5)` raises, and the loop's blanket
    handler turns that into `tool raised TypeError` — which tells the model
    nothing it can act on and burns a step. Coerced here instead, it flows to
    the honest "none of these parsed as a supported indicator", echoing the
    value back so the model can see what it sent.
    """
    if raw is None:
        return [], 0
    if isinstance(raw, str):
        items = [raw]
    else:
        try:
            items = list(raw)
        except TypeError:
            items = [raw]
    flat = [str(i).strip() for i in items if str(i).strip()]
    deduped = list(dict.fromkeys(flat))
    return deduped[:cap], max(0, len(deduped) - cap)


def build_capability_registry(
    *,
    enrichment: EnrichmentService,
    kb: KnowledgeService,
    observables: tuple[Observable, ...] = (),
    supplied: tuple[Observable, ...] = (),
    record: Callable[[EnrichmentOutcome], Awaitable[int]] | None = None,
) -> ToolRegistry:
    """A registry of the platform's READ capabilities, bound to this turn.

    Built per turn rather than per process because two of the three need the
    turn's own context: `observables` makes the message's already-parsed
    indicators addressable by their short ids. The services themselves are the
    app-wide singletons — the same objects the shortcut path uses, so breakers,
    caps and provider health are shared rather than duplicated.

    **D-039: only indicators someone other than the model supplied reach a
    provider.** `observables` (this message) and `supplied` (the analyst's
    earlier messages in the session — USER turns only, never the model's own
    answers) seed the set; what the knowledge base returns this turn joins it.
    An indicator the model composed itself is named as not checked.

    **D-049: what `enrich_observable` looked up is recorded** through `record`
    — the route passes the same `persist_enrichment` the 92/8 IOC check calls,
    so the observable and its verdict exist for a later proposal to target and
    for Living Verdicts to watch. Only what D-039 let through was looked up, so
    only that is recorded: the model cannot make the platform record an
    indicator it composed. `None` (probes, tests) records nothing and says
    nothing about recording.
    """
    known = {o.obs_id: o for o in observables}
    known.update({o.value: o for o in observables})
    registry = ToolRegistry()
    allowed: set[str] = {o.obs_id for o in (*observables, *supplied)}

    def _learn(payloads: list[dict]) -> None:
        """Indicators in knowledge-base records returned this turn were supplied
        by a source, not composed by the model (D-039). Only HIT payloads: a
        tool's echo of what it was asked must never launder a request into a
        supply."""
        for payload in payloads:
            for value in payload.values():
                if isinstance(value, str):
                    allowed.update(o.obs_id for o in extract(value).observables)
    # The TURN's enrichment budget (review of 1b86070). The service caps each
    # call at ENRICH_MAX_OBSERVABLES, but a loop makes up to nine calls and a
    # model re-asks for what came back over the cap — so per call, one deep
    # turn could drive hundreds of lookups against provider keys and breakers
    # every tenant shares. Per turn is the bound the shortcut path has always
    # had (CAP_SKIP says "this turn's"), and the registry is built per turn.
    enrich_budget = ENRICH_MAX_OBSERVABLES

    async def enrich_observable(args: dict) -> dict:
        nonlocal enrich_budget
        requested, omitted = _as_list(
            args.get("observables") or args.get("observable"), cap=MAX_TOOL_ARG_ITEMS
        )
        if not requested:
            return {"error": "no_observables", "detail": "no observable was supplied"}
        if not enrichment.active:
            return {
                "error": "enrichment_inactive",
                "detail": "no enrichment providers are configured in this deployment",
            }
        resolved, unresolved, over_cap = _resolve(requested, known)
        if not resolved:
            return {
                "error": "unparsable",
                "detail": "none of these parsed as a supported indicator",
                "unresolved": unresolved,
            }
        not_supplied = [o for o in resolved if o.obs_id not in allowed]
        resolved = [o for o in resolved if o.obs_id in allowed]
        within, beyond = resolved[:enrich_budget], resolved[enrich_budget:]
        outcome = await enrichment.enrich(tuple(within)) if within else None
        items = []
        for item in outcome.items if outcome else ():
            entry = {
                "observable": _observable_payload(item.observable),
                "sources_answered": item.sources_answered,
            }
            if item.skip_reason is not None:
                # Not "clean" — not looked up. The distinction is the whole of
                # the DEFERRED rail, and a model given "no signals" would call
                # it benign.
                entry["not_checked"] = item.skip_reason
            else:
                entry["signals"] = [
                    {
                        "source": s.provider,
                        "label": str(s.label),
                        "confidence": s.confidence,
                        "summary": s.summary,
                    }
                    for s in item.signals
                ]
            items.append(entry)
        if outcome:
            enrich_budget -= len(outcome.enriched)
        for obs in beyond:
            # Not looked up because the turn's budget is spent — named exactly
            # as the service names its own cap, never as "no signals".
            items.append({"observable": _observable_payload(obs), "sources_answered": 0,
                          "not_checked": CAP_SKIP})
        for obs in not_supplied:
            items.append({"observable": _observable_payload(obs), "sources_answered": 0,
                          "not_checked": NOT_SUPPLIED_SKIP})
        result: dict = {"results": items}
        if outcome and outcome.provider_failures:
            # Named, because "nobody had anything" and "the sources that would
            # have known did not answer" must not read alike.
            result["sources_unavailable"] = outcome.provider_failures
        if unresolved:
            result["unresolved"] = unresolved
        if omitted:
            result["omitted"] = omitted
        if over_cap:
            # A different truth from `omitted`, which counts argument items
            # dropped before parsing. This counts indicators the arguments
            # actually yielded and we would not carry — kept separate, because
            # "you sent too many strings" and "your strings held more
            # indicators than we will check" are not the same sentence.
            result["omitted_observables"] = over_cap
        if record is not None and outcome is not None and outcome.enriched:
            # Said either way: a model that is not told cannot know whether "I
            # have recorded the verdict" is true, and a storage hiccup must not
            # cost the analyst a computed answer (the shortcut path's S5 rule).
            try:
                await record(outcome)
                result["recorded"] = True
            except Exception:
                logger.exception("agent enrichment: recording failed; results returned unrecorded")
                result["recorded"] = False
        return result

    async def lookup_cve(args: dict) -> dict:
        requested, omitted = _as_list(
            args.get("cve_ids") or args.get("cve_id"), cap=MAX_IDS_PER_LOOKUP
        )
        if not requested:
            return {"error": "no_cve_ids", "detail": "no CVE id was supplied"}
        if not kb.active:
            return {
                "error": "kb_inactive",
                "detail": "the knowledge base is not connected in this deployment",
            }
        ids = [c.upper() for c in requested]
        try:
            # Same call and the same fetch sizing as the shortcut path: the
            # default top_k renders CVEs past it as false "not in the knowledge
            # base" misses (S6 review).
            hits = await kb.lookup_ids(tuple(ids), top_k=max(8, 4 * len(ids)))
        except KBUnavailable as err:
            return {"error": "kb_unavailable", "detail": err.public}
        by_id: dict[str, list[dict]] = {cve: [] for cve in ids}
        for hit in hits:
            for cve in ids:
                if cve in hit.ids:
                    by_id[cve].append(_hit_payload(hit))
        for chunks in by_id.values():
            _learn(chunks)
        result: dict = {
            "found": {cve: chunks for cve, chunks in by_id.items() if chunks},
            # An id the KB has never heard of is an honest miss, and saying so
            # is the point — a model that gets silence invents a CVE.
            "not_found": [cve for cve, chunks in by_id.items() if not chunks],
        }
        if omitted:
            result["omitted"] = omitted
        return result

    async def search_knowledge(args: dict) -> dict:
        query = str(args.get("query") or "").strip()
        if not query:
            return {"error": "no_query", "detail": "no query was supplied"}
        if not kb.active:
            return {
                "error": "kb_inactive",
                "detail": "the knowledge base is not connected in this deployment",
            }
        try:
            # `search_definition` owns the curated-doc-type filter and fuses
            # over documents rather than chunks (TD-026). Reusing it is what
            # keeps the agent's answer and the shortcut's answer the same
            # answer.
            hits = await kb.search_definition(query)
        except KBUnavailable as err:
            return {"error": "kb_unavailable", "detail": err.public}
        if not hits:
            # Connected and ignorant is a MISS, not "deferred" — the third of
            # the three truths.
            return {"results": [], "miss": "the knowledge base has no entry for that"}
        payloads = [_hit_payload(h) for h in hits]
        _learn(payloads)
        return {"results": payloads}

    registry.add(
        name="enrich_observable",
        description=(
            "Look up reputation and threat-intelligence signals for one or more "
            "indicators (IP, domain, URL, file hash). Accepts either the short id "
            "of an indicator already parsed from the conversation (e.g. "
            "'ipv4-9c463859') or the indicator itself. Returns each source's "
            "verdict and evidence; an indicator that was not checked says so "
            "rather than reporting no signals."
        ),
        parameters={
            "observables": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "Indicator ids or values. Prefer the short id when the "
                    "indicator came from the conversation."
                ),
            }
        },
        required=["observables"],
        level=ToolLevel.READ,
        handler=enrich_observable,
    )
    registry.add(
        name="lookup_cve",
        description=(
            "Retrieve knowledge-base records for specific CVE ids, including "
            "severity, CVSS, EPSS probability and whether the vulnerability is "
            "known to be exploited (KEV). Ids the knowledge base does not hold "
            "are returned as not_found rather than guessed at."
        ),
        parameters={
            "cve_ids": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    f"Up to {MAX_IDS_PER_LOOKUP} CVE ids, e.g. ['CVE-2021-44228']."
                ),
            }
        },
        required=["cve_ids"],
        level=ToolLevel.READ,
        handler=lookup_cve,
    )
    registry.add(
        name="search_knowledge",
        description=(
            "Search the curated security knowledge base for background on a "
            "concept, attacker technique or tactic — what something is and how it "
            "shows up. Not for looking up a specific CVE id; use lookup_cve for "
            "that. Returns an explicit miss when the knowledge base has no entry."
        ),
        parameters={
            "query": {
                "type": "string",
                "description": "What to look up, e.g. 'lateral movement' or 'Kerberoasting'.",
            }
        },
        required=["query"],
        level=ToolLevel.READ,
        handler=search_knowledge,
        max_calls_per_turn=SEARCH_KNOWLEDGE_MAX_CALLS,
    )
    return registry


__all__ = [
    "MAX_TOOL_ARG_ITEMS",
    "NOT_SUPPLIED_SKIP",
    "SNIPPET_CHARS",
    "build_capability_registry",
]
