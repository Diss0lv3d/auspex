"""S30 call 1: organizations are created only by the CLI, run in the app
container as `python -m auspex.tenancy …`. Driven in-process here."""

import asyncio

import pytest
from _tenancy import drop_orgs, token

from auspex.config import get_settings
from auspex.db import create_pool
from auspex.tenancy import __main__ as cli
from auspex.tenancy.__main__ import main

PREFIX = "t-s30-cli"


@pytest.fixture
def clean(client, settings):
    async def _drop():
        pool = await create_pool(settings.database_url, retries=2, delay=0.5)
        try:
            await drop_orgs(pool, PREFIX)
        finally:
            await pool.close()

    asyncio.run(_drop())
    yield
    asyncio.run(_drop())


def _storage(monkeypatch, region: str) -> None:
    """A deployment that stores its data in `region` (D-069), as the CLI sees
    it, whatever this machine's STORAGE_REGION says. A copy of the suite's
    settings, so its signing key stays the same."""
    stored = get_settings().model_copy(update={"storage_region": region})
    monkeypatch.setattr(cli, "get_settings", lambda: stored)


@pytest.fixture
def ksa_storage(monkeypatch):
    _storage(monkeypatch, "ksa")


@pytest.fixture
def global_storage(monkeypatch):
    _storage(monkeypatch, "global")


def test_the_cli_builds_an_mssp_and_lists_it_without_emails(clean, ksa_storage, capsys):
    assert main(["create-org", "--kind", "provider", "--name", f"{PREFIX}-mssp",
                 "--workspace", f"{PREFIX}-mssp", "--admin", f"boss@{PREFIX}.auspex.dev"]) == 0
    assert main(["create-client", "--provider", f"{PREFIX}-mssp", "--name", f"{PREFIX}-bank",
                 "--workspace", f"{PREFIX}-bank", "--region", "ksa", "--restricted"]) == 0
    assert main(["set-member", "--workspace", f"{PREFIX}-mssp", "--email",
                 f"ops@{PREFIX}.auspex.dev", "--role", "analyst", "--provider-wide"]) == 0
    assert main(["set-restricted", "--client", f"{PREFIX}-bank", "off"]) == 0
    assert main(["remove-member", "--workspace", f"{PREFIX}-mssp", "--email",
                 f"ops@{PREFIX}.auspex.dev"]) == 0
    capsys.readouterr()
    assert main(["list"]) == 0
    listed = capsys.readouterr().out
    assert f"{PREFIX}-bank" in listed and "ksa" in listed
    assert "@" not in listed


def test_a_refusal_exits_1_with_the_reason(clean, capsys):
    assert main(["create-client", "--provider", f"{PREFIX}-nope", "--name", f"{PREFIX}-x",
                 "--workspace", f"{PREFIX}-x"]) == 1
    assert "No organization named" in capsys.readouterr().err


def test_a_ksa_workspace_is_refused_where_the_deployment_stores_elsewhere(
        clean, global_storage, capsys):
    """D-069: on a deployment that stores in `global`."""
    assert main(["create-org", "--kind", "provider", "--name", f"{PREFIX}-mssp",
                 "--workspace", f"{PREFIX}-mssp", "--admin", f"boss@{PREFIX}.auspex.dev",
                 "--region", "ksa"]) == 1
    assert "ksa" in capsys.readouterr().err
    assert main(["create-org", "--kind", "provider", "--name", f"{PREFIX}-mssp",
                 "--workspace", f"{PREFIX}-mssp", "--admin", f"boss@{PREFIX}.auspex.dev"]) == 0
    assert main(["create-client", "--provider", f"{PREFIX}-mssp", "--name", f"{PREFIX}-bank",
                 "--workspace", f"{PREFIX}-bank", "--region", "ksa"]) == 1
    assert "ksa" in capsys.readouterr().err
    assert main(["list"]) == 0
    assert f"{PREFIX}-bank" not in capsys.readouterr().out


def test_an_unknown_region_is_refused_before_anything_is_written(clean, capsys):
    with pytest.raises(SystemExit):
        main(["create-org", "--kind", "direct", "--name", f"{PREFIX}-r",
              "--workspace", f"{PREFIX}-r", "--admin", f"r@{PREFIX}.auspex.dev",
              "--region", "mars"])


