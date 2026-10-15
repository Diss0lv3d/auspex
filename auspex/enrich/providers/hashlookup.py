"""CIRCL hashlookup — keyless, always-on (probe §2).

GET https://hashlookup.circl.lu/lookup/{md5|sha1|sha256}/{hash}.
This is a known-GOOD file database (NSRL and friends): a hit means "known
distributed file" — weak benign evidence, weighted by `hashlookup:trust`
(0–100). A 404 miss is NO signal (unknown ≠ bad). `parents[]` is huge and
never stored.
"""

import httpx

from auspex.classify.observables import Observable, ObservableType
from auspex.enrich.providers.base import Provider, parse_json, raise_for_status
from auspex.enrich.types import ProviderSignal, VerdictLabel

BASE_URL = "https://hashlookup.circl.lu"

_PATH_BY_TYPE = {
    ObservableType.MD5: "md5",
    ObservableType.SHA1: "sha1",
    ObservableType.SHA256: "sha256",
}

# Known-file is weak benign evidence even at full trust: plenty of malware
# ships inside "known distributed" archives. Cap well below provider verdicts.
_MAX_CONFIDENCE = 0.5


class Hashlookup(Provider):
    name = "CIRCL hashlookup"
    region = "global"
    accepts = frozenset(_PATH_BY_TYPE)

    async def lookup(
        self, client: httpx.AsyncClient, observable: Observable
    ) -> ProviderSignal | None:
        path = _PATH_BY_TYPE[observable.type]
        resp = await client.get(f"{BASE_URL}/lookup/{path}/{observable.value}")
        if resp.status_code == 404:
            return None  # "Non existing ..." — unknown file, no signal
        raise_for_status(self.name, resp)  # incl. 400 bad-hex = our bug, not theirs
        data = parse_json(self.name, resp)

        trust = data.get("hashlookup:trust")
        trust = trust if isinstance(trust, int) else 0
        product = data.get("ProductCode")
        product = product if isinstance(product, dict) else {}
        label_bits = [str(v) for v in (data.get("FileName"), product.get("ProductName")) if v]
        described = label_bits[0] if label_bits else "unnamed known file"
        return ProviderSignal(
            provider=self.name,
            label=VerdictLabel.BENIGN,
            confidence=round(_MAX_CONFIDENCE * min(trust, 100) / 100, 3),
            summary=f"known distributed file: {described} (trust {trust}/100)",
            evidence={
                "trust": trust,
                "file_name": data.get("FileName"),
                "product": product.get("ProductName"),
                "db": data.get("db"),
            },
        )
