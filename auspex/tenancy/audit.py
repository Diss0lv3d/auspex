"""The tenancy audit trail (D-061; S30 design §3): who entered or changed a
workspace, and of which organization. Append-only: nothing in auspex/ updates
or deletes a row (pinned by tests/test_tenancy_admin.py)."""

import json
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

# Must equal the audit_events_action_check list in auspex/migrations.py (pinned).
ACTIONS: frozenset[str] = frozenset({
    "workspace.enter",
    "membership.add",
    "membership.role",
    "membership.remove",
    "membership.provider_wide",
    "org.create",
    "org.restricted",
    "workspace.create",
    "person.rehome",
})
AUDIT_PAGE_MAX = 100


@dataclass(frozen=True)
class Actor:
    kind: str  # "user" | "cli" | "system"
    user_id: UUID | None = None
    org_id: UUID | None = None


CLI = Actor("cli")
SYSTEM = Actor("system")  # dev provisioning


def person(user_id: UUID, org_id: UUID) -> Actor:
    """A signed-in person, stamped with their home organization at write time."""
    return Actor("user", user_id, org_id)


async def record(conn, *, workspace_id: UUID, action: str, actor: Actor,
                 subject_user_id: UUID | None = None, details: dict | None = None) -> None:
    if action not in ACTIONS:
        raise ValueError(f"unknown audit action {action!r}")
    await conn.execute(
        "INSERT INTO audit_events (workspace_id, actor_kind, actor_user_id, actor_org_id,"
        " action, subject_user_id, details) VALUES ($1, $2, $3, $4, $5, $6, $7::jsonb)",
        workspace_id, actor.kind, actor.user_id, actor.org_id, action, subject_user_id,
        json.dumps(details or {}),
    )


async def list_events(db, workspace_id: UUID, *, before: datetime | None = None,
                      limit: int = 50) -> list[dict]:
    """One workspace's events, newest first. `before` pages by created_at."""
    rows = await db.fetch(
        """
        SELECT e.id, e.created_at, e.action, e.actor_kind, e.details,
               e.actor_user_id, au.email AS actor_email, au.display_name AS actor_name,
               e.actor_org_id, ao.name AS actor_org,
               e.subject_user_id, su.email AS subject_email
          FROM audit_events e
          LEFT JOIN users au ON au.id = e.actor_user_id
          LEFT JOIN organizations ao ON ao.id = e.actor_org_id
          LEFT JOIN users su ON su.id = e.subject_user_id
         WHERE e.workspace_id = $1
           AND ($2::timestamptz IS NULL OR e.created_at < $2)
         ORDER BY e.created_at DESC, e.id DESC
         LIMIT $3
        """,
        workspace_id, before, max(1, min(limit, AUDIT_PAGE_MAX)),
    )
    return [
        {
            "id": str(r["id"]),
            "at": r["created_at"].isoformat(),
            "action": r["action"],
            "actor": {
                "kind": r["actor_kind"],
                "user_id": str(r["actor_user_id"]) if r["actor_user_id"] else None,
                "email": r["actor_email"],
                "display_name": r["actor_name"],
                "organization": r["actor_org"],
            },
            "subject": {
                "user_id": str(r["subject_user_id"]) if r["subject_user_id"] else None,
                "email": r["subject_email"],
            },
            "details": json.loads(r["details"]),
        }
        for r in rows
    ]
