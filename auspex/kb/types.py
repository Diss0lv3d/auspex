"""KB data shapes — S6. Frozen dataclasses, same discipline as enrich/types.py.

A KBDoc is a source document (one CVE record, one technique page, one concept
entry). Chunking turns it into KBChunks — the unit that is embedded, indexed,
and retrieved. A KBHit is a retrieved chunk plus its retrieval score.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class KBDoc:
    doc_id: str  # canonical id: "CVE-2021-44228", "T1059.001", "CONCEPT-C2"
    title: str
    content: str
    doc_type: str  # "cve" | "technique" | "concept"
    source: str  # provenance label, e.g. "nvd", "attack-seed-summary"
    source_ref: str  # URL or feed reference ("" when none)
    ids: tuple[str, ...] = ()  # exact-match rail: normalized IDs this doc answers for
    severity: str = ""  # CVSS severity for cve docs ("" when n/a)
    cvss_score: float | None = None


@dataclass(frozen=True)
class KBChunk:
    doc: KBDoc
    chunk_index: int
    text: str

    @property
    def chunk_id(self) -> str:
        # Deterministic — re-ingesting a doc overwrites its chunks (upsert by _id).
        return f"{self.doc.doc_id}#{self.chunk_index}"


@dataclass(frozen=True)
class KBHit:
    chunk_id: str
    doc_id: str
    title: str
    text: str
    doc_type: str
    source: str
    source_ref: str
    ids: tuple[str, ...]
    severity: str
    cvss_score: float | None
    score: float


class KBUnavailable(Exception):
    """The KB could not answer this turn (breaker open, HTTP failure, missing
    model/index). Callers keep the honest deferred copy — never a 500.

    The exception MESSAGE is diagnostic (logs, tests). `public` is the clause
    rendered into user-facing copy (KB_UNAVAILABLE_COPY's {detail}) — analyst
    voice, no exception class names, no breaker/HTTP internals. S6 review:
    "(breaker open)" and "ConnectTimeout" were reaching the chat window."""

    def __init__(self, detail: str, *, public: str = "it didn't respond") -> None:
        super().__init__(detail)
        self.public = public
