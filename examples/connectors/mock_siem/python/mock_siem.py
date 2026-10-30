"""example.mock_siem 1.0.0: the reference connector, written Python-first (S32).

The mock SIEM is a made-up alert service. It exists only as the recorded exchanges in
../fixtures, so every command here runs offline through `auspex-sdk run`. Copy this file as a
starting point for your own connector; ../yaml is the same connector as YAML plus plain
handlers, and both build to the same manifest.

The mock API, all under `{base_url}` and authenticated with a bearer token:

    GET  /api/health                         -> {"status": "ok"}
    GET  /api/alerts?cursor=<c>&limit=<n>    -> {"alerts": [...], "next": "<c>" | null}
    GET  /api/alerts/<id>                    -> {"id", "status": "open" | "closed", ...}
    POST /api/alerts/<id>/close  (and /reopen) -> the alert, with its new status
"""

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Annotated

from auspex_sdk.runtime import (
    Context,
    OutputField,
    Secret,
    Tls,
    Undo,
    Url,
    action,
    command,
    connector,
)


# --- config ----------------------------------------------------------------------------------
# The string in each Annotated is the label the admin sees. A field with no default is required.
# `hosts` is the only place the connector may send requests: the host of the admin's base_url.
@connector(
    id="example.mock_siem",
    version="1.0.0",
    name="Mock SIEM",
    description="A mock SIEM: pulls its alerts and closes them. The reference connector.",
    hosts=("https://{base_url}",),
)
@dataclass(frozen=True)
class Config:
    base_url: Annotated[Url, "SIEM URL"]
    api_token: Annotated[Secret, "API token"]
    tls: Annotated[Tls, "TLS"] = Tls()  # Tls() is "verify"; there is no way to switch it off


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
@command("test")
def check(ctx: Context) -> dict:
    """The admin's "Test connection" button."""
    r = _get(ctx, "/api/health")
    ok = r.status_code == 200 and r.json().get("status") == "ok"
    return {"ok": ok, "detail": "reachable" if ok else f"health check returned {r.status_code}"}


@command("fetch")
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


@action(
    "close_alert",
    risk="write",
    dry_run=close_dry_run,
    undo=Undo(
        handler=reopen,
        restores="the alert's open status",
        cannot_restore=("the closing note, if the SIEM keeps one",),
    ),
    observe=closed_count,
    targets="alert_id",  # the parameter that names the alert in the SIEM
    output=(OutputField("status", "string", True),),
)
def close_alert(
    ctx: Context,
    alert_id: Annotated[str, "The alert to close."],
    note: Annotated[str | None, "An optional closing note."] = None,
) -> dict:
    """Close an alert in the SIEM."""
    alert = _post(ctx, f"/api/alerts/{alert_id}/close").json()
    return {
        "would": f"closed alert {alert_id}",
        "affects": [alert_id],
        "reversible": True,
        "detail": {"status": alert["status"]},
    }
