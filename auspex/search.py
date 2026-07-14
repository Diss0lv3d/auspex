"""OpenSearch connectivity — our own container (D-009), never SARA's cluster.

S1 scope: readiness ping only. No index creation here; index/mapping work
starts in S6 with a mapping probe first.
"""

import httpx

from auspex.config import Settings

PING_TIMEOUT_SECONDS = 5.0


async def opensearch_ping(settings: Settings) -> dict:
    """Hit the cluster root; returns {"ok": bool, "detail": str}."""
    auth = None
    if settings.opensearch_user and settings.opensearch_pass:
        auth = (settings.opensearch_user, settings.opensearch_pass)
    try:
        async with httpx.AsyncClient(timeout=PING_TIMEOUT_SECONDS, auth=auth) as client:
            resp = await client.get(settings.opensearch_url)
        if resp.status_code == 200:
            version = resp.json().get("version", {}).get("number", "unknown")
            return {"ok": True, "detail": f"opensearch {version}"}
        return {"ok": False, "detail": f"status {resp.status_code}"}
    except httpx.HTTPError as err:
        return {"ok": False, "detail": f"unreachable: {err.__class__.__name__}"}
