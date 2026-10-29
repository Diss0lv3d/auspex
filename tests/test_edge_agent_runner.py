"""S33 Task 6: the Edge Agent (D-062). It claims a job, fetches the package by hash and
re-hashes it, runs the command in a subprocess with a timeout and only the secrets the
config names, and posts the answer. Driven here against the real app (the TestClient is
its HTTP client) and the real `auspex_sdk.run` subprocess."""

import io
import json
import os
import shutil
import zipfile
from pathlib import Path

import pytest
from _tenancy import build_mssp, drop_orgs
from auspex_sdk.build import build
from auspex_sdk.package import build_zip

from auspex.connectors.catalogue import register
from auspex.connectors.kinds import CONNECTOR_TEST
from auspex.db import create_pool
from auspex.edge import agent as agent_mod
from auspex.edge.agent import Agent
from auspex.edge.secrets import SecretsFileRefused, load
from auspex.edge_api.agents import create_agent, enroll
from auspex.integrations.store import create
from auspex.jobs.queue import enqueue
from auspex.tenancy.audit import person

PREFIX = "t-s33-runner"
EXAMPLE = Path(__file__).resolve().parents[1] / "examples/connectors/mock_siem"
FIXTURE = EXAMPLE / "fixtures" / "test.json"
TOKEN = "example-token-placeholder"  # noqa: S105 -- a placeholder, not a credential
CONFIG = {"base_url": "https://siem.example.test", "api_token": "secret:siem_token"}


def _files(zip_bytes: bytes) -> dict[str, bytes]:
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as z:
        return {n: z.read(n) for n in z.namelist()}


@pytest.fixture(scope="module")
def reference_zip(tmp_path_factory) -> bytes:
    copy = tmp_path_factory.mktemp("ref") / "c"
    shutil.copytree(EXAMPLE / "yaml", copy, ignore=shutil.ignore_patterns("dist", "__pycache__"))
    zip_path, _ = build(copy)
    return zip_path.read_bytes()


def _variant(reference_zip: bytes, tail: str) -> bytes:
    """The reference package with its `check` replaced: another package, another hash."""
    files = _files(reference_zip)
    files["mock_siem.py"] = files["mock_siem.py"] + tail.encode()
    return build_zip(files)


@pytest.fixture
async def site(client, settings, reference_zip, tmp_path, monkeypatch):
    monkeypatch.setenv("AUSPEX_SDK_RUN_FIXTURE", str(FIXTURE))
    pool = await create_pool(settings.database_url, retries=2, delay=0.5)
    await drop_orgs(pool, PREFIX)
    try:
        m = await build_mssp(pool, PREFIX)
        admin = person(m.d_user, m.direct)
        agent_row, enrollment = await create_agent(pool, workspace_id=m.direct_ws,
                                                   actor=admin, name="runner")
        _, credential = await enroll(pool, enrollment)
        secrets = tmp_path / "secrets.json"
        secrets.write_text(json.dumps({"siem_token": TOKEN}))
        secrets.chmod(0o600)

        async def integration(data: bytes, prefix: str):
            entry = await register(pool, workspace_id=m.direct_ws, data=data,
                                   registered_by=m.d_user, offered_to_clients=False)
            integ = await create(pool, workspace_id=m.direct_ws, actor=admin, name=prefix,
                                 prefix=prefix, content_hash=entry.content_hash,
                                 config=CONFIG, agent_id=agent_row.id)
            job, _ = await enqueue(
                pool, workspace_id=m.direct_ws, kind=CONNECTOR_TEST,
                idempotency_key=f"test:{prefix}", integration_id=integ.id,
                payload={"integration_id": str(integ.id), "content_hash": entry.content_hash,
                         "command": "test", "config": CONFIG, "arguments": {}})
            return job, entry.content_hash

        agent = Agent(http=client, credential=credential, secrets_path=secrets,
                      cache_dir=tmp_path / "cache", wait=0)
        yield pool, agent, integration, secrets, reference_zip
    finally:
        await drop_orgs(pool, PREFIX)
        await pool.close()


async def _row(pool, job_id):
    return await pool.fetchrow("SELECT status, result, last_error FROM jobs WHERE id = $1",
                               job_id)


