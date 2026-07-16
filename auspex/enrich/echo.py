"""Enriched ioc_check copy — S5. Plain text (the UI renders verbatim), Auspex
voice, engine never named (provider names are data sources, not the engine).

Honesty rules (D-014 spirit, DEFERRED rail):
- a verdict line only ever reports what providers actually returned;
- skipped observables say why, per line — never silently dropped;
- provider failures get a trailer line, so "no signal" can't masquerade as
  "nothing wrong";
- observables whose type no connected source covers say so.
"""

from auspex.classify.observables import Observable, ObservableType
from auspex.enrich.types import EnrichmentOutcome, ObservableEnrichment, VerdictLabel
from auspex.enrich.verdict import synthesize

# No obs_id-lookup path exists yet (parked in IDEAS.md) — the copy must only
# promise what works today: pasting the indicator again re-runs enrichment.
VERDICTS_RECORDED_COPY = (
    "Verdicts are recorded and decay over time; paste an indicator again for a fresh read."
)


def _observable_line(o: Observable) -> str:
    # Same shape as the S4 static echo (shortcuts.py) — one surface, one format.
    line = f"- {o.value} — {o.type} (id {o.obs_id})"
    if o.defanged:
        line += " · received defanged"
    return line


def _detail_line(item: ObservableEnrichment, coverage: dict[ObservableType, int]) -> str:
    if item.skip_reason is not None:
        return item.skip_reason
    if not item.signals:
        asked = coverage.get(item.observable.type, 0)
        if asked == 0:
            return "no connected source covers this observable type yet"
        noun = "source" if asked == 1 else "sources"
        return f"no signal from {asked} connected {noun} — unknown to them"
    verdict = synthesize(item.observable, item.signals)
    evidence = "; ".join(f"{s.provider}: {s.summary}" for s in item.signals)
    if verdict is None or verdict.label is VerdictLabel.UNKNOWN:
        return f"no reputation verdict — context: {evidence}"
    return f"verdict: {verdict.label} (confidence {verdict.confidence_at_write:.2f}) — {evidence}"


def render_ioc_answer(outcome: EnrichmentOutcome, coverage: dict[ObservableType, int]) -> str:
    count = len(outcome.items)
    noun = "observable" if count == 1 else "observables"
    blocks = [
        f"{_observable_line(item.observable)}\n  {_detail_line(item, coverage)}"
        for item in outcome.items
    ]
    text = f"Parsed {count} {noun}:\n\n" + "\n".join(blocks)
    if outcome.provider_failures:
        # A provider can fail one lookup yet answer another in the same turn
        # (per-call fan-out); "partial" keeps the trailer from contradicting a
        # signal line above it (seen live: OTX timed out on an IP, answered a hash).
        answered = {s.provider for item in outcome.items for s in item.signals}
        downs = "; ".join(
            f"{name} (partial — {reason})" if name in answered else f"{name} ({reason})"
            for name, reason in sorted(outcome.provider_failures.items())
        )
        text += f"\n\nSources unavailable this turn: {downs}."
    if any(item.signals for item in outcome.items):
        text += f"\n\n{VERDICTS_RECORDED_COPY}"
    return text
