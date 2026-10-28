"""The connector catalogue (S32, spec decision 3; Review Focus 5): content-hashed packages
per workspace, a provider's packages offered to its clients, first-party packages in the
reserved `__deployment__` workspace, and the one listing every workspace sees."""

import json
from pathlib import Path
from uuid import uuid4

import pytest
from _tenancy import build_mssp, drop_orgs, make_org, make_workspace
from auspex_sdk.package import build_zip

from auspex.connectors import __main__ as cli
from auspex.connectors.catalogue import RegistrationRefused, available, register
from auspex.db import create_pool
from auspex.llm.scorecard import DEPLOYMENT_WORKSPACE, ensure_deployment_workspace

PREFIX = "t-s32-cat"
# Every package id these tests register starts here, so first-party rows (which every
# workspace in the dev DB lists) are deleted however a test ends.
ID_PREFIX = "tcat."


def package(connector_id: str, version: str = "1.0.0", *, body: bytes = b"") -> bytes:
    manifest = {
        "schema_version": 1,
        "id": connector_id,
        "version": version,
        "name": "Catalogue test",
        "description": "A package the catalogue tests register.",
        "commands": {"test": {"handler": "pkg.handlers:test"}},
    }
    return build_zip({
        "manifest.json": json.dumps(manifest).encode(),
        "pkg/__init__.py": b"",
        "pkg/handlers.py": body,
    })


def fresh_id() -> str:
    return f"{ID_PREFIX}c{uuid4().hex[:12]}"


async def _drop_test_packages(pool) -> None:
    await pool.execute(
        "DELETE FROM connector_packages WHERE starts_with(connector_id, $1)", ID_PREFIX
    )


@pytest.fixture
async def world(client, settings):
    pool = await create_pool(settings.database_url, retries=2, delay=0.5)
    await drop_orgs(pool, PREFIX)
    await _drop_test_packages(pool)
    try:
        yield pool, await build_mssp(pool, PREFIX)
    finally:
        await _drop_test_packages(pool)
        await drop_orgs(pool, PREFIX)
        await pool.close()


async def _deployment(pool):
    return await ensure_deployment_workspace(pool)


def _listed(entries, connector_id):
    return [e for e in entries if e.connector_id == connector_id]


async def test_a_registered_package_is_listed_in_its_own_workspace(world):
    pool, m = world
    cid = fresh_id()
    entry = await register(pool, workspace_id=m.direct_ws, data=package(cid),
                           registered_by=m.d_user, offered_to_clients=False)
    assert entry.connector_id == cid and entry.version == "1.0.0"
    assert entry.content_hash.startswith("sha256:")
    assert entry.manifest["id"] == cid
    assert not entry.first_party and not entry.offered_to_clients
    (listed,) = _listed(await available(pool, workspace_id=m.direct_ws), cid)
    assert listed.source == "own" and listed.id == entry.id


async def test_the_same_hash_twice_is_the_same_entry(world):
    pool, m = world
    data = package(fresh_id())
    a = await register(pool, workspace_id=m.direct_ws, data=data, registered_by=m.d_user,
                       offered_to_clients=False)
    b = await register(pool, workspace_id=m.direct_ws, data=data, registered_by=None,
                       offered_to_clients=False)
    assert a.id == b.id
    count = await pool.fetchval(
        "SELECT count(*) FROM connector_packages WHERE workspace_id = $1 AND content_hash = $2",
        m.direct_ws, a.content_hash,
    )
    assert count == 1


async def test_the_same_id_and_version_with_another_hash_is_refused(world):
    pool, m = world
    cid = fresh_id()
    await register(pool, workspace_id=m.direct_ws, data=package(cid), registered_by=m.d_user,
                   offered_to_clients=False)
    with pytest.raises(RegistrationRefused, match="bump the version") as e:
        await register(pool, workspace_id=m.direct_ws, data=package(cid, body=b"# changed\n"),
                       registered_by=m.d_user, offered_to_clients=False)
    assert "bump the version" in e.value.reason
    bumped = await register(pool, workspace_id=m.direct_ws,
                            data=package(cid, "1.0.1", body=b"# changed\n"),
                            registered_by=m.d_user, offered_to_clients=False)
    assert bumped.version == "1.0.1"


async def test_a_bad_package_is_refused_with_the_member_named(world):
    pool, m = world
    bad = build_zip({"manifest.json": b"{}", "../x.py": b""})
    with pytest.raises(RegistrationRefused, match=r"\.\./x\.py"):
        await register(pool, workspace_id=m.direct_ws, data=bad, registered_by=m.d_user,
                       offered_to_clients=False)


async def test_only_a_provider_may_offer_to_clients(world):
    """Review Focus 5: refused in a client or direct workspace, whoever the caller is."""
    pool, m = world
    for ws in (m.client1_ws, m.client2_ws, m.direct_ws):
        cid = fresh_id()
        with pytest.raises(RegistrationRefused, match="provider") as e:
            await register(pool, workspace_id=ws, data=package(cid), registered_by=m.p_admin,
                           offered_to_clients=True)
        assert "provider" in e.value.reason
        assert not await pool.fetchval(
            "SELECT count(*) FROM connector_packages WHERE connector_id = $1", cid)


