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
mutates tenant state or touches a provider that changes anything. The permission
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

from auspex.agent.registry import ToolLevel, ToolRegistry
from auspex.classify.observables import Observable, extract
from auspex.enrich import EnrichmentService
from auspex.kb import MAX_IDS_PER_LOOKUP, KBUnavailable, KnowledgeService

logger = logging.getLogger("auspex.agent.capabilities")

# An INPUT boundary, not a capability cap — the distinction matters and the two
# were nearly conflated here. How many indicators are worth enriching is
# `ENRICH_MAX_OBSERVABLES`, and the enrichment service already applies it AND
# reports each over-cap observable as a `CAP_SKIP` skip reason; how many CVE ids
# one lookup may carry is `MAX_IDS_PER_LOOKUP`, sized to OpenSearch's
# bool-clause limit. Re-declaring either here would be a second opinion about a
# calibrated number — the drift this module exists to avoid. This bounds only
# how many strings we will attempt to PARSE out of one tool argument, so a model
# emitting a thousand-element array costs a thousand regex passes and no more.
MAX_TOOL_ARG_ITEMS = 25

# Enough of a chunk for the model to reason from, short enough that nine tool
# results do not crowd out the conversation. Truncation is NAMED in the payload
# rather than silent — a model shown a clipped page must be able to tell.
SNIPPET_CHARS = 600


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


def _resolve(values: list[str], known: dict[str, Observable]) -> tuple[list[Observable], list[str]]:
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
    """
    resolved: list[Observable] = []
    unresolved: list[str] = []
    seen: set[str] = set()
    for raw in values:
        candidate = (raw or "").strip()
        if not candidate:
            continue
        found = known.get(candidate)
        if found is None:
            parsed = extract(candidate).observables
            found = parsed[0] if parsed else None
        if found is None:
            unresolved.append(candidate)
        elif found.obs_id not in seen:
            seen.add(found.obs_id)
            resolved.append(found)
    return resolved, unresolved


def _as_list(raw, *, cap: int) -> tuple[list[str], int]:
    """Coerce a tool argument to a capped list of strings.

    Models send a bare string where an array is specified often enough that
    treating it as a contract violation would fail turns for a formatting
    choice. Returns the omitted count so the payload can NAME the cap rather
    than silently answering about a subset (the S21 lesson: an assertion — or an
    answer — over a truncated set must say it was truncated).
    """
    if raw is None:
        return [], 0
    items = [raw] if isinstance(raw, str) else list(raw)
    flat = [str(i).strip() for i in items if str(i).strip()]
    deduped = list(dict.fromkeys(flat))
    return deduped[:cap], max(0, len(deduped) - cap)


def build_capability_registry(
    *,
    enrichment: EnrichmentService,
    kb: KnowledgeService,
    observables: tuple[Observable, ...] = (),
) -> ToolRegistry:
    """A registry of the platform's READ capabilities, bound to this turn.

    Built per turn rather than per process because two of the three need the
    turn's own context: `observables` makes the message's already-parsed
    indicators addressable by their short ids. The services themselves are the
    app-wide singletons — the same objects the shortcut path uses, so breakers,
    caps and provider health are shared rather than duplicated.
    """
    known = {o.obs_id: o for o in observables}
    known.update({o.value: o for o in observables})
    registry = ToolRegistry()

    async def enrich_observable(args: dict) -> dict:
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
        resolved, unresolved = _resolve(requested, known)
        if not resolved:
            return {
                "error": "unparsable",
                "detail": "none of these parsed as a supported indicator",
                "unresolved": unresolved,
            }
        outcome = await enrichment.enrich(tuple(resolved))
        items = []
        for item in outcome.items:
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
        result: dict = {"results": items}
        if outcome.provider_failures:
            # Named, because "nobody had anything" and "the sources that would
            # have known did not answer" must not read alike.
            result["sources_unavailable"] = outcome.provider_failures
        if unresolved:
            result["unresolved"] = unresolved
        if omitted:
            result["omitted"] = omitted
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
        return {"results": [_hit_payload(h) for h in hits]}

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
    )
    return registry


__all__ = [
    "MAX_TOOL_ARG_ITEMS",
    "SNIPPET_CHARS",
    "build_capability_registry",
]
