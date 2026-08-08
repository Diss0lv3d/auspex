"""Persistence for ACH investigations — S12, D-008 workspace-scoped throughout.

The database stores INPUTS only: the subject snapshot, the hypothesis
identities, and the append-only evidence trail. Scores, statuses, weights, and
lookup plans are recomputed by auspex.ach (pure functions) on every read — the
math has one source of truth and stored rows can never drift from it (the same
reason verdicts store decay PARAMETERS and compute effective confidence at
read, D-017).

Evidence rows persist their cell vector AS WRITTEN: a later curation change to
the doctrine tables (evidence.py) re-scores future evidence without silently
rewriting what past evidence meant when it was recorded.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from uuid import UUID

import asyncpg

from auspex.ach.types import (
    Cell,
    Evidence,
    EvidenceKind,
    Hypothesis,
    HypothesisKey,
    SubjectKind,
)


@dataclass(frozen=True)
class InvestigationRecord:
    """One investigation as loaded from Postgres — inputs, not conclusions."""

    investigation_id: UUID
    subject_kind: SubjectKind
    subject: dict
    status: str
    hypotheses: tuple[Hypothesis, ...]
    evidence: tuple[Evidence, ...]


def _cells_to_json(cells) -> str:
    return json.dumps({k.value: v for k, v in cells.items()})


def _cells_from_json(raw: str | dict) -> dict[HypothesisKey, Cell]:
    data = raw if isinstance(raw, dict) else json.loads(raw)
    out: dict[HypothesisKey, Cell] = {}
    for key, cell in data.items():
        try:
            out[HypothesisKey(key)] = cell
        except ValueError:
            continue  # a key retired from the vocabulary: ignore, never crash a load
    return out


async def create_investigation(
    pool: asyncpg.Pool,
    *,
    workspace_id: UUID,
    subject_kind: SubjectKind,
    subject: dict,
    hypotheses: Sequence[Hypothesis],
    evidence: Sequence[Evidence],
    session_id: UUID | None = None,
) -> UUID:
    """Create the investigation with its seeded hypotheses and initial
    deterministic evidence, in one transaction."""
    async with pool.acquire() as conn, conn.transaction():
        investigation_id: UUID = await conn.fetchval(
            """
            INSERT INTO investigations (workspace_id, session_id, subject_kind, subject)
            VALUES ($1, $2, $3, $4)
            RETURNING id
            """,
            workspace_id,
            session_id,
            subject_kind.value,
            json.dumps(subject),
        )
        for h in hypotheses:
            await conn.execute(
                """
                INSERT INTO hypotheses (workspace_id, investigation_id, key, label)
                VALUES ($1, $2, $3, $4)
                """,
                workspace_id,
                investigation_id,
                h.key.value,
                h.label,
            )
        await _insert_evidence(conn, workspace_id, investigation_id, evidence)
    return investigation_id


async def add_evidence(
    pool: asyncpg.Pool,
    *,
    workspace_id: UUID,
    investigation_id: UUID,
    evidence: Sequence[Evidence],
) -> int:
    """Append evidence rows (ownership already verified by the caller's load).
    Returns rows written; also bumps the investigation's updated_at."""
    if not evidence:
        return 0
    async with pool.acquire() as conn, conn.transaction():
        await _insert_evidence(conn, workspace_id, investigation_id, evidence)
        await conn.execute(
            """
            UPDATE investigations SET updated_at = now()
            WHERE id = $1 AND workspace_id = $2
            """,
            investigation_id,
            workspace_id,
        )
    return len(evidence)


async def _insert_evidence(
    conn: asyncpg.Connection,
    workspace_id: UUID,
    investigation_id: UUID,
    evidence: Sequence[Evidence],
) -> None:
    for e in evidence:
        await conn.execute(
            """
            INSERT INTO ach_evidence
                (workspace_id, investigation_id, kind, statement, credibility,
                 cells, source, obs_id)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
            """,
            workspace_id,
            investigation_id,
            e.kind.value,
            e.statement,
            e.credibility,
            _cells_to_json(e.cells),
            e.source,
            e.obs_id,
        )


async def load_investigation(
    pool: asyncpg.Pool, *, workspace_id: UUID, investigation_id: UUID
) -> InvestigationRecord | None:
    """Load one investigation with hypotheses and the evidence trail. Returns
    None when absent OR owned by another workspace — the caller cannot tell
    the difference, deliberately (tenant isolation is an invariant)."""
    async with pool.acquire() as conn:
        inv = await conn.fetchrow(
            """
            SELECT id, subject_kind, subject, status
            FROM investigations
            WHERE id = $1 AND workspace_id = $2
            """,
            investigation_id,
            workspace_id,
        )
        if inv is None:
            return None
        hyp_rows = await conn.fetch(
            """
            SELECT key, label FROM hypotheses
            WHERE investigation_id = $1 AND workspace_id = $2
            ORDER BY created_at, key
            """,
            investigation_id,
            workspace_id,
        )
        ev_rows = await conn.fetch(
            """
            SELECT kind, statement, credibility, cells, source, obs_id
            FROM ach_evidence
            WHERE investigation_id = $1 AND workspace_id = $2
            ORDER BY created_at, id
            """,
            investigation_id,
            workspace_id,
        )
    subject = inv["subject"]
    return InvestigationRecord(
        investigation_id=inv["id"],
        subject_kind=SubjectKind(inv["subject_kind"]),
        subject=subject if isinstance(subject, dict) else json.loads(subject),
        status=inv["status"],
        hypotheses=tuple(
            Hypothesis(key=HypothesisKey(r["key"]), label=r["label"]) for r in hyp_rows
        ),
        evidence=tuple(
            Evidence(
                kind=EvidenceKind(r["kind"]),
                statement=r["statement"],
                credibility=r["credibility"],
                cells=_cells_from_json(r["cells"]),
                source=r["source"],
                obs_id=r["obs_id"],
            )
            for r in ev_rows
        ),
    )
