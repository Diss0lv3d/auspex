"""ACH investigations — S12, the zero-LLM REST surface (D-019).

An investigation is a durable competing-hypotheses analysis of ONE pasted
subject (alert or email). Everything on this surface is deterministic code:
the subject is parsed by the S10/S11 parsers, hypotheses seed from the closed
catalog, evidence derives from the typed shapes, the matrix and the next-lookup
plan are recomputed on every read (the store persists inputs, never
conclusions). No model is called anywhere on these routes — a model-rendered
hypothesis summary through a contract is S13+ work and will follow the
S10/S11 directive+pin pattern when it comes.

POST /api/investigations                 — create from a pasted alert/email
GET  /api/investigations/{id}            — current matrix + lookup plan
POST /api/investigations/{id}/lookups    — EXECUTE the top recommended lookup
                                           (S5 enrichment fan-out), fold the
                                           result in as evidence, re-assess
"""

from __future__ import annotations

import logging
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from auspex.ach import (
    AchAssessment,
    LookupPlan,
    SubjectKind,
    candidate_lookups,
    enrichment_coverage,
    evidence_from_alert,
    evidence_from_email,
    evidence_from_enrichment,
    rank_lookups,
    score_matrix,
    seed_hypotheses,
)
from auspex.ach.render import (
    SUMMARY_CONTRACT,
    check_citations,
    citation_labels,
    investigation_directive,
)
from auspex.ach.store import (
    InvestigationRecord,
    add_evidence,
    create_investigation,
    load_investigation,
)
from auspex.alerts import normalize
from auspex.auth import AuthContext, resolve_user
from auspex.classify.classifier import _is_alert_paste, _is_email_paste
from auspex.classify.observables import Observable, ObservableType, observable_id
from auspex.enrich import EnrichmentService, persist_enrichment
from auspex.limits import Meter, UsageLimiter
from auspex.llm.client import LLMClient, LLMError
from auspex.phishing import decide_verdict, parse_email
from auspex.phishing.victims import filter_victim_iocs

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/investigations", tags=["investigations"])

Auth = Annotated[AuthContext, Depends(resolve_user)]


class CreateInvestigationBody(BaseModel):
    # Same ceiling as ChatBody: the parsers run synchronously over this text.
    message: str = Field(min_length=1, max_length=32_000)
    session_id: UUID | None = None


class RunLookupBody(BaseModel):
    # Absent ⇒ run the engine's TOP-ranked lookup; present ⇒ run that specific
    # candidate (it must still BE a candidate — the engine's hygiene applies).
    obs_id: str | None = None


def _subject_snapshot(kind: SubjectKind, message: str) -> tuple[dict, tuple, tuple]:
    """Parse the paste with the owning S10/S11 parser and reduce it to the
    jsonb snapshot the engine needs later: observables (for candidates),
    recipient domains (for the victim filter), and display fields."""
    if kind is SubjectKind.ALERT:
        env = normalize(message)
        subject = {
            "parsed": env.parsed,
            "fmt": env.fmt.value,
            "name": env.name,
            "severity": env.severity.value if env.severity else None,
            "iocs": _obs_json(env.iocs),
            "iocs_truncated": max(len(env.iocs) - _MAX_SNAPSHOT_IOCS, 0),
            "recipient_domains": [],
            "recipient_domains_truncated": 0,
        }
        return subject, env.iocs, evidence_from_alert(env)
    env = parse_email(message)
    verdict = decide_verdict(env)
    kept, _ = filter_victim_iocs(env)
    subject = {
        "parsed": env.parsed,
        "from_addr": env.from_addr,
        "from_domain": env.from_domain,
        "subject_line": env.subject,
        "iocs": _obs_json(kept),  # victim-filtered at parse time, once
        "iocs_truncated": max(len(kept) - _MAX_SNAPSHOT_IOCS, 0),
        # Same bound-and-name discipline as iocs: a paste listing hundreds of
        # recipients otherwise stores and echoes them all on every GET — the
        # one list the finding-8 caps missed (S13 review, finding 5). The
        # victim filter already ran on the FULL env at parse time; this cap
        # only bounds the display snapshot.
        "recipient_domains": list(env.recipient_domains[:_MAX_SNAPSHOT_RECIPIENTS]),
        "recipient_domains_truncated": max(
            len(env.recipient_domains) - _MAX_SNAPSHOT_RECIPIENTS, 0
        ),
    }
    return subject, kept, evidence_from_email(env, verdict)


