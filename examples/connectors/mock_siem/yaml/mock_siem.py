"""Handlers for the YAML form of example.mock_siem (S32).

connector.yaml declares everything; this file holds only the functions it names. They are the
same as in ../python/mock_siem.py without the decorators: plain functions that take `ctx` and
return a plain value. The mock SIEM exists only as the recorded exchanges in ../fixtures.
"""

import json
from datetime import UTC, datetime

from auspex_sdk.runtime import Context


def _get(ctx: Context, path: str, **params):
    return ctx.http.get(
        ctx.config.base_url.rstrip("/") + path,
        params=params or None,
        headers={"Authorization": f"Bearer {ctx.config.api_token}"},
    )


def _post(ctx: Context, path: str):
    return ctx.http.post(
        ctx.config.base_url.rstrip("/") + path,
        headers={"Authorization": f"Bearer {ctx.config.api_token}"},
    )


def _iso(epoch_seconds: int) -> str:
    """The SIEM speaks epoch seconds; the platform wants ISO-8601 UTC."""
    return datetime.fromtimestamp(epoch_seconds, tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


# --- test and fetch --------------------------------------------------------------------------
def check(ctx: Context) -> dict:
    """The admin's "Test connection" button."""
    r = _get(ctx, "/api/health")
    ok = r.status_code == 200 and r.json().get("status") == "ok"
    return {"ok": ok, "detail": "reachable" if ok else f"health check returned {r.status_code}"}


def pull(ctx: Context, cursor: str | None, limit: int) -> dict:
    """One page of alerts. Return next_cursor=None when there is nothing more."""
    params = {"limit": limit}
    if cursor:
        params["cursor"] = cursor
    page = _get(ctx, "/api/alerts", **params).json()
    items = [
        {
            "external_id": a["id"],
            "kind": "alert",
            "title": a["title"],
            "severity": a["severity"],
            "observed_at": _iso(a["created"]),
            "updated_at": _iso(a["modified"]),
            # the vendor's own record, kept as a string (64 KB at most)
            "raw": json.dumps(a, sort_keys=True),
        }
        for a in page["alerts"]
    ]
    return {"items": items, "next_cursor": page["next"]}


# --- close_alert -----------------------------------------------------------------------------
# An action is its execute function plus a dry run (required), an undo and an observe. All of
# them take the same parameters. An optional parameter you leave out arrives as None.
# connector.yaml names each one under the action.
def _alert(ctx: Context, alert_id: str) -> dict:
    return _get(ctx, f"/api/alerts/{alert_id}").json()


def close_dry_run(ctx: Context, alert_id: str, note: str | None = None) -> dict:
    """Say what execute would do, touching nothing."""
    alert = _alert(ctx, alert_id)
    return {
        "would": f"close alert {alert_id}",
        "affects": [alert_id],
        "reversible": True,
        "detail": {"status": alert["status"]},  # what it is now; execute leaves it "closed"
    }


def reopen(ctx: Context, alert_id: str, note: str | None = None) -> dict:
    """Undo: put the alert back to open."""
    alert = _post(ctx, f"/api/alerts/{alert_id}/reopen").json()
    return {
        "would": f"reopen alert {alert_id}",
        "affects": [alert_id],
        "reversible": True,
        "detail": {"status": alert["status"]},
    }


def closed_count(ctx: Context, alert_id: str, note: str | None = None) -> int:
    """Observe: how many of this action's effects landed (1 if the alert is closed, else 0).
    The platform asks after a failed execute, to learn whether it did anything."""
    return 1 if _alert(ctx, alert_id)["status"] == "closed" else 0


def close_alert(ctx: Context, alert_id: str, note: str | None = None) -> dict:
    """Close an alert in the SIEM."""
    alert = _post(ctx, f"/api/alerts/{alert_id}/close").json()
    return {
        "would": f"closed alert {alert_id}",
        "affects": [alert_id],
        "reversible": True,
        "detail": {"status": alert["status"]},
    }
