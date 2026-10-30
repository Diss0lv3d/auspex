"""The one way into a workspace (D-061; S30 design §2): a sign-in lands, a
switch names its target, and both are checked against enterable_workspaces and
recorded as `workspace.enter` in the workspace entered."""

from uuid import UUID

from auspex.tenancy import audit
from auspex.tenancy.access import Access, enterable_workspaces, landing


class NoAccess(Exception):
    """The person may not enter the workspace asked for, or any workspace."""


async def enter(pool, user_id: UUID, *, via: str, workspace_id: UUID | None = None) -> Access:
    if via not in ("login", "switch") or (via == "switch" and workspace_id is None):
        raise ValueError(f"unknown entry {via!r}")
    # B-025: one transaction, the person's row locked FOR SHARE first. A rehome
    # (`rehome_person` locks it FOR NO KEY UPDATE) waits for this entry, so the
    # access decided here and the home stamped on its event are the same moment's.
    async with pool.acquire() as conn, conn.transaction():
        home = await conn.fetchval(
            "SELECT home_org_id FROM users WHERE id = $1 FOR SHARE", user_id)
        if via == "login":
            access = await landing(conn, user_id)
        else:
            access = (await enterable_workspaces(conn, user_id, only=workspace_id)).get(
                workspace_id)
        if access is None:
            raise NoAccess
        await audit.record(conn, workspace_id=access.workspace_id, action="workspace.enter",
                           actor=audit.person(user_id, home), details={"via": via})
    return access
