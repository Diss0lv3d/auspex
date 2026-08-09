"""What would flip this verdict — derived in code, at write time.

Deterministic and zero-LLM by design (ROADMAP S15 constraint). Every condition
below is a claim the verdict is ALREADY making implicitly; deriving them is not
invention, it is writing down what the label commits us to so that a feed can
later contradict it.

The test of this vocabulary, set by the S15 prompt, is whether it can describe
what S14 already observed happening: the live retro-hunt flip was a `suspicious`
CVE verdict that became `malicious` after CVE-2026-35273 entered KEV. That is
`KEV_LISTING` on the CVE and `PROVIDER_ESCALATION` on the label, both of which
this module would have registered when the `suspicious` verdict was written —
so the platform could have said in advance exactly what did in fact change its
mind.
"""

from __future__ import annotations

from auspex.classify.observables import Observable, ObservableType
from auspex.enrich.types import SEVERITY, ProviderSignal, VerdictLabel
from auspex.enrich.verdict import Verdict
from auspex.watchers.types import FalsificationCondition, WatcherKind


def conditions_for(
    observable: Observable,
    verdict: Verdict,
    signals: tuple[ProviderSignal, ...] = (),
) -> tuple[FalsificationCondition, ...]:
    """The falsification conditions this verdict commits to.

    Empty is a legitimate answer and is not padded: a `malicious` CVE verdict
    already at the top of the severity order is not falsified by a KEV listing
    (KEV agrees with it) nor by anything more severe arriving, and inventing a
    watcher so the count looks better would be the platform claiming a
    self-check it does not perform."""
    conditions: list[FalsificationCondition] = []

    if observable.type is ObservableType.CVE:
        if SEVERITY[verdict.label] < SEVERITY[VerdictLabel.MALICIOUS]:
            conditions.append(
                FalsificationCondition(
                    kind=WatcherKind.KEV_LISTING,
                    claim=(
                        f"{observable.value} is not known to be exploited in the "
                        f"wild — this workspace holds it as {verdict.label.value}."
                    ),
                    params={"cve": observable.value},
                )
            )
        # Applies at every label, malicious included: a withdrawn record
        # invalidates the BASIS of a verdict rather than disagreeing with its
        # conclusion, and a confident label resting on a retracted document is
        # the more misleading of the two.
        conditions.append(
            FalsificationCondition(
                kind=WatcherKind.RECORD_WITHDRAWN,
                claim=(
                    f"This verdict rests on the published record for "
                    f"{observable.value}."
                ),
                params={"cve": observable.value},
            )
        )

    if SEVERITY[verdict.label] < SEVERITY[VerdictLabel.MALICIOUS]:
        # `sources` names WHO the claim is about. A claim of silence is only
        # honest about the providers that actually spoke this turn — "nobody
        # calls this malicious" would be a claim about providers we never asked.
        sources = sorted({s.provider for s in signals})
        conditions.append(
            FalsificationCondition(
                kind=WatcherKind.PROVIDER_ESCALATION,
                claim=(
                    "No connected source rates this worse than "
                    f"{verdict.label.value}"
                    + (f" ({', '.join(sources)} answered)." if sources else ".")
                ),
                params={"label": verdict.label.value, "sources": sources},
            )
        )

    return tuple(conditions)
