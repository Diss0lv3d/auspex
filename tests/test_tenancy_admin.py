"""S30 (D-061; design §3): every tenancy write goes through admin.py, under
one set of rules, and records its audit event in the same transaction."""

import pytest
from _tenancy import build_mssp, drop_orgs

from auspex.db import create_pool
from auspex.tenancy import admin
from auspex.tenancy.access import enterable_workspaces
from auspex.tenancy.audit import ACTIONS, CLI, list_events, person

PREFIX = "t-s30-admin"
DOMAIN = f"{PREFIX}.auspex.dev"


@pytest.fixture
async def world(client, settings):
    pool = await create_pool(settings.database_url, retries=2, delay=0.5)
    await drop_orgs(pool, PREFIX)
    try:
        yield pool, await build_mssp(pool, PREFIX)
    finally:
        await drop_orgs(pool, PREFIX)
        await pool.close()


async def _actions(pool, workspace_id):
    return [e["action"] for e in await list_events(pool, workspace_id)]


async def test_create_org_makes_the_workspace_and_its_first_admin(world):
    pool, _ = world
    org_id, ws_id = await admin.create_org(
        pool, kind="provider", name=f"{PREFIX}-mssp2", workspace=f"{PREFIX}-mssp2",
        admin_email=f"boss@{DOMAIN}", region="ksa")
    region = await pool.fetchval("SELECT region FROM workspaces WHERE id = $1", ws_id)
    assert region == "ksa"
    boss = await pool.fetchval("SELECT id FROM users WHERE email = $1", f"boss@{DOMAIN}")
    assert (await enterable_workspaces(pool, boss))[ws_id].role == "admin"
    assert sorted(await _actions(pool, ws_id)) == [
        "membership.add", "org.create", "workspace.create"]


async def test_a_create_that_fails_halfway_leaves_nothing(world):
    pool, m = world
    taken = await pool.fetchval("SELECT name FROM workspaces WHERE id = $1", m.direct_ws)
    with pytest.raises(admin.Conflict):
        await admin.create_org(pool, kind="direct", name=f"{PREFIX}-halfway",
                               workspace=taken, admin_email=f"half@{DOMAIN}")
    assert await pool.fetchval(
        "SELECT count(*) FROM organizations WHERE name = $1", f"{PREFIX}-halfway") == 0
    assert await pool.fetchval(
        "SELECT count(*) FROM users WHERE email = $1", f"half@{DOMAIN}") == 0


async def test_create_org_refuses_a_client_and_the_reserved_name(world):
    pool, _ = world
    with pytest.raises(admin.Invalid):
        await admin.create_org(pool, kind="client", name=f"{PREFIX}-x", workspace=f"{PREFIX}-x",
                               admin_email=f"x@{DOMAIN}")
    with pytest.raises(admin.Refused):
        await admin.create_org(pool, kind="direct", name=f"{PREFIX}-y",
                               workspace="__deployment__", admin_email=f"y@{DOMAIN}")


async def test_create_client_hangs_under_a_provider_only(world):
    pool, m = world
    direct_name = await pool.fetchval("SELECT name FROM organizations WHERE id = $1", m.direct)
    with pytest.raises(admin.Invalid):
        await admin.create_client(pool, provider=direct_name, name=f"{PREFIX}-c9",
                                  workspace=f"{PREFIX}-c9")
    provider_name = await pool.fetchval("SELECT name FROM organizations WHERE id = $1", m.provider)
    _, ws = await admin.create_client(pool, provider=provider_name, name=f"{PREFIX}-c9",
                                      workspace=f"{PREFIX}-c9")
    assert ws in await enterable_workspaces(pool, m.p_admin)  # the grant reaches it


async def test_restricting_a_client_withdraws_the_grant(world):
    pool, m = world
    client1 = await pool.fetchval("SELECT name FROM organizations WHERE id = $1", m.client1)
    await admin.set_restricted(pool, client=client1, restricted=True)
    assert m.client1_ws not in await enterable_workspaces(pool, m.p_admin)
    assert "org.restricted" in await _actions(pool, m.client1_ws)
    direct = await pool.fetchval("SELECT name FROM organizations WHERE id = $1", m.direct)
    with pytest.raises(admin.Invalid):
        await admin.set_restricted(pool, client=direct, restricted=True)


async def test_a_member_is_added_only_within_reach(world):
    pool, m = world
    actor = person(m.p_admin, m.provider)
    c2_email = await pool.fetchval("SELECT email FROM users WHERE id = $1", m.c2_user)
    with pytest.raises(admin.Conflict, match="another organization"):
        await admin.add_member(pool, workspace_id=m.client1_ws, email=c2_email,
                               role="viewer", actor=actor)
    p_email = await pool.fetchval("SELECT email FROM users WHERE id = $1", m.p_analyst)
    added = await admin.add_member(pool, workspace_id=m.client1_ws, email=p_email,
                                   role="viewer", actor=actor)
    assert added == m.p_analyst
    assert "membership.add" in await _actions(pool, m.client1_ws)


