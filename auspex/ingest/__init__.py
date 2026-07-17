"""Feed ingestion — S7. NVD delta + CISA KEV + FIRST EPSS merge into enriched
per-CVE docs in the S6 knowledge base; a startup catch-up scheduler tolerates
multi-day host gaps (ingest_state watermarks in Postgres)."""

from auspex.ingest.enrich import enrich_doc
from auspex.ingest.epss import EPSSFeed
from auspex.ingest.events import ChangeSink, DocChange, NullSink
from auspex.ingest.kev import KEVCatalog, KEVFeed
from auspex.ingest.nvd import NVDError, NVDFeed, is_rejected, windows

__all__ = [
    "ChangeSink",
    "DocChange",
    "EPSSFeed",
    "KEVCatalog",
    "KEVFeed",
    "NVDError",
    "NVDFeed",
    "NullSink",
    "enrich_doc",
    "is_rejected",
    "windows",
]
