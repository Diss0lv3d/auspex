"""Victim-domain IOC filtering — S11 goal 4. A phishing email names its victim:
the recipient's own domain, mailbox, and internal infrastructure appear all
over the headers and body. Surfacing those as "malicious indicators" points the
response at the victim instead of the attacker — so they are filtered in CODE
before the indicator list reaches the directive (render.py).

Filtered: observables whose registrable domain matches a recipient domain
(domains, URLs by host, email addresses by domain) and private/loopback/
link-local/reserved IPs (internal infrastructure is not an IOC in a phishing
write-up). The SENDER side is never filtered — it is the suspect, even when it
spoofs the victim's own domain (the auth findings carry that story)."""

from __future__ import annotations

import ipaddress
from urllib.parse import urlparse

from auspex.classify.observables import Observable, ObservableType
from auspex.phishing.envelope import EmailEnvelope
from auspex.phishing.lookalike import registrable_domain


def _host_of(o: Observable) -> str | None:
    if o.type is ObservableType.DOMAIN:
        return o.value.lower()
    if o.type is ObservableType.EMAIL:
        return o.value.rsplit("@", 1)[-1].lower() if "@" in o.value else None
    if o.type is ObservableType.URL:
        try:
            return (urlparse(o.value).hostname or "").lower() or None
        except ValueError:
            return None
    return None


def _is_internal_ip(value: str) -> bool:
    try:
        ip = ipaddress.ip_address(value)
    except ValueError:
        return False
    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    )


def filter_victim_iocs(
    env: EmailEnvelope,
) -> tuple[tuple[Observable, ...], int]:
    """Split the envelope's IOCs into (kept, withheld_count). Withheld =
    recipient-domain artifacts + internal IPs; kept = everything that could
    actually be attacker infrastructure."""
    victim_regs = {registrable_domain(d) for d in env.recipient_domains}
    kept: list[Observable] = []
    withheld = 0
    for o in env.iocs:
        if o.type in (ObservableType.IPV4, ObservableType.IPV6) and _is_internal_ip(o.value):
            withheld += 1
            continue
        host = _host_of(o)
        if host and victim_regs and registrable_domain(host) in victim_regs:
            withheld += 1
            continue
        kept.append(o)
    return tuple(kept), withheld