# Snapshot bound (S12 verification finding 8): a 32 KB paste dense with
# routable IPs yields thousands of observables; unbounded, the subject jsonb
# and the candidate fan-out amplify every GET. Truncation is NAMED in the
# snapshot ("iocs_truncated"), never silent. 200 is far beyond any real
# alert/email — only the pathological paste loses tail observables.
_MAX_SNAPSHOT_IOCS = 200
_MAX_SNAPSHOT_RECIPIENTS = 50  # same discipline for the recipient list (S13 review 5)


def _obs_json(observables: tuple[Observable, ...]) -> list[dict]:
    return [
        {"type": o.type.value, "value": o.value, "obs_id": o.obs_id, "defanged": o.defanged}
        for o in observables[:_MAX_SNAPSHOT_IOCS]
    ]


def _obs_from_json(items: list[dict]) -> tuple[Observable, ...]:
    out = []
    for i in items:
        try:
            t = ObservableType(i["type"])
            value = i["value"]
        except (KeyError, ValueError):
            continue
        out.append(
            Observable(
                type=t,
                value=value,
                obs_id=i.get("obs_id") or observable_id(t, value),
                defanged=bool(i.get("defanged", False)),
            )
        )
    return tuple(out)


def _assess(record: InvestigationRecord) -> tuple[AchAssessment, LookupPlan]:
    """Recompute matrix + lookup plan from stored inputs (single source of
    truth is the math, never a stored score)."""
    assessment = score_matrix(record.hypotheses, record.evidence)
    observables = _obs_from_json(record.subject.get("iocs", []))
    covered = enrichment_coverage(tuple(e.obs_id for e in record.evidence))
    plan = rank_lookups(
        assessment, candidate_lookups(observables, covered_obs_ids=covered)
    )
    return assessment, plan


def _render(record: InvestigationRecord) -> dict:
    assessment, plan = _assess(record)
    # Citation identity (S13): stable per-row labels derived from the
    # ach_evidence uuid — what the cited summary and the citation guard
    # resolve against.
    cite_by_id = {v: k for k, v in citation_labels(record.evidence).items()}
    return {
        "investigation_id": str(record.investigation_id),
        "subject_kind": record.subject_kind.value,
        "subject": record.subject,
        "status": record.status,
        "ranking_claimed": assessment.ranking_claimed,
        "ranking_reason": assessment.reason,
        "notes": list(assessment.notes),
        "hypotheses": [
            {
                "key": s.hypothesis.key.value,
                "label": s.hypothesis.label,
                "status": s.status,
                "inconsistency": s.inconsistency,
                "support": s.support,
                # Named for what it is (matrix.py doctrine): a plausibility
                # weight derived from inconsistency, NOT a probability —
                # nothing on this surface estimates base rates. A bare
                # "weight" invited exactly that misreading (S13 review,
                # finding 6).
                "plausibility_weight": s.weight,
                "rejected_reason": s.rejected_reason,
            }
            for s in assessment.scores
        ],
        "evidence": [
            {
                "evidence_id": r.evidence.evidence_id,
                "cite": cite_by_id.get(r.evidence.evidence_id or ""),
                "kind": r.evidence.kind.value,
                "statement": r.evidence.statement,
                "credibility": r.evidence.credibility,
                "cells": {k.value: v for k, v in r.evidence.cells.items()},
                "source": r.evidence.source,
                "obs_id": r.evidence.obs_id,
                "diagnostic": r.diagnostic,
            }
            for r in assessment.readings
        ],
        "next_lookups": {
            "prior_entropy_bits": plan.prior_entropy_bits,
            "reason": plan.reason,
            "total_candidates": plan.total_candidates,
            "ranked": [
                {
                    "kind": r.candidate.kind.value,
                    "obs_id": r.candidate.observable.obs_id,
                    "type": r.candidate.observable.type.value,
                    "value": r.candidate.observable.value,
                    "reason": r.candidate.reason,
                    "expected_gain_bits": r.expected_gain_bits,
                    "outcomes": [
                        {
                            "outcome": t.outcome,
                            "probability": t.probability,
                            "posterior_entropy_bits": t.posterior_entropy_bits,
                        }
                        for t in r.outcome_terms
                    ],
                }
                for r in plan.ranked
            ],
        },
    }


