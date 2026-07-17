"""Per-doc change events — the S7 extension point. Emit-only.

Ingest EMITS one DocChange per upserted doc; nothing consumes them yet. The
"kev-added" kind is the future retro-hunt trigger (S14 — new intel re-hunts
historical observables); building a consumer now would be speculative, so the
default sink is an explicit no-op (ROADMAP S7 note 4).
"""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class DocChange:
    doc_id: str  # "CVE-2026-58644"
    feed: str  # "nvd-delta" | "kev"
    kind: str  # "upserted" | "kev-added" | "deleted" (NVD rejected a held CVE)


class ChangeSink(Protocol):
    async def emit(self, changes: Sequence[DocChange]) -> None: ...


class NullSink:
    """Deliberate no-op — consumers land with retro-hunt (S14)."""

    async def emit(self, changes: Sequence[DocChange]) -> None:
        return None
