"""auspex.classify — the code-owned 92/8 fast path (S4).

Pure, deterministic, LLM-free and network-free. Code picks the path, never a
prompt (ADR: code over prompts). Pattern source: SARA Open's fast classifier
(docs/probes/2026-07-16-sara-fastpath-pattern.md) — pattern reused, not code.
"""

from auspex.classify.classifier import Category, Classification, classify
from auspex.classify.observables import (
    Extraction,
    Observable,
    ObservableType,
    extract,
    extract_observables,
    observable_id,
    refang,
)

__all__ = [
    "Category",
    "Classification",
    "Extraction",
    "Observable",
    "ObservableType",
    "classify",
    "extract",
    "extract_observables",
    "observable_id",
    "refang",
]