async def test_a_claimed_test_runs_and_its_answer_is_posted(site):
    pool, agent, integration, _, reference_zip = site
    job, _ = await integration(reference_zip, "siteok")
    assert agent.run_once() is True
    row = await _row(pool, job.id)
    assert row["status"] == "done", row["last_error"]
    assert json.loads(row["result"]) == {"ok": True, "detail": "reachable"}
    assert agent.run_once() is False  # nothing left


async def test_a_package_whose_bytes_do_not_hash_to_the_job_s_is_never_run(site):
    """Review Focus 3: the catalogue's bytes are swapped under the pinned hash; the agent
    re-hashes, refuses, and the job fails naming both hashes."""
    pool, agent, integration, _, reference_zip = site
    job, pinned = await integration(reference_zip, "sitetamper")
    other = _variant(reference_zip, "\n# tampered\n")
    await pool.execute("UPDATE connector_packages SET package = $2 WHERE content_hash = $1",
                       pinned, other)
    assert agent.run_once() is True
    row = await _row(pool, job.id)
    assert row["status"] == "failed"
    assert pinned in row["last_error"] and "hashes to" in row["last_error"]


def test_a_secrets_file_others_can_read_is_refused(tmp_path):
    loose = tmp_path / "secrets.json"
    loose.write_text("{}")
    loose.chmod(0o644)
    with pytest.raises(SecretsFileRefused, match="0600"):
        load(loose)


async def test_the_secrets_file_is_read_again_for_each_job(site):
    pool, agent, integration, secrets, reference_zip = site
    secrets.write_text(json.dumps({}))  # rotated away: the next job must see it
    job, _ = await integration(reference_zip, "siterotate")
    agent.run_once()
    row = await _row(pool, job.id)
    assert row["status"] == "failed" and "siem_token" in row["last_error"]


async def test_a_command_over_its_time_is_stopped_and_said_so(site, monkeypatch):
    pool, agent, integration, _, reference_zip = site
    monkeypatch.setattr(agent_mod, "COMMAND_TIMEOUTS", {"test": 1})
    slow = _variant(reference_zip, "\nimport time\n\ndef check(ctx):\n    time.sleep(5)\n")
    job, _ = await integration(slow, "siteslow")
    agent.run_once()
    row = await _row(pool, job.id)
    assert row["status"] == "failed" and "1 s" in row["last_error"]


async def test_a_connector_that_leaks_its_secret_sends_nothing_of_it(site, caplog):
    """Review Focus 4: printed, logged and raised; neither the job row nor the agent's
    own log carries the value."""
    pool, agent, integration, _, reference_zip = site
    leaky = _variant(reference_zip, (
        "\n\ndef check(ctx):\n"
        "    print('token', str(ctx.config.api_token))\n"
        "    raise RuntimeError('leaked ' + str(ctx.config.api_token))\n"))
    job, _ = await integration(leaky, "siteleak")
    agent.run_once()
    row = await _row(pool, job.id)
    assert row["status"] == "failed"
    assert TOKEN not in row["last_error"] and "[secret:api_token]" in row["last_error"]
    assert TOKEN not in caplog.text
    assert os.stat(agent.cache_dir).st_mode & 0o077 == 0


def test_the_agent_will_not_start_without_its_url_and_secrets_file():
    from auspex.edge.__main__ import main

    assert main({}) == 2


def test_a_half_unpacked_package_left_by_a_crash_is_never_reused(tmp_path, reference_zip):
    """Self-review (S33): a crash mid-unpack leaves `<hash>.partial`; the next unpack
    must start clean, so a stray file there never joins the package that runs."""
    from auspex_sdk.package import read_package

    from auspex.edge import cache

    _, digest, _ = read_package(reference_zip)
    staging = (tmp_path / cache._SAFE.sub("_", digest)).with_suffix(".partial")
    staging.mkdir(parents=True)
    (staging / "planted.py").write_text("raise SystemExit('ran')\n")
    target = cache.unpack(tmp_path, digest, reference_zip)
    assert not (target / "planted.py").exists()


