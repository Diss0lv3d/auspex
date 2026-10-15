"""The one way into a workspace (D-061; S30 design §2): a sign-in lands, a
switch names its target, and both are checked against enterable_workspaces and
recorded as `workspace.enter` in the workspace entered."""

from uuid import UUID

from auspex.tenancy import audit
from auspex.tenancy.access import Access, enterable_workspaces, home_org, landing


class NoAccess(Exception):
    """The person may not enter the workspace asked for, or any workspace."""


async def enter(pool, user_id: UUID, *, via: str, workspace_id: UUID | None = None) -> Access:
    if via == "login":
        access = await landing(pool, user_id)
    elif via == "switch" and workspace_id is not None:
        access = (await enterable_workspaces(pool, user_id, only=workspace_id)).get(workspace_id)
    else:
        raise ValueError(f"unknown entry {via!r}")
    if access is None:
        raise NoAccess
    home = await home_org(pool, user_id)
    async with pool.acquire() as conn:
        await audit.record(conn, workspace_id=access.workspace_id, action="workspace.enter",
                           actor=audit.person(user_id, home), details={"via": via})
    return access
