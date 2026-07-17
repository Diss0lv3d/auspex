"""Merge one NVD-parsed KBDoc with KEV + EPSS evidence — pure, no I/O.

Absence stays absent: no KEV entry leaves the KEV fields empty (the echo then
makes no exploitation claim either way); ransomware "Unknown" maps to False,
which the echo renders as silence, never "no". EPSS strings become floats here
(probe: 9-decimal strings) so the echo formats from numbers.
"""

from dataclasses import replace

from auspex.kb.types import KBDoc


def enrich_doc(doc: KBDoc, kev_entry: dict | None, epss_row: dict | None) -> KBDoc:
    updates: dict = {}
    if kev_entry:
        updates["kev_date_added"] = kev_entry.get("dateAdded", "")
        updates["kev_ransomware"] = kev_entry.get("knownRansomwareCampaignUse") == "Known"
    if epss_row:
        updates["epss_score"] = float(epss_row["epss"])
        updates["epss_percentile"] = float(epss_row["percentile"])
        updates["epss_date"] = epss_row.get("date", "")
    return replace(doc, **updates) if updates else doc
