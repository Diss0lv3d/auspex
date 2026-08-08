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


def _sender_artifacts(env: EmailEnvelope) -> set[str]:
    """The sender-side values that are NEVER victim-filtered — the suspect's own
    address and reply/bounce paths. A self-spoof (From: ceo@acme.com to
    finance@acme.com) makes the sender look exactly like a victim artifact; it
    is still the single most important indicator in the message."""
    return {
        v.lower()
        for v in (
            env.from_addr,
            env.from_domain,
            env.reply_to_addr,
            env.reply_to_domain,
            env.return_path_addr,
            env.return_path_domain,
        )
        if v
    }


def sender_forges_recipient_domain(env: EmailEnvelope) -> bool:
    """Whether the sender claims the recipient's own domain — the self-spoof
    shape behind most BEC. The directive has to call this out: the sender is an
    indicator here, and every other rule in the block is telling the model that
    the recipient's domain is not one."""
    if not env.from_domain or not env.recipient_domains:
        return False
    victim_regs = {registrable_domain(d) for d in env.recipient_domains}
    return registrable_domain(env.from_domain) in victim_regs


def filter_victim_iocs(
    env: EmailEnvelope,
) -> tuple[tuple[Observable, ...], int]:
    """Split the envelope's IOCs into (kept, withheld_count). Withheld =
    recipient-domain artifacts + internal IPs; kept = everything that could
    actually be attacker infrastructure — including every sender-side artifact,
    whatever domain it claims.

    The sender exemption is enforced HERE, not assumed: before the S12 review
    the recipient-domain match ran over all observables, so a BEC self-spoof had
    its From address silently withheld and the directive then told the model not
    to list it (finding B, verified by execution)."""
    victim_regs = {registrable_domain(d) for d in env.recipient_domains}
    sender = _sender_artifacts(env)
    kept: list[Observable] = []
    withheld = 0
    for o in env.iocs:
        if o.value.lower() in sender:
            kept.append(o)
            continue
        if o.type in (ObservableType.IPV4, ObservableType.IPV6) and _is_internal_ip(o.value):
            withheld += 1
            continue
        host = _host_of(o)
        if host and victim_regs and registrable_domain(host) in victim_regs:
            withheld += 1
            continue
        kept.append(o)
    return tuple(kept), withheld