async def test_a_result_post_that_fails_once_is_retried_not_dropped(site, monkeypatch):
    """PR #51 review #1: the agent dropped an answer whose post failed, leaving the job
    to the heartbeat. It retries with backoff, and the job ends."""
    import httpx

    pool, agent, integration, _, reference_zip = site
    job, _ = await integration(reference_zip, "siteretry")
    real_post, failures = agent.http.post, []

    def flaky(url, *args, **kwargs):
        if "/result" in url and not failures:
            failures.append(url)
            raise httpx.ConnectError("transient")
        return real_post(url, *args, **kwargs)

    monkeypatch.setattr(agent.http, "post", flaky)
    monkeypatch.setattr(agent_mod, "RETRY_DELAYS", (0, 0, 0))
    assert agent.run_once() is True
    assert failures and (await _row(pool, job.id))["status"] == "done"
    assert agent.running == set()  # the heartbeat names nothing once it is posted


def test_the_heartbeat_names_the_job_being_run(site, monkeypatch):
    _, agent, _, _, _ = site
    sent = []
    monkeypatch.setattr(agent.http, "post",
                        lambda url, **kw: sent.append(kw.get("json")) or
                        type("R", (), {"raise_for_status": lambda self: None})())
    agent.running.add("00000000-0000-0000-0000-000000000001")
    agent.heartbeat()
    assert sent == [{"jobs": ["00000000-0000-0000-0000-000000000001"]}]


async def test_a_secret_echoed_in_a_result_never_reaches_the_job_row(site):
    """PR #51 review #3, end to end: the connector answers with its secret in the
    result's text; the job row (what the admin is shown) holds only the placeholder."""
    pool, agent, integration, _, reference_zip = site
    echo = _variant(reference_zip, (
        "\n\ndef check(ctx):\n"
        "    return {'ok': False, 'detail': 'SIEM said: bad key ' + str(ctx.config.api_token)}\n"))
    job, _ = await integration(echo, "siteecho")
    agent.run_once()
    row = await _row(pool, job.id)
    assert row["status"] == "done"
    assert TOKEN not in row["result"] and "[secret:api_token]" in row["result"]


def test_the_agent_scrubs_every_string_of_a_result_again():
    answer = agent_mod._answer(json.dumps({"result": {
        "ok": False, "detail": f"x {TOKEN}", f"k{TOKEN}": [f"y{TOKEN}"]}}), 0,
        {"siem_token": TOKEN})
    assert TOKEN not in json.dumps(answer)


async def test_a_package_that_is_not_a_zip_is_answered_not_fatal(site):
    """PR #51 review #5: `PackageError` from `read_package` escaped `run_once` and
    killed the agent. It is answered as an error in words."""
    pool, agent, integration, _, reference_zip = site
    job, pinned = await integration(reference_zip, "sitebad")
    await pool.execute("UPDATE connector_packages SET package = $2 WHERE content_hash = $1",
                       pinned, b"not a zip at all")
    assert agent.run_once() is True
    row = await _row(pool, job.id)
    assert row["status"] == "failed" and "package" in row["last_error"]


async def test_a_full_disk_is_answered_not_fatal(site, monkeypatch):
    pool, agent, integration, _, reference_zip = site
    job, _ = await integration(reference_zip, "sitedisk")

    def full(*args, **kwargs):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(agent_mod.cache, "unpack", full)
    assert agent.run_once() is True
    row = await _row(pool, job.id)
    assert row["status"] == "failed" and "No space left" in row["last_error"]


def test_the_loop_survives_any_one_job_s_failure(monkeypatch, tmp_path):
    """`main()` caught only httpx errors; any other escape ended the agent."""
    from auspex.edge import __main__ as entry

    calls = []

    class Boom:
        def __init__(self, **kw):
            pass

        def heartbeat(self):
            pass

        def run_once(self):
            calls.append(1)
            if len(calls) == 1:
                raise RuntimeError("one bad job")
            raise KeyboardInterrupt

    secrets = tmp_path / "s.json"
    secrets.write_text("{}")
    secrets.chmod(0o600)
    monkeypatch.setattr(entry, "Agent", Boom)
    monkeypatch.setattr(entry, "credential", lambda *a, **k: "apa_x")
    monkeypatch.setattr(entry.time, "sleep", lambda s: None)
    assert entry.main({"AUSPEX_URL": "http://127.0.0.1:9", "AUSPEX_SECRETS_FILE": str(secrets),
                       "AUSPEX_AGENT_CACHE": str(tmp_path / "c")}) == 0
    assert len(calls) == 2
