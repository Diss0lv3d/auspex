"""KB-backed shortcut copy — S6. Plain text (UI renders verbatim), Auspex
voice, engine never named. Same honesty rules as enrich/echo.py:

- a CVE block only renders what the KB actually holds; a requested CVE the
  KB doesn't know gets an explicit per-line miss, never silence;
- KB *unavailable* is different copy from KB *doesn't know* — "isn't
  connected yet" (deferred), "didn't answer this turn" (down), and "not in
  the knowledge base yet" (a miss) are three different truths;
- definition answers cite their source; seed-summary provenance is labeled
  as such, never passed off as verbatim MITRE/NVD text.
"""

from auspex.kb.types import KBHit

KB_UNAVAILABLE_COPY = (
    "The knowledge base didn't answer this turn — {detail}. Nothing was "
    "fabricated in its place; try again shortly, or ask for an analysis in "
    "context and I'll take the deep path."
)

CVE_MISS_LINE = "not in the knowledge base yet — curated feeds grow over time"

DEFINITION_MISS_COPY = (
    "That term isn't in the knowledge base yet — curated content grows over "
    'time. Ask me to reason about it in context — e.g. "explain how this '
    "shows up in an investigation\" — and I'll take the deep path."
)

_SOURCE_LABELS = {
    "nvd": "NVD",
    "attack-seed-summary": "MITRE ATT&CK (Auspex seed summary)",
    "auspex-seed": "Auspex seed corpus",
}


def _source_label(hit: KBHit) -> str:
    return _SOURCE_LABELS.get(hit.source, hit.source or "knowledge base")


def _chunk_order(hit: KBHit) -> int:
    # chunk_id is "<doc_id>#<index>" — lexicographic sort put #10 before #2
    # once a doc grows past ten chunks (S6 review; S7 feeds bring long docs).
    try:
        return int(hit.chunk_id.rsplit("#", 1)[1])
    except (IndexError, ValueError):
        return 0


def _exploitation_lines(hit: KBHit) -> list[str]:
    """KEV/EPSS enrichment, rendered only from held evidence (S7). No KEV row
    ⇒ no exploitation claim either way; no EPSS row ⇒ no likelihood number.
    'Unknown' ransomware use renders as nothing — absence of evidence."""
    lines: list[str] = []
    if hit.kev_date_added:
        line = f"  Known exploited — in CISA KEV since {hit.kev_date_added}"
        if hit.kev_ransomware:
            line += "; used in ransomware campaigns"
        lines.append(line + ".")
    if hit.epss_score is not None:
        line = f"  EPSS {hit.epss_score:.2f}"
        if hit.epss_percentile is not None:
            line += f" — {hit.epss_percentile * 100:.1f}th percentile"
        if hit.epss_date:
            line += f" (as of {hit.epss_date})"
        lines.append(line + ".")
    return lines


def _cve_block(cve_id: str, hits: list[KBHit]) -> str:
    if not hits:
        return f"- {cve_id} — {CVE_MISS_LINE}"
    first = hits[0]
    header = f"- {cve_id}"
    if first.severity:
        header += f" — {first.severity}"
        if first.cvss_score is not None:
            header += f" (CVSS {first.cvss_score})"
    elif first.cvss_score is not None:
        header += f" — CVSS {first.cvss_score}"
    body_lines = [f"  {h.text}" for h in hits] + _exploitation_lines(first)
    body = "\n".join(body_lines)
    trailer = f"  Source: {_source_label(first)}"
    if first.source_ref:
        trailer += f" · {first.source_ref}"
    return f"{header}\n{body}\n{trailer}"


def render_cve_answer(requested: list[str], hits: list[KBHit], *, omitted: int = 0) -> str:
    """One block per requested CVE, in request order; misses are explicit.
    `hits` is whatever lookup_ids returned — grouped here by exact id match.
    `omitted` = CVEs the caller capped away this turn; saying so keeps the
    answer honest — a capped CVE must never read as "not in the knowledge base"."""
    by_id: dict[str, list[KBHit]] = {cve: [] for cve in requested}
    for hit in hits:
        for cve in requested:
            if cve.upper() in hit.ids:
                by_id[cve].append(hit)
    for group in by_id.values():
        group.sort(key=_chunk_order)
    count = len(requested)
    noun = "vulnerability" if count == 1 else "vulnerabilities"
    blocks = "\n".join(_cve_block(cve, by_id[cve]) for cve in requested)
    answer = f"Knowledge base read on {count} {noun}:\n\n{blocks}"
    if omitted:
        noun_more = "was" if omitted == 1 else "were"
        answer += (
            f"\n\n{omitted} more {noun_more} requested — I read up to {count} per turn; "
            "ask about the rest in a follow-up and I'll cover them too."
        )
    return answer


def render_definition_answer(hits: list[KBHit]) -> str | None:
    """Top-hit definition with provenance, or None when the KB has nothing
    relevant (caller keeps the deferred copy — an empty KB stays honest)."""
    if not hits:
        return None
    top = hits[0]
    title = top.title or top.doc_id
    lines = [f"{title} — from the knowledge base:", "", top.text]
    related = [h for h in hits[1:] if h.doc_id != top.doc_id]
    if related:
        seen: dict[str, None] = {}
        for h in related:
            label = h.title or h.doc_id
            # Parenthesize ids analysts recognize (CVE-…, T1059) — never our
            # internal CONCEPT-* naming scheme (S6 review: copy leak).
            if h.title and h.title != h.doc_id and not h.doc_id.startswith("CONCEPT-"):
                label = f"{h.title} ({h.doc_id})"
            seen.setdefault(label)
        lines += ["", "Related entries: " + "; ".join(list(seen)[:3])]
    trailer = f"Source: {_source_label(top)}"
    if top.source_ref:
        trailer += f" · {top.source_ref}"
    lines += ["", trailer]
    return "\n".join(lines)