def test_provider_wide_survives_a_role_change_until_withdrawn(clean):
    async def granted():
        pool = await create_pool(get_settings().database_url, retries=2, delay=0.5)
        try:
            return await pool.fetchval(
                "SELECT m.provider_wide FROM memberships m JOIN users u ON u.id = m.user_id"
                " WHERE lower(u.email) = $1", f"pw@{PREFIX}.auspex.dev")
        finally:
            await pool.close()

    ws, email = f"{PREFIX}-pw", f"pw@{PREFIX}.auspex.dev"
    assert main(["create-org", "--kind", "provider", "--name", ws, "--workspace", ws,
                 "--admin", f"boss@{PREFIX}.auspex.dev"]) == 0
    assert main(["set-member", "--workspace", ws, "--email", email, "--role", "analyst",
                 "--provider-wide"]) == 0
    assert main(["set-member", "--workspace", ws, "--email", email, "--role", "admin"]) == 0
    assert asyncio.run(granted()) is True
    assert main(["set-member", "--workspace", ws, "--email", email, "--role", "admin",
                 "--no-provider-wide"]) == 0
    assert asyncio.run(granted()) is False


async def _person_and_workspace(email: str, workspace: str):
    pool = await create_pool(get_settings().database_url, retries=2, delay=0.5)
    try:
        return (await pool.fetchval("SELECT id FROM users WHERE lower(email) = $1", email),
                await pool.fetchval("SELECT id FROM workspaces WHERE name = $1", workspace))
    finally:
        await pool.close()


def test_a_person_claimed_by_another_organization_is_recovered_by_the_cli(
        clean, client, settings, capsys):
    """F2 (S30 final review): A's admin adds B's future CEO over the API, which
    homes the CEO in A. B (and the CLI) get 409 until A removes the membership
    and the CLI rehomes the person; then B's admin adds them."""
    a, b = f"{PREFIX}-a", f"{PREFIX}-b"
    ceo = f"ceo@{PREFIX}-b.auspex.dev"
    assert main(["create-org", "--kind", "direct", "--name", a, "--workspace", a,
                 "--admin", f"admin@{PREFIX}-a.auspex.dev"]) == 0
    a_admin, a_ws = asyncio.run(_person_and_workspace(f"admin@{PREFIX}-a.auspex.dev", a))
    claimed = client.post("/api/workspace/members", json={"email": ceo, "role": "viewer"},
                          headers=token(settings, a_admin, a_ws))
    assert claimed.status_code == 201, claimed.text
    ceo_id = claimed.json()["user_id"]
    capsys.readouterr()

    assert main(["create-org", "--kind", "direct", "--name", b, "--workspace", b,
                 "--admin", ceo]) == 1
    assert "another organization" in capsys.readouterr().err
    assert main(["create-org", "--kind", "direct", "--name", b, "--workspace", b,
                 "--admin", f"boss@{PREFIX}-b.auspex.dev"]) == 0
    b_admin, b_ws = asyncio.run(_person_and_workspace(f"boss@{PREFIX}-b.auspex.dev", b))
    b_headers = token(settings, b_admin, b_ws)
    blocked = client.post("/api/workspace/members", json={"email": ceo, "role": "admin"},
                          headers=b_headers)
    assert blocked.status_code == 409
    assert main(["set-member", "--workspace", b, "--email", ceo, "--role", "admin"]) == 1
    capsys.readouterr()

    assert main(["rehome-person", "--email", ceo, "--org", b]) == 1  # A still holds them
    held = capsys.readouterr()
    assert "1 membership" in held.err and "@" not in held.out + held.err
    assert client.delete(f"/api/workspace/members/{ceo_id}",
                         headers=token(settings, a_admin, a_ws)).status_code == 200
    assert main(["rehome-person", "--email", ceo, "--org", b]) == 0
    done = capsys.readouterr()
    assert b in done.out and a in done.out  # the operator, not B's admins, reads the old home
    assert "@" not in done.out + done.err

    added = client.post("/api/workspace/members", json={"email": ceo, "role": "admin"},
                        headers=b_headers)
    assert added.status_code == 201, added.text
    assert added.json()["user_id"] == ceo_id
    events = client.get("/api/audit", headers=b_headers).json()["events"]
    rehomed = [e for e in events if e["action"] == "person.rehome"]
    assert len(rehomed) == 1
    assert rehomed[0]["details"] == {"to": b}
    assert a not in str(events)  # B-021: nothing B's admins read names A
    assert rehomed[0]["subject"]["user_id"] == ceo_id
    assert rehomed[0]["actor"]["kind"] == "cli"
