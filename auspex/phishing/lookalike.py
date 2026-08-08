"""Deterministic lookalike-domain detection — S11 (ADR 0006: code, no LLM).

Four detection classes over a sender-adjacent domain, each a NAMED finding
with a confidence (never an opaque flag):

1. **TLD swap** (HIGH) — SLD matches a protected brand exactly, registrable
   domain is not on the brand's allow-list (`paypal.net`). SARA class 1.
2. **Near-miss SLD** (MEDIUM) — Damerau-Levenshtein 1–2 from a brand SLD
   (`micr0soft.com`, `paypla.com`). SARA class 2, with the same min-length
   guard so short brands don't false-positive the world.
3. **Homograph** (HIGH) — punycode (`xn--`) or raw non-ASCII in the domain
   that mixes scripts or confusable-folds onto a protected brand
   (`pаypal.com` with a Cyrillic а). Auspex extension beyond SARA's
   Cyrillic-range check: explicit confusable fold + brand re-check.
4. **Brand-subdomain bait** (MEDIUM) — a protected brand appears as a NON-
   registrable label (`login.paypal.com.secure-verify.io`); the user reads the
   brand, the DNS goes elsewhere. From SARA's subdomain-spoofing anomaly,
   promoted to a first-class finding (points 20 vs SARA's generic +10 — the
   pattern is specific enough to deserve its own name and weight).

Weights ride on the findings here (detection and weighting stay adjacent to
their class); the verdict layer only sums. Legitimate brand hosts (registrable
domain on the allow-list) return no findings, whatever their subdomains.
Reference: docs/probes/2026-07-18-sara-phishing-header-patterns.md §2.
"""

from __future__ import annotations

from auspex.phishing.brands import BRAND_ALLOWLIST, NEAR_MISS_MIN_LEN
from auspex.phishing.envelope import Finding, FindingType

# Common Cyrillic/Greek confusables → Latin. Deliberately the high-frequency
# set (what real IDN-homograph phish use), not full Unicode TR39.
_CONFUSABLES = str.maketrans(
    {
        "а": "a", "е": "e", "о": "o", "р": "p", "с": "c", "у": "y", "х": "x",
        "і": "i", "ѕ": "s", "һ": "h", "ԁ": "d", "ј": "j", "ԛ": "q", "ѡ": "w",
        "ν": "v", "ο": "o", "α": "a", "ρ": "p", "τ": "t", "υ": "u", "κ": "k",
        "η": "n", "ι": "i", "ϲ": "c", "ɡ": "g", "ⅼ": "l", "ℓ": "l",
    }
)

_LATIN = set("abcdefghijklmnopqrstuvwxyz")


# Multi-label public suffixes — the compound ccTLD second levels that real
# brands and real victims sit under. A curated code constant, like BRAND_ALLOWLIST
# (TD-015 path-to-fix item 3, partially closed): not the full Public Suffix List,
# but the commercially common set. Reading `amazon.co.uk` as registrable domain
# "co.uk" was not the harmless false-negative bias TD-015 claimed — it made every
# .co.uk address collapse onto one "domain" (S12 review D/E).
_MULTI_LABEL_SUFFIXES = frozenset(
    {
        "co.uk", "org.uk", "ac.uk", "gov.uk", "me.uk", "net.uk", "sch.uk", "ltd.uk", "plc.uk",
        "com.au", "net.au", "org.au", "edu.au", "gov.au", "id.au",
        "co.nz", "net.nz", "org.nz", "ac.nz", "govt.nz",
        "co.jp", "or.jp", "ne.jp", "ac.jp", "go.jp",
        "co.kr", "or.kr", "ne.kr",
        "co.in", "net.in", "org.in", "gov.in", "ac.in",
        "co.za", "org.za", "net.za", "gov.za",
        "co.il", "org.il", "net.il", "ac.il",
        "co.th", "in.th", "co.id", "or.id", "web.id",
        "com.br", "com.mx", "com.ar", "com.co", "com.pe", "com.ve",
        "com.tr", "com.cn", "com.hk", "com.tw", "com.sg", "com.my", "com.ph", "com.vn",
        "com.pk", "com.bd", "com.np", "com.lk",
        "com.eg", "com.sa", "com.qa", "com.kw", "com.bh", "com.om", "com.jo", "com.lb",
        "com.ng", "com.gh", "com.ua", "com.pl", "com.ro", "com.gr", "com.cy", "com.mt",
        "com.es", "com.pt", "com.it", "com.de", "com.fr", "com.ru",
    }
)


