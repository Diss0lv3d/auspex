"""Provider registry — which clients activate for a given Settings.

Activation policy (probe-driven, see docs/probes/2026-07-16-enrichment-providers.md):
- Always-on, probed keyless: InternetDB, CIRCL hashlookup, OTX (key optional).
- Key-gated: URLhaus + ThreatFox (one abuse.ch Auth-Key covers both — keyless
  is 401 since 2024, probe mismatch #1), AbuseIPDB, GreyNoise (keyless budget
  is 25/week — useless, mismatch #3).
"""

from auspex.config import Settings
from auspex.enrich.providers.abuseipdb import AbuseIPDB
from auspex.enrich.providers.base import Provider
from auspex.enrich.providers.greynoise import GreyNoise
from auspex.enrich.providers.hashlookup import Hashlookup
from auspex.enrich.providers.internetdb import InternetDB
from auspex.enrich.providers.otx import OTX
from auspex.enrich.providers.threatfox import ThreatFox
from auspex.enrich.providers.urlhaus import URLhaus

__all__ = [
    "AbuseIPDB",
    "GreyNoise",
    "Hashlookup",
    "InternetDB",
    "OTX",
    "Provider",
    "ThreatFox",
    "URLhaus",
    "build_providers",
]


def build_providers(settings: Settings) -> list[Provider]:
    providers: list[Provider] = [
        InternetDB(),
        Hashlookup(),
        OTX(api_key=settings.otx_api_key),
    ]
    if settings.abusech_auth_key:
        providers.append(URLhaus(settings.abusech_auth_key))
        providers.append(ThreatFox(settings.abusech_auth_key))
    if settings.abuseipdb_api_key:
        providers.append(AbuseIPDB(settings.abuseipdb_api_key))
    if settings.greynoise_api_key:
        providers.append(GreyNoise(settings.greynoise_api_key))
    return providers
