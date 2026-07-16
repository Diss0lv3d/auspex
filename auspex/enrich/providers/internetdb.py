"""Shodan InternetDB — keyless, always-on (probe §1).

GET https://internetdb.shodan.io/{ip} (IPv4 + IPv6, both live-verified).
404 = "No information available" = no data, never an error. The signal is
exposure CONTEXT: `vulns[]` non-empty leans suspicious; open ports alone are
label-UNKNOWN context (a mail server is not malicious for having port 25 open).
"""

import httpx

from auspex.classify.observables import Observable, ObservableType
from auspex.enrich.providers.base import Provider, parse_json, raise_for_status
from auspex.enrich.types import ProviderSignal, VerdictLabel

BASE_URL = "https://internetdb.shodan.io"


class InternetDB(Provider):
    name = "InternetDB"
    accepts = frozenset({ObservableType.IPV4, ObservableType.IPV6})

    async def lookup(
        self, client: httpx.AsyncClient, observable: Observable
    ) -> ProviderSignal | None:
        resp = await client.get(f"{BASE_URL}/{observable.value}")
        if resp.status_code == 404:
            return None  # "No information available" — data, not failure
        raise_for_status(self.name, resp)
        data = parse_json(self.name, resp)

        ports = [p for p in data.get("ports", []) if isinstance(p, int)]
        vulns = [str(v) for v in data.get("vulns", [])]
        hostnames = [str(h) for h in data.get("hostnames", [])]
        tags = [str(t) for t in data.get("tags", [])]
        evidence = {"ports": ports, "vulns": vulns, "hostnames": hostnames[:5], "tags": tags}

        if vulns:
            shown = ", ".join(sorted(vulns)[:5])
            more = f" (+{len(vulns) - 5} more)" if len(vulns) > 5 else ""
            return ProviderSignal(
                provider=self.name,
                label=VerdictLabel.SUSPICIOUS,
                confidence=0.4,
                summary=f"exposed host with known vulnerabilities: {shown}{more}",
                evidence=evidence,
            )
        if not ports:
            return None  # 200 with nothing useful — treat as no data
        summary = f"open ports {', '.join(str(p) for p in sorted(ports))}"
        if hostnames:
            summary += f" · hostnames {', '.join(hostnames[:3])}"
        if tags:
            summary += f" · tags {', '.join(tags)}"
        return ProviderSignal(
            provider=self.name,
            label=VerdictLabel.UNKNOWN,
            confidence=0.0,
            summary=summary,
            evidence=evidence,
        )