def _suffix_labels(parts: list[str]) -> int:
    """How many trailing labels form the public suffix — 2 for a compound
    ccTLD suffix (co.uk), else 1."""
    if len(parts) >= 3 and ".".join(parts[-2:]) in _MULTI_LABEL_SUFFIXES:
        return 2
    return 1


def registrable_domain(fqdn: str) -> str:
    """The registered domain: the public suffix plus the one label to its left.
    Compound-suffix aware (`amazon.co.uk` → `amazon.co.uk`, not `co.uk`).

    Coverage is still the curated `_MULTI_LABEL_SUFFIXES` set, so an exotic
    suffix outside it degrades the way the naive version always did — but for
    the suffixes real mail uses, this is now correct rather than
    optimistically-wrong."""
    parts = fqdn.lower().strip(".").split(".")
    want = _suffix_labels(parts) + 1
    return ".".join(parts[-want:]) if len(parts) >= want else ".".join(parts)


def _sld(fqdn: str) -> str:
    """The registered label — the one a brand name would occupy."""
    parts = fqdn.lower().strip(".").split(".")
    want = _suffix_labels(parts) + 1
    return parts[-want] if len(parts) >= want else ""


def is_brand_host(fqdn: str, brand: str) -> bool:
    """Whether `fqdn` is the brand's OWN host: its registrable domain is on the
    brand's canonical list, or it is `<brand>.<compound ccTLD suffix>` — the
    brand's country presence (`amazon.co.uk`, `hsbc.co.uk`), which the canonical
    list does not enumerate and should not have to.

    A single-label TLD off the canonical list (`amazon.net`, `paypal.xyz`) is
    NOT a brand host — that stays a TLD swap, because it is the shape attackers
    actually register. The ccTLD allowance is deliberately false-negative biased
    in the documented direction (TD-015)."""
    reg = registrable_domain(fqdn)
    if reg in BRAND_ALLOWLIST.get(brand, frozenset()):
        return True
    parts = reg.split(".")
    return len(parts) >= 3 and parts[0] == brand and ".".join(parts[1:]) in _MULTI_LABEL_SUFFIXES


def damerau_levenshtein(a: str, b: str, cap: int = 3) -> int:
    """Damerau-Levenshtein with early-exit cap (SARA-verbatim algorithm shape:
    transposition catches `paypla`; returns `cap` when the true distance ≥ cap)."""
    if a == b:
        return 0
    if abs(len(a) - len(b)) >= cap:
        return cap
    la, lb = len(a), len(b)
    prev_prev: list[int] = []
    prev: list[int] = list(range(lb + 1))
    for i in range(1, la + 1):
        curr = [i] + [0] * lb
        min_row = curr[0]
        for j in range(1, lb + 1):
            cost = 0 if a[i - 1] == b[j - 1] else 1
            curr[j] = min(curr[j - 1] + 1, prev[j] + 1, prev[j - 1] + cost)
            if i > 1 and j > 1 and a[i - 1] == b[j - 2] and a[i - 2] == b[j - 1]:
                curr[j] = min(curr[j], prev_prev[j - 2] + 1)
            min_row = min(min_row, curr[j])
        if min_row >= cap:
            return cap
        prev_prev, prev = prev, curr
    return min(prev[lb], cap)


def _fold(label: str) -> str:
    """Lower-case + confusable-fold a domain label to its Latin skeleton."""
    return label.lower().translate(_CONFUSABLES)


def _mixed_script(label: str) -> bool:
    """Latin chars mixed with confusable-range non-Latin in ONE label — the
    homograph hallmark (an all-native-script IDN is a legitimate domain)."""
    has_latin = any(c in _LATIN for c in label)
    has_nonlatin = any(ord(c) > 127 and _fold(c) != c for c in label)
    return has_latin and has_nonlatin


def _decode_punycode(label: str) -> str | None:
    try:
        return label.encode("ascii").decode("idna")
    except (UnicodeError, ValueError):
        return None


