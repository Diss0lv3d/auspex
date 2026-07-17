"""Enrichment fan-out + verdict store — S5.

Public surface: the service (lifespan-owned), the renderer (chat route), the
persister (chat route), and the core types. Providers, breaker, filters, and
synthesis are internal wiring — import from their modules in tests only.
"""

from auspex.enrich.echo import render_ioc_answer
from auspex.enrich.service import EnrichmentService
from auspex.enrich.store import persist_enrichment
from auspex.enrich.types import (
    EnrichmentOutcome,
    ObservableEnrichment,
    ProviderError,
    ProviderSignal,
    VerdictLabel,
)

__all__ = [
    "EnrichmentOutcome",
    "EnrichmentService",
    "ObservableEnrichment",
    "ProviderError",
    "ProviderSignal",
    "VerdictLabel",
    "persist_enrichment",
    "render_ioc_answer",
]