async def test_an_offered_package_reaches_only_that_providers_clients(world):
    pool, m = world
    other = await make_org(pool, f"{PREFIX}-other", "provider")
    other_client = await make_org(pool, f"{PREFIX}-other-client", "client", parent=other)
    other_client_ws = await make_workspace(pool, f"{PREFIX}-other-client", other_client)
    cid = fresh_id()
    offered = await register(pool, workspace_id=m.provider_ws, data=package(cid),
                             registered_by=m.p_admin, offered_to_clients=True)
    assert offered.offered_to_clients
    (own,) = _listed(await available(pool, workspace_id=m.provider_ws), cid)
    assert own.source == "own"
    # The restricted client2 lists it too: a listing is code, not access to its data.
    for ws in (m.client1_ws, m.client2_ws):
        (listed,) = _listed(await available(pool, workspace_id=ws), cid)
        assert listed.source == "provider" and listed.id == offered.id
    for ws in (other_client_ws, m.direct_ws):
        assert not _listed(await available(pool, workspace_id=ws), cid)


async def test_a_providers_unoffered_package_stays_its_own(world):
    pool, m = world
    cid = fresh_id()
    await register(pool, workspace_id=m.provider_ws, data=package(cid),
                   registered_by=m.p_admin, offered_to_clients=False)
    for ws in (m.client1_ws, m.client2_ws):
        assert not _listed(await available(pool, workspace_id=ws), cid)


async def test_a_foreign_workspaces_own_package_is_never_listed(world):
    pool, m = world
    cid = fresh_id()
    await register(pool, workspace_id=m.client1_ws, data=package(cid),
                   registered_by=m.c1_user, offered_to_clients=False)
    assert _listed(await available(pool, workspace_id=m.client1_ws), cid)
    for ws in (m.client2_ws, m.provider_ws, m.direct_ws):
        assert not _listed(await available(pool, workspace_id=ws), cid)


async def test_a_first_party_package_is_listed_everywhere(world):
    pool, m = world
    cid = fresh_id()
    deployment = await _deployment(pool)
    entry = await register(pool, workspace_id=deployment, data=package(cid),
                           registered_by=None, offered_to_clients=False, first_party=True)
    assert entry.first_party
    for ws in (m.provider_ws, m.client1_ws, m.client2_ws, m.direct_ws):
        (listed,) = _listed(await available(pool, workspace_id=ws), cid)
        assert listed.source == "first_party" and listed.id == entry.id


async def test_first_party_lives_only_in_the_deployment_workspace(world):
    pool, m = world
    with pytest.raises(RegistrationRefused, match=DEPLOYMENT_WORKSPACE):
        await register(pool, workspace_id=m.direct_ws, data=package(fresh_id()),
                       registered_by=m.d_user, offered_to_clients=False, first_party=True)
    with pytest.raises(RegistrationRefused, match=DEPLOYMENT_WORKSPACE):
        await register(pool, workspace_id=await _deployment(pool), data=package(fresh_id()),
                       registered_by=None, offered_to_clients=False, first_party=False)


async def test_an_id_a_first_party_package_uses_is_refused(world):
    """Review Focus 5: even for a workspace's admin."""
    pool, m = world
    cid = fresh_id()
    await register(pool, workspace_id=await _deployment(pool), data=package(cid),
                   registered_by=None, offered_to_clients=False, first_party=True)
    for ws, admin in ((m.direct_ws, m.d_user), (m.provider_ws, m.p_admin)):
        with pytest.raises(RegistrationRefused, match="first-party"):
            await register(pool, workspace_id=ws, data=package(cid, "9.0.0"),
                           registered_by=admin, offered_to_clients=False)


async def test_an_id_the_provider_offers_is_refused_in_its_client(world):
    pool, m = world
    cid = fresh_id()
    await register(pool, workspace_id=m.provider_ws, data=package(cid),
                   registered_by=m.p_admin, offered_to_clients=True)
    with pytest.raises(RegistrationRefused, match="provider offers"):
        await register(pool, workspace_id=m.client1_ws, data=package(cid, "2.0.0"),
                       registered_by=m.c1_user, offered_to_clients=False)
    # A direct customer is nobody's client: the id is free there.
    await register(pool, workspace_id=m.direct_ws, data=package(cid, "2.0.0"),
                   registered_by=m.d_user, offered_to_clients=False)


async def test_the_cli_registers_first_party_into_the_deployment_workspace(
        world, tmp_path, capsys):
    pool, m = world
    cid = fresh_id()
    zip_path = tmp_path / "pkg.zip"
    zip_path.write_bytes(package(cid))
    assert await cli.run(["register", "--first-party", str(zip_path)]) == 0
    out = capsys.readouterr().out
    assert cid in out and "sha256:" in out
    row = await pool.fetchrow(
        "SELECT w.name, cp.first_party, cp.offered_to_clients FROM connector_packages cp"
        " JOIN workspaces w ON w.id = cp.workspace_id WHERE cp.connector_id = $1", cid)
    assert row["name"] == DEPLOYMENT_WORKSPACE and row["first_party"]
    assert not row["offered_to_clients"]
    (listed,) = _listed(await available(pool, workspace_id=m.client1_ws), cid)
    assert listed.source == "first_party"


