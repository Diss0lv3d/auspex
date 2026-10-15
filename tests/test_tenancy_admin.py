"""S30 (D-061; design §3): every tenancy write goes through admin.py, under
one set of rules, and records its audit event in the same transaction."""

import asyncio

import pytest
from _tenancy import add_membership, build_mssp, drop_orgs, make_user

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


async def _deployment_ws(pool):
    from auspex.llm.scorecard import DEPLOYMENT_WORKSPACE

    await pool.execute(
        "INSERT INTO workspaces (name, org_id) VALUES ($1, NULL) ON CONFLICT (name) DO NOTHING",
        DEPLOYMENT_WORKSPACE)
    return await pool.fetchval("SELECT id FROM workspaces WHERE name = $1", DEPLOYMENT_WORKSPACE)


async def test_the_deployment_workspace_takes_no_member(world):
    pool, _ = world
    dep = await _deployment_ws(pool)
    before = await pool.fetchval("SELECT count(*) FROM memberships WHERE workspace_id = $1", dep)
    with pytest.raises(admin.Refused, match="reserved"):
        await admin.set_member(pool, workspace="__deployment__", email=f"dep@{DOMAIN}",
                               role="viewer")
    with pytest.raises(admin.Refused, match="reserved"):
        await admin.add_member(pool, workspace_id=dep, email=f"dep2@{DOMAIN}", role="viewer",
                               actor=CLI)
    assert await pool.fetchval(
        "SELECT count(*) FROM memberships WHERE workspace_id = $1", dep) == before
    assert await pool.fetchval(
        "SELECT count(*) FROM users WHERE email = ANY($1::text[])",
        [f"dep@{DOMAIN}", f"dep2@{DOMAIN}"]) == 0


async def test_an_admin_homed_in_another_org_leaves_nothing(world):
    pool, m = world
    outsider = await pool.fetchval("SELECT email FROM users WHERE id = $1", m.c2_user)
    name = f"{PREFIX}-outsider"
    with pytest.raises(admin.Conflict, match="another organization"):
        await admin.create_org(pool, kind="direct", name=name, workspace=name,
                               admin_email=outsider)
    assert await pool.fetchval("SELECT count(*) FROM organizations WHERE name = $1", name) == 0
    assert await pool.fetchval("SELECT count(*) FROM workspaces WHERE name = $1", name) == 0
    assert await pool.fetchval(
        "SELECT count(*) FROM audit_events WHERE details->>'organization' = $1", name) == 0


async def test_create_client_admin_must_belong_to_the_provider(world):
    pool, m = world
    provider = await pool.fetchval("SELECT name FROM organizations WHERE id = $1", m.provider)
    insider = await pool.fetchval("SELECT email FROM users WHERE id = $1", m.p_analyst)
    _, ws = await admin.create_client(pool, provider=provider, name=f"{PREFIX}-c10",
                                      workspace=f"{PREFIX}-c10", admin_email=insider)
    assert (await enterable_workspaces(pool, m.p_analyst))[ws].role == "admin"
    outsider = await pool.fetchval("SELECT email FROM users WHERE id = $1", m.c2_user)
    with pytest.raises(admin.Conflict):
        await admin.create_client(pool, provider=provider, name=f"{PREFIX}-c11",
                                  workspace=f"{PREFIX}-c11", admin_email=outsider)
    assert await pool.fetchval(
        "SELECT count(*) FROM organizations WHERE name = $1", f"{PREFIX}-c11") == 0
    assert await pool.fetchval(
        "SELECT count(*) FROM workspaces WHERE name = $1", f"{PREFIX}-c11") == 0
    assert await pool.fetchval(
        "SELECT count(*) FROM audit_events WHERE details->>'organization' = $1",
        f"{PREFIX}-c11") == 0


async def test_dev_provisioning_into_a_new_workspace_audits_its_creation_once(world):
    pool, _ = world
    name = f"{PREFIX}-devws"
    first = await admin.provision_dev_user(pool, f"d1@{DOMAIN}", workspace_name=name)
    second = await admin.provision_dev_user(pool, f"d2@{DOMAIN}", workspace_name=name)
    ws_id, ws_org = (lambda r: (r["id"], r["org_id"]))(
        await pool.fetchrow("SELECT id, org_id FROM workspaces WHERE name = $1", name))
    for user in (first, second):
        assert await pool.fetchval("SELECT home_org_id FROM users WHERE id = $1", user) == ws_org
    actions = await _actions(pool, ws_id)
    assert actions.count("org.create") == 1 and actions.count("workspace.create") == 1
    assert actions.count("membership.add") == 2


async def test_a_role_change_through_set_member_keeps_the_grant(world):
    pool, m = world
    p_email = await pool.fetchval("SELECT email FROM users WHERE id = $1", m.p_analyst)
    ws_name = await pool.fetchval("SELECT name FROM workspaces WHERE id = $1", m.provider_ws)
    await admin.set_member(pool, workspace=ws_name, email=p_email, role="analyst",
                           provider_wide=True)
    await admin.set_member(pool, workspace=ws_name, email=p_email, role="admin")
    assert m.client1_ws in await enterable_workspaces(pool, m.p_analyst)
    await admin.set_member(pool, workspace=ws_name, email=p_email, role="admin",
                           provider_wide=False)
    assert m.client1_ws not in await enterable_workspaces(pool, m.p_analyst)


