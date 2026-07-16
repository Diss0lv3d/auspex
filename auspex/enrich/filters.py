"""Enrichment skip filters — S5 (SARA intel_enricher.py:171-186 pattern).

Two hard skips, applied BEFORE any provider is contacted:
- private/reserved addresses: RFC1918, loopback, link-local, TEST-NET, ULA…
  carry no reputation and leak internal topology to third parties. `is_global`
  is the stdlib's one-stop check (False for every special-purpose range).
- ubiquitous domains: enriching google.com wastes provider quota to learn that
  Google is Google. Applies even to defanged occurrences — the defang is
  analyst signal (S7 verdict floor input), but the *lookup* is still pointless.

Skips are echoed honestly per-observable (DEFERRED rail), never silent.
"""

import ipaddress

from auspex.classify.classifier import is_common_domain
from auspex.classify.observables import Observable, ObservableType

PRIVATE_IP_SKIP = "private/reserved address — not routable, never enriched"
COMMON_DOMAIN_SKIP = "ubiquitous domain — skipped to keep provider quota for real signals"


def skip_reason(observable: Observable) -> str | None:
    """Why this observable must not be enriched, or None if it may be."""
    if observable.type in (ObservableType.IPV4, ObservableType.IPV6):
        # value is canonical (S4 normalization) — parse cannot fail here.
        if not ipaddress.ip_address(observable.value).is_global:
            return PRIVATE_IP_SKIP
    if observable.type is ObservableType.DOMAIN and is_common_domain(observable.value):
        return COMMON_DOMAIN_SKIP
    return None