async def test_a_new_email_becomes_a_person_of_the_workspaces_organization(world):
    pool, m = world
    actor = person(m.p_admin, m.provider)
    new = await admin.add_member(pool, workspace_id=m.client1_ws, email=f"fresh@{DOMAIN}",
                                 role="analyst", actor=actor)
    assert await pool.fetchval("SELECT home_org_id FROM users WHERE id = $1", new) == m.client1


async def test_adding_an_email_in_another_case_finds_the_existing_person(world):
    pool, m = world
    actor = person(m.p_admin, m.provider)
    p_email = await pool.fetchval("SELECT email FROM users WHERE id = $1", m.p_analyst)
    found = await admin.add_member(pool, workspace_id=m.client1_ws,
                                   email=f"  {p_email.upper()} ", role="viewer", actor=actor)
    assert found == m.p_analyst


async def test_adding_an_existing_member_again_is_a_conflict(world):
    pool, m = world
    c1_email = await pool.fetchval("SELECT email FROM users WHERE id = $1", m.c1_user)
    with pytest.raises(admin.Conflict, match="Already a member"):
        await admin.add_member(pool, workspace_id=m.client1_ws, email=c1_email,
                               role="admin", actor=person(m.p_admin, m.provider))


async def test_no_one_changes_their_own_membership(world):
    pool, m = world
    me = person(m.p_admin, m.provider)
    for change in (
        admin.change_member(pool, workspace_id=m.provider_ws, user_id=m.p_admin,
                            actor=me, role="viewer"),
        admin.change_member(pool, workspace_id=m.provider_ws, user_id=m.p_admin,
                            actor=me, provider_wide=False),
        admin.remove_member(pool, workspace_id=m.provider_ws, user_id=m.p_admin, actor=me),
    ):
        with pytest.raises(admin.Refused):
            await change
    p_email = await pool.fetchval("SELECT email FROM users WHERE id = $1", m.p_admin)
    with pytest.raises(admin.Refused):
        await admin.add_member(pool, workspace_id=m.client1_ws, email=p_email,
                               role="admin", actor=me)


async def test_provider_wide_only_on_a_providers_workspace(world):
    pool, m = world
    with pytest.raises(admin.Invalid):
        await admin.change_member(pool, workspace_id=m.client1_ws, user_id=m.c1_user,
                                  actor=person(m.p_admin, m.provider), provider_wide=True)
    await admin.change_member(pool, workspace_id=m.provider_ws, user_id=m.p_analyst,
                              actor=person(m.p_admin, m.provider), provider_wide=True)
    assert m.client1_ws in await enterable_workspaces(pool, m.p_analyst)
    assert "membership.provider_wide" in await _actions(pool, m.provider_ws)


async def test_role_change_and_removal_are_audited_and_404_for_a_stranger(world):
    pool, m = world
    actor = person(m.d_user, m.direct)
    await admin.add_member(pool, workspace_id=m.direct_ws, email=f"temp@{DOMAIN}",
                           role="viewer", actor=actor)
    temp = await pool.fetchval("SELECT id FROM users WHERE email = $1", f"temp@{DOMAIN}")
    await admin.change_member(pool, workspace_id=m.direct_ws, user_id=temp, actor=actor,
                              role="analyst")
    await admin.remove_member(pool, workspace_id=m.direct_ws, user_id=temp, actor=actor)
    assert {"membership.role", "membership.remove"} <= set(await _actions(pool, m.direct_ws))
    with pytest.raises(admin.NotFound):
        await admin.remove_member(pool, workspace_id=m.direct_ws, user_id=m.c1_user,
                                  actor=actor)


async def test_the_audit_names_the_actor_and_their_organization(world):
    pool, m = world
    await admin.add_member(pool, workspace_id=m.client1_ws, email=f"who@{DOMAIN}",
                           role="viewer", actor=person(m.p_admin, m.provider))
    event = (await list_events(pool, m.client1_ws))[0]
    assert event["actor"]["user_id"] == str(m.p_admin)
    assert event["actor"]["organization"] == f"{PREFIX}-provider"
    assert event["subject"]["email"] == f"who@{DOMAIN}"


async def test_audit_actions_match_the_database_check(world):
    pool, _ = world
    definition = await pool.fetchval(
        "SELECT pg_get_constraintdef(oid) FROM pg_constraint"
        " WHERE conname = 'audit_events_action_check'")
    import re
    assert set(re.findall(r"'([\w.]+)'", definition)) == ACTIONS


async def test_cli_acts_record_the_cli_as_actor(world):
    pool, _ = world
    _, ws = await admin.create_org(pool, kind="direct", name=f"{PREFIX}-viacli",
                                   workspace=f"{PREFIX}-viacli", admin_email=f"cli@{DOMAIN}",
                                   actor=CLI)
    assert {e["actor"]["kind"] for e in await list_events(pool, ws)} == {"cli"}


def test_no_code_rewrites_the_audit_trail():
    from pathlib import Path

    root = Path(__file__).resolve().parents[1] / "auspex"
    for path in root.rglob("*.py"):
        text = path.read_text().lower()
        assert "update audit_events" not in text, path
        assert "delete from audit_events" not in text, path
