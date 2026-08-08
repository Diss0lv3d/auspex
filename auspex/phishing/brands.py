"""Protected-brand allow-list for lookalike detection — S11.

Keys are the brand's second-level label (SLD, no TLD); values are the
registrable domains the brand actually uses. Anything else whose SLD matches
(or nearly matches) a key is a lookalike candidate (lookalike.py).

DECISION (S11): this is a CODE constant, not an env var or data file — the list
changes at code-review cadence (a new brand means new detection behavior worth
a test), exactly like SARA's BRAND_ALLOWLIST
(docs/probes/2026-07-18-sara-phishing-header-patterns.md §2). Ported from that
probe; extend via PR with a fixture test per added brand.
"""

from __future__ import annotations

BRAND_ALLOWLIST: dict[str, set[str]] = {
    "microsoft": {"microsoft.com"},
    "microsoftonline": {"microsoftonline.com"},
    "office365": {"office365.com"},
    "office": {"office.com"},
    "outlook": {"outlook.com"},
    "onedrive": {"onedrive.com"},
    "sharepoint": {"sharepoint.com"},
    "windowsazure": {"windowsazure.com"},
    "azure": {"azure.com", "azure.net"},
    "live": {"live.com"},
    "hotmail": {"hotmail.com"},
    "apple": {"apple.com"},
    "icloud": {"icloud.com"},
    "google": {"google.com"},
    "gmail": {"gmail.com"},
    "youtube": {"youtube.com"},
    "amazon": {"amazon.com"},
    "aws": {"aws.com"},
    "paypal": {"paypal.com"},
    "stripe": {"stripe.com"},
    "facebook": {"facebook.com"},
    "instagram": {"instagram.com"},
    "whatsapp": {"whatsapp.com"},
    "linkedin": {"linkedin.com"},
    "github": {"github.com"},
    "gitlab": {"gitlab.com"},
    "dropbox": {"dropbox.com"},
    "adobe": {"adobe.com"},
    "netflix": {"netflix.com"},
    "docusign": {"docusign.com", "docusign.net"},
    "slack": {"slack.com"},
    "zoom": {"zoom.us"},
    "salesforce": {"salesforce.com"},
    "oracle": {"oracle.com"},
    "ibm": {"ibm.com"},
    "chase": {"chase.com"},
    "wellsfargo": {"wellsfargo.com"},
    "bankofamerica": {"bankofamerica.com"},
    "citi": {"citi.com"},
    "hsbc": {"hsbc.com"},
    "barclays": {"barclays.com"},
}

# Brand SLDs shorter than this are only checked for TLD swaps — the
# Levenshtein near-miss space at distance 1 around "ibm"/"aws" explodes
# into unrelated legitimate domains (SARA's NEAR_MISS_MIN_LEN).
NEAR_MISS_MIN_LEN = 5