def check_domain(fqdn: str | None) -> tuple[Finding, ...]:
    """All lookalike findings for one domain. Empty for None, for domains on a
    brand's allow-list, and for domains with no brand resemblance."""
    if not fqdn or "." not in fqdn:
        return ()
    fqdn = fqdn.lower().strip(".").rstrip(">").strip()
    findings: list[Finding] = []

    # ── homograph: punycode labels and raw non-ASCII ─────────────────────────
    labels = fqdn.split(".")
    unicode_labels: list[str] = []
    for lab in labels:
        if lab.startswith("xn--"):
            decoded = _decode_punycode(lab)
            if decoded is None:
                findings.append(
                    Finding(
                        FindingType.HOMOGRAPH,
                        "MEDIUM",
                        20,
                        f"Sender domain carries an undecodable punycode label ({lab})",
                    )
                )
            else:
                unicode_labels.append(decoded)
        elif any(ord(c) > 127 for c in lab):
            unicode_labels.append(lab)
    for lab in unicode_labels:
        folded = _fold(lab)
        brand_hit = folded in BRAND_ALLOWLIST
        if _mixed_script(lab) or (brand_hit and folded != lab):
            hallmark = (
                f"confusable-folds to protected brand '{folded}'"
                if brand_hit
                else "mixes Latin with confusable non-Latin characters"
            )
            findings.append(
                Finding(
                    FindingType.HOMOGRAPH,
                    "HIGH",
                    30,
                    f"IDN homograph: sender domain label '{lab}' {hallmark}",
                )
            )

    # ASCII skeleton for the brand checks (folds any decoded unicode labels).
    def _skeleton(lab: str) -> str:
        return _fold(_decode_punycode(lab) or lab) if lab.startswith("xn--") else _fold(lab)

    ascii_fqdn = ".".join(_skeleton(lab) for lab in labels)
    registrable = registrable_domain(ascii_fqdn)
    sld = _sld(ascii_fqdn)
    if not sld:
        return tuple(findings)

    # Legitimate brand host → nothing else to flag (subdomains included).
    if sld in BRAND_ALLOWLIST and is_brand_host(ascii_fqdn, sld):
        return tuple(findings)

    # ── class 1: TLD swap ────────────────────────────────────────────────────
    if sld in BRAND_ALLOWLIST:
        canonical = ", ".join(sorted(BRAND_ALLOWLIST[sld]))
        findings.append(
            Finding(
                FindingType.TYPOSQUAT_TLD_SWAP,
                "HIGH",
                30,
                f"TLD swap: {registrable} uses protected brand '{sld}' off its "
                f"canonical domain(s) ({canonical})",
            )
        )
    # ── class 2: near-miss SLD ───────────────────────────────────────────────
    elif len(sld) >= NEAR_MISS_MIN_LEN:
        best: tuple[int, str, str] | None = None  # (distance, brand, canonical)
        for brand, allowed in BRAND_ALLOWLIST.items():
            if len(brand) < NEAR_MISS_MIN_LEN or abs(len(sld) - len(brand)) > 2:
                continue
            dist = damerau_levenshtein(sld, brand, cap=3)
            if 1 <= dist <= 2 and (best is None or dist < best[0]):
                best = (dist, brand, ", ".join(sorted(allowed)))
        if best is not None:
            dist, brand, canonical = best
            findings.append(
                Finding(
                    FindingType.TYPOSQUAT_NEAR_MISS,
                    "MEDIUM",
                    30,
                    f"Typosquat: {registrable} is {dist} edit(s) from protected "
                    f"brand '{brand}' (canonical: {canonical})",
                )
            )

    # ── class 4: brand as a non-registrable label ────────────────────────────
    # Everything left of the registrable domain — computed from its label count,
    # so `amazon.co.uk` has NO prefix labels and cannot bait against itself.
    prefix = ascii_fqdn.split(".")[: -(registrable.count(".") + 1)]
    bait = next((lab for lab in prefix if lab in BRAND_ALLOWLIST), None)
    if bait is not None:
        findings.append(
            Finding(
                FindingType.BRAND_SUBDOMAIN_BAIT,
                "MEDIUM",
                20,
                f"Brand-subdomain bait: '{bait}' appears as a subdomain label "
                f"but the domain actually registered is {registrable}",
            )
        )
    return tuple(findings)
