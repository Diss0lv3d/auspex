"""S34 Task 4: who may approve, per workspace and risk level (design decision 1 and 8).

The default (Hunaiza's call): `write` by an analyst or admin, `destructive` by an admin
only, provider staff included. A workspace's admin may tighten it. The check is in the
same statement that claims the proposal (D-024): a refused approver leaves the row as
it was, and an allowed one records the rule in force."""

import json
import uuid

import pytest
from _tenancy import build_mssp, drop_orgs, token

from auspex.actions.policy import DEFAULT, approvable
from auspex.db import create_pool

PREFIX = "t-s34-policy"


@pytest.fixture
async def world(client, settings):
    pool = await create_pool(settings.database_url, retries=2, delay=0.5)
    await drop_orgs(pool, PREFIX)
    try:
        yield pool, await build_mssp(pool, PREFIX)
    finally:
        await drop_orgs(pool, PREFIX)
        await pool.close()


async def _proposal(pool, ws, level: str) -> uuid.UUID:
    return await pool.fetchval(
        "INSERT INTO proposals (workspace_id, tool_name, tool_level, tool_input,"
        " spec_fingerprint, card) VALUES ($1, 'annotate_observable', $2, '{}', 'fp', '{}')"
        " RETURNING id", ws, level)


async def _analyst(pool, m):
    """An analyst in the direct workspace (build_mssp's d_user is its admin)."""
    user = await pool.fetchval("INSERT INTO users (email, home_org_id) VALUES ($1, $2)"
                               " RETURNING id", f"an-{uuid.uuid4().hex[:6]}@{PREFIX}.dev",
                               m.direct)
    await pool.execute("INSERT INTO memberships (workspace_id, user_id, role)"
                       " VALUES ($1, $2, 'analyst')", m.direct_ws, user)
    return user


def _approve(client, settings, user, ws, pid):
    return client.post(f"/api/proposals/{pid}/approve", headers=token(settings, user, ws))


async def _status(pool, pid):
    return await pool.fetchrow("SELECT status, decided_by, approval_rule FROM proposals"
                               " WHERE id = $1", pid)


def test_the_default_is_hunaiza_s_rule():
    assert DEFAULT == {"write": (("admin", "analyst"), True),
                       "destructive": (("admin",), True)}


async def test_by_default_an_analyst_approves_write_but_not_destructive(world, client,
                                                                          settings):
    """Review Focus 3: refused before the row moves, in words."""
    pool, m = world
    analyst = await _analyst(pool, m)
    write, destructive = await _proposal(pool, m.direct_ws, "write"), \
        await _proposal(pool, m.direct_ws, "destructive")
    assert _approve(client, settings, analyst, m.direct_ws, write).status_code == 200
    refused = _approve(client, settings, analyst, m.direct_ws, destructive)
    assert refused.status_code == 403 and "destructive" in refused.json()["detail"]
    row = await _status(pool, destructive)
    assert row["status"] == "pending_approval" and row["decided_by"] is None


async def test_an_admin_approves_both_and_the_rule_is_recorded(world, client, settings):
    pool, m = world
    pid = await _proposal(pool, m.direct_ws, "destructive")
    assert _approve(client, settings, m.d_user, m.direct_ws, pid).status_code == 200
    rule = json.loads((await _status(pool, pid))["approval_rule"])
    assert rule == {"risk": "destructive", "roles": ["admin"], "provider_staff": True,
                    "source": "default"}


async def test_a_tightened_policy_refuses_provider_staff(world, client, settings):
    """A client's admin may keep the MSSP's people from approving in its workspace."""
    pool, m = world
    c1_admin = await pool.fetchval("INSERT INTO users (email, home_org_id) VALUES ($1, $2)"
                                   " RETURNING id", f"c1a@{PREFIX}.dev", m.client1)
    await pool.execute("INSERT INTO memberships (workspace_id, user_id, role)"
                       " VALUES ($1, $2, 'admin')", m.client1_ws, c1_admin)
    put = client.put("/api/approval-policy", headers=token(settings, c1_admin, m.client1_ws),
                     json={"risk": "write", "roles": ["admin", "analyst"],
                           "provider_staff": False})
    assert put.status_code == 200, put.text
    pid = await _proposal(pool, m.client1_ws, "write")
    staff = _approve(client, settings, m.p_admin, m.client1_ws, pid)  # provider-wide admin
    assert staff.status_code == 403 and "provider" in staff.json()["detail"]
    assert _approve(client, settings, c1_admin, m.client1_ws, pid).status_code == 200


async def test_a_policy_never_reaches_another_workspace(world, client, settings):
    pool, m = world
    put = client.put("/api/approval-policy", headers=token(settings, m.d_user, m.direct_ws),
                     json={"risk": "write", "roles": ["admin"], "provider_staff": True})
    assert put.status_code == 200
    levels = await approvable(pool, workspace_id=m.client1_ws, role="analyst",
                              home_org_id=m.client1)
    assert "write" in levels  # client1 keeps the default
    assert client.put("/api/approval-policy", headers=token(settings, m.c1_user, m.client1_ws),
                      json={"risk": "write", "roles": ["admin"],
                            "provider_staff": True}).status_code == 403  # analyst


@pytest.mark.parametrize("body", [
    {"risk": "read", "roles": ["admin"], "provider_staff": True},
    {"risk": "write", "roles": ["owner"], "provider_staff": True},
    {"risk": "write", "roles": [], "provider_staff": True},
], ids=["read-risk", "unknown-role", "nobody"])
async def test_a_policy_that_makes_no_sense_is_refused(world, client, settings, body):
    _, m = world
    res = client.put("/api/approval-policy", headers=token(settings, m.d_user, m.direct_ws),
                     json=body)
    assert res.status_code == 422