async def test_the_cli_refuses_a_bad_package(world, tmp_path, capsys):
    zip_path = tmp_path / "bad.zip"
    zip_path.write_bytes(b"not a zip")
    assert await cli.run(["register", "--first-party", str(zip_path)]) == 1
    assert "refused" in capsys.readouterr().err


async def test_the_cli_refuses_an_oversize_file_before_reading_it(tmp_path, capsys,
                                                                  monkeypatch):
    """S32 final review: the size is checked from the file system, so a mistyped path to
    a huge file is never read into memory."""
    from auspex_sdk.package import MAX_PACKAGE_BYTES

    big = tmp_path / "big.zip"
    with big.open("wb") as f:
        f.truncate(MAX_PACKAGE_BYTES + 1)
    read = []
    monkeypatch.setattr(Path, "read_bytes", lambda self: read.append(self) or b"")
    assert await cli.run(["register", "--first-party", str(big)]) == 1
    assert read == []
    assert "over the" in capsys.readouterr().err


async def test_the_same_package_registered_twice_at_once_is_one_entry(world):
    """S32 final review: two identical uploads racing (a double click, a retry) both get
    the one entry; neither is told to bump the version."""
    import asyncio

    pool, m = world
    for _ in range(10):
        data = package(fresh_id())
        entries = await asyncio.gather(*(
            register(pool, workspace_id=m.direct_ws, data=data, registered_by=m.d_user,
                     offered_to_clients=False) for _ in range(4)))
        assert len({e.id for e in entries}) == 1


# Fix round 1 (ruling c1): one listing per connector id, first-party > provider > own. A
# shadowed package stays registered; the later registration is never refused over it.


async def test_a_provider_offer_shadows_a_clients_own_package_of_that_id(world):
    pool, m = world
    cid = fresh_id()
    own = await register(pool, workspace_id=m.client1_ws, data=package(cid),
                         registered_by=m.c1_user, offered_to_clients=False)
    offered = await register(pool, workspace_id=m.provider_ws, data=package(cid, "2.0.0"),
                             registered_by=m.p_admin, offered_to_clients=True)
    listed = _listed(await available(pool, workspace_id=m.client1_ws), cid)
    assert [(e.id, e.source) for e in listed] == [(offered.id, "provider")]
    assert await pool.fetchval("SELECT 1 FROM connector_packages WHERE id = $1", own.id)


async def test_a_first_party_package_shadows_own_and_provider_packages_of_that_id(world):
    pool, m = world
    cid = fresh_id()
    await register(pool, workspace_id=m.client1_ws, data=package(cid),
                   registered_by=m.c1_user, offered_to_clients=False)
    await register(pool, workspace_id=m.provider_ws, data=package(cid, "2.0.0"),
                   registered_by=m.p_admin, offered_to_clients=True)
    await register(pool, workspace_id=m.direct_ws, data=package(cid, "3.0.0"),
                   registered_by=m.d_user, offered_to_clients=False)
    first = await register(pool, workspace_id=await _deployment(pool),
                           data=package(cid, "4.0.0"), registered_by=None,
                           offered_to_clients=False, first_party=True)
    for ws in (m.client1_ws, m.client2_ws, m.provider_ws, m.direct_ws):
        listed = _listed(await available(pool, workspace_id=ws), cid)
        assert [(e.id, e.source) for e in listed] == [(first.id, "first_party")]
    assert await pool.fetchval(
        "SELECT count(*) FROM connector_packages WHERE connector_id = $1", cid) == 4


@pytest.mark.parametrize("escape", ["\\u0000", "\\ud800"], ids=["nul", "lone-surrogate"])
async def test_a_manifest_postgres_cannot_store_is_refused_in_words(world, escape):
    """PR #43 review #6 (reproduced, docs/probes/2026-10-28-s33-pr43-6-7-8.md): a NUL
    or a lone surrogate escaped in manifest.json passed json.loads and the manifest
    rules, then Postgres refused the jsonb and the route answered 500."""
    pool, m = world
    raw = json.dumps({"schema_version": 1, "id": fresh_id(), "version": "1.0.0",
                      "name": "x", "description": "PLACEHOLDER",
                      "commands": {"test": {"handler": "pkg.handlers:test"}}}
                     ).replace("PLACEHOLDER", f"re{escape}pro")
    data = build_zip({"manifest.json": raw.encode(), "pkg/__init__.py": b"",
                      "pkg/handlers.py": b""})
    with pytest.raises(RegistrationRefused, match="cannot be stored"):
        await register(pool, workspace_id=m.direct_ws, data=data, registered_by=m.d_user,
                       offered_to_clients=False)