# --- F1 (S30 final review): membership writes re-check the actor, one at a time ---


async def _second_admin(pool, m):
    """direct_ws gets a second admin beside d_user; both are homed in direct."""
    other = await make_user(pool, f"d2-admin@{DOMAIN}", m.direct)
    await add_membership(pool, m.direct_ws, other, "admin")
    return other


async def _admins(pool, workspace_id):
    return await pool.fetchval(
        "SELECT count(*) FROM memberships WHERE workspace_id = $1 AND role = 'admin'",
        workspace_id)


def _one_done_one_refused(results):
    refused = [r for r in results if isinstance(r, admin.Refused)]
    assert len(refused) == 1 and results.count(None) == 1, results
    assert str(refused[0]) == admin.NOT_AN_ADMIN


async def test_two_admins_removing_each_other_at_once_leave_one(world):
    pool, m = world
    a1, a2 = m.d_user, await _second_admin(pool, m)
    results = await asyncio.gather(
        admin.remove_member(pool, workspace_id=m.direct_ws, user_id=a2,
                            actor=person(a1, m.direct)),
        admin.remove_member(pool, workspace_id=m.direct_ws, user_id=a1,
                            actor=person(a2, m.direct)),
        return_exceptions=True,
    )
    _one_done_one_refused(results)
    assert await _admins(pool, m.direct_ws) == 1
    assert (await _actions(pool, m.direct_ws)).count("membership.remove") == 1


async def test_two_admins_demoting_each_other_at_once_leave_one(world):
    pool, m = world
    a1, a2 = m.d_user, await _second_admin(pool, m)
    results = await asyncio.gather(
        admin.change_member(pool, workspace_id=m.direct_ws, user_id=a2,
                            actor=person(a1, m.direct), role="analyst"),
        admin.change_member(pool, workspace_id=m.direct_ws, user_id=a1,
                            actor=person(a2, m.direct), role="analyst"),
        return_exceptions=True,
    )
    _one_done_one_refused(results)
    assert await _admins(pool, m.direct_ws) == 1
    assert (await _actions(pool, m.direct_ws)).count("membership.role") == 1


async def test_a_removed_admin_is_refused_on_the_next_write(world):
    pool, m = world
    a1, a2 = m.d_user, await _second_admin(pool, m)
    await admin.remove_member(pool, workspace_id=m.direct_ws, user_id=a2,
                              actor=person(a1, m.direct))
    gone = person(a2, m.direct)
    for write in (
        lambda: admin.remove_member(pool, workspace_id=m.direct_ws, user_id=a1, actor=gone),
        lambda: admin.change_member(pool, workspace_id=m.direct_ws, user_id=a1, actor=gone,
                                    role="viewer"),
        lambda: admin.add_member(pool, workspace_id=m.direct_ws, email=f"late@{DOMAIN}",
                                 role="viewer", actor=gone),
    ):
        with pytest.raises(admin.Refused, match="current admin"):
            await write()
    assert await _admins(pool, m.direct_ws) == 1
    assert await pool.fetchval(
        "SELECT count(*) FROM users WHERE email = $1", f"late@{DOMAIN}") == 0


async def test_a_demoted_admin_is_refused_and_the_cli_still_acts(world):
    pool, m = world
    await pool.execute("UPDATE memberships SET role = 'analyst' WHERE user_id = $1", m.d_user)
    with pytest.raises(admin.Refused, match="current admin"):
        await admin.add_member(pool, workspace_id=m.direct_ws, email=f"nope@{DOMAIN}",
                               role="viewer", actor=person(m.d_user, m.direct))
    ws_name = await pool.fetchval("SELECT name FROM workspaces WHERE id = $1", m.direct_ws)
    d_email = await pool.fetchval("SELECT email FROM users WHERE id = $1", m.d_user)
    await admin.set_member(pool, workspace=ws_name, email=d_email, role="admin")  # recovery
    assert await _admins(pool, m.direct_ws) == 1


async def test_a_membership_write_waits_for_the_workspace_then_re_checks(world):
    """The lock comes BEFORE the re-check: a write that starts while another is
    in flight waits for it, then sees what it committed."""
    pool, m = world
    a1, a2 = m.d_user, await _second_admin(pool, m)
    write = None
    async with pool.acquire() as conn:
        tx = conn.transaction()
        await tx.start()
        try:
            await conn.execute(
                "SELECT 1 FROM workspaces WHERE id = $1 FOR NO KEY UPDATE", m.direct_ws)
            write = asyncio.create_task(admin.remove_member(
                pool, workspace_id=m.direct_ws, user_id=a1, actor=person(a2, m.direct)))
            done, _ = await asyncio.wait({write}, timeout=0.5)
            assert not done, "the write did not wait for the workspace"
            await conn.execute(
                "DELETE FROM memberships WHERE workspace_id = $1 AND user_id = $2",
                m.direct_ws, a2)
            await tx.commit()
        except BaseException:
            await tx.rollback()
            raise
    with pytest.raises(admin.Refused, match="current admin"):
        await write
    assert await _admins(pool, m.direct_ws) == 1
