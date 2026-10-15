"""S30 (D-061): enterable_workspaces is the only answer to "may this person
enter, and as what" — explicit memberships within reach, plus provider-wide
grants into unrestricted clients, explicit winning."""

import asyncio

import pytest
from _tenancy import add_membership, build_mssp, drop_orgs, make_org, make_workspace

from auspex.db import create_pool
from auspex.tenancy.access import enterable_workspaces, landing
from auspex.tenancy.admin import provision_dev_user

PREFIX = "t-s30-access"


@pytest.fixture
async def world(client, settings):
    pool = await create_pool(settings.database_url, retries=2, delay=0.5)
    await drop_orgs(pool, PREFIX)
    try:
        yield pool, await build_mssp(pool, PREFIX)
    finally:
        await drop_orgs(pool, PREFIX)
        await pool.close()


async def _roles(pool, user_id):
    return {ws: (a.role, a.via) for ws, a in (await enterable_workspaces(pool, user_id)).items()}


async def test_a_provider_wide_admin_reaches_unrestricted_clients_only(world):
    pool, m = world
    assert await _roles(pool, m.p_admin) == {
        m.provider_ws: ("admin", "membership"),
        m.client1_ws: ("admin", "provider_wide"),
    }


async def test_a_grant_reaches_a_client_created_after_it(world):
    pool, m = world
    late = await make_org(pool, f"{PREFIX}-client3", "client", parent=m.provider)
    late_ws = await make_workspace(pool, f"{PREFIX}-client3", late)
    assert (await _roles(pool, m.p_admin))[late_ws] == ("admin", "provider_wide")


async def test_an_explicit_membership_wins_over_the_grant(world):
    pool, m = world
    await add_membership(pool, m.client1_ws, m.p_admin, "viewer")
    assert (await _roles(pool, m.p_admin))[m.client1_ws] == ("viewer", "membership")


async def test_an_explicit_membership_reaches_a_restricted_client(world):
    pool, m = world
    await add_membership(pool, m.client2_ws, m.p_analyst, "analyst")
    assert (await _roles(pool, m.p_analyst))[m.client2_ws] == ("analyst", "membership")


async def test_without_a_grant_an_mssp_analyst_enters_only_the_provider(world):
    pool, m = world
    assert await _roles(pool, m.p_analyst) == {m.provider_ws: ("analyst", "membership")}


@pytest.mark.parametrize("target", ["client2_ws", "provider_ws", "direct_ws"])
async def test_a_stray_membership_outside_reach_grants_nothing(world, target):
    """The write path refuses these rows (Task 3); the read side must not trust
    that it did."""
    pool, m = world
    await add_membership(pool, getattr(m, target), m.c1_user, "admin")
    assert await _roles(pool, m.c1_user) == {m.client1_ws: ("analyst", "membership")}


async def test_a_stray_grant_on_a_client_workspace_reaches_nothing_more(world):
    pool, m = world
    await pool.execute(
        "UPDATE memberships SET provider_wide = true WHERE user_id = $1", m.c1_user)
    assert await _roles(pool, m.c1_user) == {m.client1_ws: ("analyst", "membership")}


async def test_a_grant_held_by_someone_homed_elsewhere_reaches_nothing(world):
    pool, m = world
    await add_membership(pool, m.provider_ws, m.d_user, "admin", provider_wide=True)
    assert await _roles(pool, m.d_user) == {m.direct_ws: ("admin", "membership")}


async def test_nothing_reaches_the_deployment_workspace(world):
    pool, m = world
    ws = await pool.fetchval("SELECT id FROM workspaces WHERE name = '__deployment__'")
    if ws is None:
        ws = await pool.fetchval(
            "INSERT INTO workspaces (name) VALUES ('__deployment__') RETURNING id")
    await add_membership(pool, ws, m.d_user, "admin")
    try:
        assert ws not in await enterable_workspaces(pool, m.d_user)
    finally:
        await pool.execute(
            "DELETE FROM memberships WHERE workspace_id = $1 AND user_id = $2", ws, m.d_user)


async def test_only_narrows_to_one_workspace(world):
    pool, m = world
    assert set(await enterable_workspaces(pool, m.p_admin, only=m.client1_ws)) == {m.client1_ws}
    assert await enterable_workspaces(pool, m.p_admin, only=m.client2_ws) == {}


async def test_landing_prefers_the_home_organization(world):
    pool, m = world
    assert (await landing(pool, m.p_admin)).workspace_id == m.provider_ws
    await pool.execute("DELETE FROM memberships WHERE user_id = $1", m.c1_user)
    assert await landing(pool, m.c1_user) is None


async def test_an_email_in_another_case_is_the_same_person(world):
    pool, _ = world
    first = await provision_dev_user(pool, f"case@{PREFIX}.auspex.dev",
                                     workspace_name=f"{PREFIX}-dev")
    again = await provision_dev_user(pool, f"  CASE@{PREFIX.upper()}.auspex.dev ",
                                     workspace_name=f"{PREFIX}-dev")
    assert again == first


async def test_two_first_logins_at_once_make_one_person(world):
    pool, _ = world
    email = f"race@{PREFIX}.auspex.dev"
    ids = await asyncio.gather(*[
        provision_dev_user(pool, email, workspace_name=f"{PREFIX}-dev") for _ in range(4)
    ])
    assert len(set(ids)) == 1
    assert await pool.fetchval(
        "SELECT count(*) FROM memberships WHERE user_id = $1", ids[0]) == 1


async def test_a_new_dev_user_is_an_analyst_in_its_workspace(world):
    pool, _ = world
    user = await provision_dev_user(pool, f"new@{PREFIX}.auspex.dev",
                                    workspace_name=f"{PREFIX}-dev")
    access = await landing(pool, user)
    assert (access.workspace_name, access.role, access.org_kind) == (
        f"{PREFIX}-dev", "analyst", "direct")


async def test_no_one_is_provisioned_into_the_deployment_workspace(world):
    pool, _ = world
    with pytest.raises(ValueError, match="reserved"):
        await provision_dev_user(pool, f"x@{PREFIX}.auspex.dev", workspace_name="__deployment__")
