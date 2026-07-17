"""Knowledge base on OpenSearch — S6. KB/RAG substrate: auspex-knowledge index,
server-side embeddings (D-018), BM25+kNN+RRF retrieval with ID bypass."""

from auspex.kb.echo import (
    DEFINITION_MISS_COPY,
    KB_UNAVAILABLE_COPY,
    render_cve_answer,
    render_definition_answer,
)
from auspex.kb.service import MAX_IDS_PER_LOOKUP, KnowledgeService
from auspex.kb.types import KBDoc, KBHit, KBUnavailable

__all__ = [
    "DEFINITION_MISS_COPY",
    "KB_UNAVAILABLE_COPY",
    "KBDoc",
    "KBHit",
    "KBUnavailable",
    "KnowledgeService",
    "MAX_IDS_PER_LOOKUP",
    "render_cve_answer",
    "render_definition_answer",
]
