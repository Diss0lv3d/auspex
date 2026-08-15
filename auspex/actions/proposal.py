"""What a human is shown, and what the platform remembers it showed — S18.

S17 made an action declarable. This module is the bridge between a declaration
and a decision: it renders the card an approver reads, and it stamps the identity
of the declaration that card was rendered from.

Two things live here rather than in the route, and both for the same reason:

1. **The card is compiled from the spec (D-007, D-023).** Not from model prose,
   not from a hand-written template kept next to the action. What a human
   approves is the action's own declaration of what it touches, whether it can be
   put back, and — from the action's own `dry_run` against the real arguments —
   what it would actually do. A model that writes "this will safely quarantine
   one host" gets no say in what the card says.

2. **A spec has an identity that survives a process (TD-023).** An approval is a
   decision about a specific declaration, and an hour can pass between the
   decision and the execution — long enough for a deploy to change the action's
   risk, its scope, or its undo. The handler objects cannot answer "is this still
   the thing that was approved?" (a fresh process has different function objects
   for identical code), so the fingerprint covers the DECLARED facts an approver
   relied on, canonically serialised and hashed.

What the fingerprint deliberately does NOT cover: the handler bodies. We cannot
detect that someone changed what `isolate_host` does inside its function while
leaving every declared fact identical — that is a deploy-integrity problem, not
an approval problem, and pretending otherwise would make the check look stronger
than it is.
"""

from __future__ import annotations

import hashlib
import json

from auspex.actions.types import ActionOutcome, ActionSpec

# Bump when the canonical form changes shape, so old fingerprints compare
# unequal instead of accidentally matching a differently-computed new one.
FINGERPRINT_VERSION = 1


def canonical_spec(spec: ActionSpec) -> dict:
    """The declared facts an approver's decision rests on.

    Ordered and explicit rather than `dataclasses.asdict`: a field added to
    `ActionSpec` later must be considered here on purpose, because silently
    folding it in would invalidate every stored fingerprint on deploy, and
    silently omitting a meaningful one would let a changed action pass as
    unchanged.
    """
    return {
        "v": FINGERPRINT_VERSION,
        "name": spec.name,
        "description": spec.description,
        "risk": spec.risk.value,
        "scope": [
            {"system": s.system, "writes": s.writes, "detail": s.detail} for s in spec.scope
        ],
        "params": [
            {
                "name": p.name,
                "type": p.type.value,
                "description": p.description,
                "required": p.required,
                "enum": list(p.enum),
            }
            for p in spec.params
        ],
        "undo": (
            None
            if spec.undo is None
            else {
                "description": spec.undo.description,
                "restores": spec.undo.restores,
                "cannot_restore": list(spec.undo.cannot_restore),
            }
        ),
    }


def fingerprint(spec: ActionSpec) -> str:
    """A stable id for one declaration. Same declared facts → same string, in
    any process; any change an approver would have wanted to know about → a
    different string."""
    blob = json.dumps(canonical_spec(spec), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def card(spec: ActionSpec, *, arguments: dict, dry_run: ActionOutcome) -> dict:
    """The approval card: what this action WOULD do, to what, and whether it can
    be taken back.

    Every field comes from the spec or from the action's own dry run against the
    real arguments. `reversible` is the spec's answer, not the outcome's, for the
    same reason risk is `ToolLevel`: an action that declared what its undo cannot
    restore must not be able to present itself as fully reversible at the moment
    someone is deciding.
    """
    return {
        "action": spec.name,
        "summary": dry_run.would,
        "risk": spec.risk.value,
        "requires_approval": True,
        "arguments": dict(arguments),
        "affects": list(dry_run.affects),
        "systems": [
            {"system": s.system, "writes": s.writes, "detail": s.detail} for s in spec.scope
        ],
        "reversible": spec.reversible,
        "undo": (
            None
            if spec.undo is None
            else {
                "description": spec.undo.description,
                "restores": spec.undo.restores,
                "cannot_restore": list(spec.undo.cannot_restore),
            }
        ),
        "spec_fingerprint": fingerprint(spec),
        "detail": dict(dry_run.detail),
    }


__all__ = ["FINGERPRINT_VERSION", "canonical_spec", "card", "fingerprint"]
