"""Who may enter which workspace, and as what (D-061; S30 design §2).

`enterable_workspaces` is ONE statement and the only code that answers it:
token mints, every request's re-check (auspex/auth.py) and every cross-client
view go through it. Its two parts:

- an explicit membership counts only where the workspace's organization is the
  person's home organization or a client of it. The write path refuses
  anything else (auspex/tenancy/admin.py); this side re-checks, so a stray row
  grants nothing;
- a `provider_wide` membership on a workspace of the person's own PROVIDER
  home organization reaches every workspace of that provider's clients that
  are not `restricted`.

An explicit membership's role wins over a grant on the same workspace (the more
specific statement). `__deployment__` has no organization, so nothing reaches it.
"""

from dataclasses import dataclass
from uuid import UUID

ROLES = ("admin", "analyst", "viewer")


@dataclass(frozen=True)
class Access:
    workspace_id: UUID
    workspace_name: str
    region: str
    org_id: UUID
    org_name: str
    org_kind: str
    role: str
    via: str  # "membership" | "provider_wide"


_ENTERABLE_SQL = """
WITH me AS (
    SELECT home_org_id FROM users WHERE id = $1
),
reach AS (
    SELECT o.id FROM organizations o, me
     WHERE o.id = me.home_org_id OR o.parent_id = me.home_org_id
),
explicit AS (
    SELECT m.workspace_id, m.role, 'membership'::text AS via
      FROM memberships m
      JOIN workspaces w ON w.id = m.workspace_id
     WHERE m.user_id = $1
       AND w.org_id IN (SELECT id FROM reach)
),
granted AS (
    SELECT cw.id AS workspace_id, m.role, 'provider_wide'::text AS via
      FROM memberships m
      JOIN me ON true
      JOIN workspaces pw ON pw.id = m.workspace_id
      JOIN organizations po ON po.id = pw.org_id
      JOIN organizations co ON co.parent_id = po.id
      JOIN workspaces cw ON cw.org_id = co.id
     WHERE m.user_id = $1
       AND m.provider_wide
       AND po.kind = 'provider'
       AND po.id = me.home_org_id
       AND co.kind = 'client'
       AND NOT co.restricted
),
everything AS (
    SELECT * FROM explicit
    UNION ALL
    SELECT * FROM granted
)
SELECT DISTINCT ON (e.workspace_id)
       e.workspace_id, e.role, e.via,
       w.name AS workspace_name, w.region,
       o.id AS org_id, o.name AS org_name, o.kind AS org_kind
  FROM everything e
  JOIN workspaces w ON w.id = e.workspace_id
  JOIN organizations o ON o.id = w.org_id
 WHERE $2::uuid IS NULL OR e.workspace_id = $2::uuid
 ORDER BY e.workspace_id,
          (e.via = 'membership') DESC,
          CASE e.role WHEN 'admin' THEN 3 WHEN 'analyst' THEN 2 ELSE 1 END DESC
"""


async def enterable_workspaces(
    db, user_id: UUID, *, only: UUID | None = None
) -> dict[UUID, Access]:
    rows = await db.fetch(_ENTERABLE_SQL, user_id, only)
    return {
        r["workspace_id"]: Access(
            workspace_id=r["workspace_id"],
            workspace_name=r["workspace_name"],
            region=r["region"],
            org_id=r["org_id"],
            org_name=r["org_name"],
            org_kind=r["org_kind"],
            role=r["role"],
            via=r["via"],
        )
        for r in rows
    }


async def home_org(db, user_id: UUID) -> UUID | None:
    return await db.fetchval("SELECT home_org_id FROM users WHERE id = $1", user_id)


async def user_by_email(db, email: str) -> UUID | None:
    return await db.fetchval(
        "SELECT id FROM users WHERE lower(email) = lower($1)", email.strip()
    )


async def landing(db, user_id: UUID) -> Access | None:
    """Where a sign-in lands: the home organization's workspaces first, then the
    rest, each group by name. None when the person may enter nothing."""
    home = await home_org(db, user_id)
    if home is None:
        return None
    reachable = sorted(
        (await enterable_workspaces(db, user_id)).values(),
        key=lambda a: (a.org_id != home, a.workspace_name),
    )
    return reachable[0] if reachable else None
