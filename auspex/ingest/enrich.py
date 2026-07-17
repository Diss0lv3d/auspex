"""Merge one NVD-parsed KBDoc with KEV + EPSS evidence — pure, no I/O.

Absence stays absent: no KEV entry leaves the KEV fields empty (the echo then
makes no exploitation claim either way); ransomware "Unknown" maps to False,
which the echo renders as silence, never "no". EPSS strings become floats here
(probe: 9-decimal strings) so the echo formats from numbers.

Feed values are untrusted: a non-numeric or non-finite EPSS value would ride
into the bulk payload as a bare NaN/Infinity token, OpenSearch would reject
the whole batch, and the watermark would wedge on the same window forever
(S8 review). Malformed rows degrade to absence instead.
"""

import math
from dataclasses import replace

from auspex.kb.types import KBDoc


def _finite(value) -> float | None:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if math.isfinite(out) else None


def enrich_doc(doc: KBDoc, kev_entry: dict | None, epss_row: dict | None) -> KBDoc:
    updates: dict = {}
    if kev_entry:
        updates["kev_listed"] = True  # presence keyed on the entry, not its date (S8)
        updates["kev_date_added"] = kev_entry.get("dateAdded", "")
        updates["kev_ransomware"] = kev_entry.get("knownRansomwareCampaignUse") == "Known"
    if epss_row:
        score = _finite(epss_row.get("epss"))
        percentile = _finite(epss_row.get("percentile"))
        if score is not None:
            updates["epss_score"] = score
            updates["epss_date"] = epss_row.get("date", "")
        if percentile is not None:
            updates["epss_percentile"] = percentile
    return replace(doc, **updates) if updates else doc
