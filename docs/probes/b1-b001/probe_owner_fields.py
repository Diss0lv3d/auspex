"""B1 — what the connected sources ALREADY return about 34.187.179.218's network.

The IOC check called AbuseIPDB and OTX on turn 1 and rendered "no signal". This
prints the network-describing fields each response carries (never the key, never
the full body), to see whether the platform had the owner and dropped it.
Two outbound calls. Keys come from .env via Settings.

Run:  .venv/bin/python docs/probes/b1-b001/probe_owner_fields.py
"""

import asyncio
import sys

import httpx

sys.path.insert(0, ".")
from auspex.devhost import pin_host_defaults  # noqa: E402

pin_host_defaults()
from auspex.config import Settings  # noqa: E402

IP = "34.187.179.218"


async def main() -> None:
    s = Settings()
    async with httpx.AsyncClient(timeout=30) as http:
        r = await http.get("https://api.abuseipdb.com/api/v2/check",
                           params={"ipAddress": IP, "maxAgeInDays": 90},
                           headers={"Key": s.abuseipdb_api_key, "Accept": "application/json"})
        d = r.json().get("data", {})
        print(f"AbuseIPDB {r.status_code}:")
        for k in ("abuseConfidenceScore", "totalReports", "isWhitelisted", "isPublic",
                  "usageType", "isp", "domain", "countryCode", "hostnames", "isTor"):
            print(f"   {k} = {d.get(k)!r}")
        headers = {"X-OTX-API-KEY": s.otx_api_key} if getattr(s, "otx_api_key", "") else {}
        r = await http.get(f"https://otx.alienvault.com/api/v1/indicators/IPv4/{IP}/general",
                           headers=headers)
        d = r.json()
        print(f"OTX general {r.status_code}:")
        for k in ("asn", "country_name", "country_code", "city", "reputation"):
            print(f"   {k} = {d.get(k)!r}")
        print(f"   pulse_info.count = {d.get('pulse_info', {}).get('count')!r}")


asyncio.run(main())