async def _owned_session(request: Request, auth: Auth, session_id: UUID) -> None:
    row = await request.app.state.pool.fetchrow(
        "SELECT id FROM chat_sessions WHERE id = $1 AND workspace_id = $2 AND user_id = $3",
        session_id,
        auth.workspace_id,
        auth.user_id,
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Unknown session")


@router.post("", status_code=201)
async def create(request: Request, body: CreateInvestigationBody, auth: Auth) -> dict:
    """Open an investigation over a pasted alert or email. Format decides the
    subject kind (the 92/8 rule: format beats keywords); anything else is a
    422 — ACH v1 analyzes structured subjects, not open questions."""
    # Postgres text/jsonb cannot represent U+0000 at all, so a paste carrying
    # one 500'd at persist time (asyncpg UntranslatableCharacterError — S13
    # review, finding 1, live-verified). NUL carries no meaning in any alert
    # or email text; strip it BEFORE parsing so the parsers, the snapshot,
    # and the persisted statements all see the same text.
    q = body.message.replace("\x00", "").strip()
    if _is_alert_paste(q):
        kind = SubjectKind.ALERT
    elif _is_email_paste(q):
        kind = SubjectKind.EMAIL
    else:
        raise HTTPException(
            status_code=422,
            detail=(
                "The message is neither an alert paste (CEF/LEEF/syslog/JSON) "
                "nor an email paste (RFC-5322 headers) — an investigation "
                "needs a structured subject."
            ),
        )
    if body.session_id is not None:
        await _owned_session(request, auth, body.session_id)

    subject, _, evidence = _subject_snapshot(kind, q)
    investigation_id = await create_investigation(
        request.app.state.pool,
        workspace_id=auth.workspace_id,
        subject_kind=kind,
        subject=subject,
        hypotheses=seed_hypotheses(kind),
        evidence=evidence,
        session_id=body.session_id,
    )
    record = await load_investigation(
        request.app.state.pool,
        workspace_id=auth.workspace_id,
        investigation_id=investigation_id,
    )
    assert record is not None  # just created in this workspace
    logger.info(
        "investigation created: kind=%s evidence=%d",
        kind.value,
        len(record.evidence),
    )
    return _render(record)


@router.get("/{investigation_id}")
async def get_one(request: Request, investigation_id: UUID, auth: Auth) -> dict:
    record = await load_investigation(
        request.app.state.pool,
        workspace_id=auth.workspace_id,
        investigation_id=investigation_id,
    )
    if record is None:
        raise HTTPException(status_code=404, detail="Unknown investigation")
    return _render(record)


@router.post("/{investigation_id}/lookups")
async def run_lookup(
    request: Request, investigation_id: UUID, body: RunLookupBody, auth: Auth
) -> dict:
    """Execute the engine's recommended lookup (or a named candidate) through
    the S5 enrichment fan-out, fold the outcome in as evidence, re-assess.

    A completed lookup with no claim from any answering source folds in ONE
    weak ENRICHMENT_NO_SIGNAL row — that row is what retires the candidate,
    and it applies the small update the gain math priced into the "unknown"
    outcome. A lookup NO provider completed (outage, timeouts, breaker-open)
    yields nothing and the candidate honestly remains; `lookup_status` in the
    response says which happened. Repeated attempts against a failing
    provider set are bounded by the S5 circuit breaker (3 consecutive
    failures → 60 s open), not by this route."""
    pool = request.app.state.pool
    record = await load_investigation(
        pool, workspace_id=auth.workspace_id, investigation_id=investigation_id
    )
    if record is None:
        raise HTTPException(status_code=404, detail="Unknown investigation")

    enrichment: EnrichmentService = request.app.state.enrichment
    if not enrichment.active:
        raise HTTPException(status_code=503, detail="Enrichment is disabled on this host")

    _, plan = _assess(record)
    if not plan.ranked:
        raise HTTPException(
            status_code=409,
            detail=f"No lookup to run: {plan.reason or 'nothing ranked'}",
        )
    if body.obs_id is None:
        chosen = plan.ranked[0].candidate
    else:
        by_id = {r.candidate.observable.obs_id: r.candidate for r in plan.ranked}
        chosen = by_id.get(body.obs_id)
        if chosen is None:
            raise HTTPException(
                status_code=422,
                detail="obs_id is not among the current lookup candidates",
            )

    outcome = await enrichment.enrich((chosen.observable,))
    await persist_enrichment(pool, auth.workspace_id, outcome)  # the S5 trail too
    # evidence_from_enrichment already handles the completed-but-unknown case
    # (a weak ENRICHMENT_NO_SIGNAL row: retires the candidate, applies the
    # small update the gain math priced into the "unknown" outcome). A lookup
    # NO provider completed yields nothing — it stays a candidate, honestly.
    new_evidence = [e for item in outcome.items for e in evidence_from_enrichment(item)]
    written = 0
    if new_evidence:
        # written < len(new_evidence) means a concurrent fold already recorded
        # the same answer — the store dedups per (kind, source, obs_id)
        # under the investigation row lock (S13 review, finding 4).
        written = await add_evidence(
            pool,
            workspace_id=auth.workspace_id,
            investigation_id=investigation_id,
            evidence=new_evidence,
        )
    logger.info(
        "investigation lookup: obs=%s providers_failed=%d evidence=%d written=%d",
        chosen.observable.obs_id,
        len(outcome.provider_failures),
        len(new_evidence),
        written,
    )
    updated = await load_investigation(
        pool, workspace_id=auth.workspace_id, investigation_id=investigation_id
    )
    assert updated is not None
    rendered = _render(updated)
    # An honest status instead of a byte-identical 200 when nothing completed
    # (S12 verification finding 15): "completed" ⇒ evidence landed (a claim or
    # a no-signal coverage row); "not_completed" ⇒ no provider finished the
    # lookup — the candidate remains, and retrying is bounded by the S5
    # circuit breaker, not rewarded with fake progress.
    rendered["lookup_status"] = {
        "obs_id": chosen.observable.obs_id,
        "status": "completed" if new_evidence else "not_completed",
        "provider_failures": len(outcome.provider_failures),
    }
    return rendered


# -- S13: cited model rendering ------------------------------------------------

SUMMARY_SYSTEM_PROMPT = (
    "You are Auspex, a calm, precise security operations co-analyst. Answer "
    "concisely and analyst-to-analyst. If you are unsure, say so."
)
SUMMARY_MAX_TOKENS = 1500


async def get_summary_client_factory(request: Request):
    """The endpoint the summary renders against (the overridable test seam,
    chat's lazy-resolver shape): building the LLMClient (an httpx client)
    is deferred until the handler has passed its 404/tenancy checks, so a
    refused request never constructs a client it would have to close. The
    configured default only — the dev model switcher is a chat affordance,
    not an investigations one."""
    settings = request.app.state.settings

    def _build() -> LLMClient:
        if not settings.llm_base_url:
            raise HTTPException(status_code=503, detail="LLM endpoint not configured")
        return LLMClient.from_settings(settings)

    return _build


@router.post("/{investigation_id}/summary")
async def render_summary(
    request: Request,
    investigation_id: UUID,
    auth: Auth,
    llm_factory: Annotated[object, Depends(get_summary_client_factory)],
) -> dict:
    """Render a model-written, citation-carrying summary of the investigation
    (S13 — the first LLM call anywhere on the investigations surface).

    Division of labor is the S10/S11 pattern: CODE decides the matrix, the
    lookup plan, the leading hypothesis (pinned), and the citation ids; the
    MODEL narrates around them. Validation is post-hoc (TD-012): the contract
    check and the citation guard DETECT drift and report it in this response
    (`contract_valid`, `citations.ok`) — they do not prevent it. Nothing here
    is persisted; like every other read, the summary is recomputed on demand
    from stored inputs."""
    record = await load_investigation(
        request.app.state.pool,
        workspace_id=auth.workspace_id,
        investigation_id=investigation_id,
    )
    if record is None:
        raise HTTPException(status_code=404, detail="Unknown investigation")

    assessment, plan = _assess(record)
    bundle = investigation_directive(record, assessment, plan)
    messages = [
        {"role": "system", "content": SUMMARY_SYSTEM_PROMPT},
        {"role": "system", "content": SUMMARY_CONTRACT.system_directive()},
        {"role": "system", "content": bundle.text},
        {"role": "user", "content": "Render the investigation summary now."},
    ]
    # TD-018 (S19): this route is the OTHER inference spender, and the debt
    # entry named it explicitly so S19 would not wire only the chat path. One
    # call per request, claimed before it is made and shared with chat's
    # counter — a workspace's ceiling is on inference, not on a route.
    allowance = await UsageLimiter(request.app.state.pool).claim(
        workspace_id=auth.workspace_id, meter=Meter.INFERENCE_CALLS, units=1
    )
    if not allowance.allowed:
        logger.info(
            "workspace %s refused a summary: %s at %d/%s",
            auth.workspace_id,
            allowance.meter.value,
            allowance.used,
            allowance.limit,
        )
        raise HTTPException(status_code=429, detail=allowance.refusal_text)

    llm: LLMClient = llm_factory()
    try:
        result = await llm.chat(messages, max_tokens=SUMMARY_MAX_TOKENS, temperature=0)
    except LLMError as err:
        raise HTTPException(status_code=502, detail=f"LLM endpoint error: {err}") from err
    finally:
        await llm.aclose()

    answer = result.content or ""
    contract_result = (
        SUMMARY_CONTRACT.validate(answer, pinned=bundle.pinned) if answer else None
    )
    citations = check_citations(answer, bundle.citations) if answer else None
    if (contract_result and not contract_result.ok) or (citations and not citations.ok):
        # Structural reasons only — never the answer text (it derives from
        # tenant/attacker data; org data-handling rule, chat.py precedent).
        logger.info(
            "summary drift: contract=%s citations=%s",
            contract_result.reason() if contract_result else "empty",
            citations.reason() if citations else "empty",
        )
    return {
        "investigation_id": str(record.investigation_id),
        "mode": SUMMARY_CONTRACT.name,
        "summary": answer,
        "contract_valid": contract_result.ok if contract_result else None,
        "contract_reason": contract_result.reason() if contract_result else None,
        "pinned": bundle.pinned,
        "citations": (
            {
                "ok": citations.ok,
                "reason": citations.reason(),
                "cited_valid": citations.cited_valid,
                "unknown": list(citations.unknown),
                "uncited_claims": list(citations.uncited_claims),
                "sections_checked": list(citations.sections_checked),
            }
            if citations
            else None
        ),
        "citation_map": dict(bundle.citations),
        # No silent caps: when the trail is longer than the directive's bound,
        # the analyst is told the summary narrates a diagnostic subset.
        "evidence_shown": bundle.evidence_shown,
        "evidence_total": bundle.evidence_total,
        "finish_reason": result.finish_reason,
        "usage": (
            {
                "prompt_tokens": result.usage.prompt_tokens,
                "completion_tokens": result.usage.completion_tokens,
                "total_tokens": result.usage.total_tokens,
            }
            if result.usage
            else None
        ),
    }
