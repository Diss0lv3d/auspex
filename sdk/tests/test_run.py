"""S33 Task 5: `python -I -m auspex_sdk.run <package_dir>`, the one way a connector
command runs, for the Edge Agent and the harness alike. It reads one JSON job on stdin,
writes one JSON answer on stdout, and nothing the connector prints or logs crosses
unredacted (D-063)."""

import json
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest
from auspex_sdk.build import build
from auspex_sdk.harness import run_command

ROOT = Path(__file__).resolve().parents[2]
EXAMPLE = ROOT / "examples" / "connectors" / "mock_siem"
FIXTURE = EXAMPLE / "fixtures" / "test.json"
TOKEN = "example-token-placeholder"  # noqa: S105 -- a placeholder, not a credential
CONFIG = {"base_url": "https://siem.example.test", "api_token": "secret:siem_token"}


@pytest.fixture(scope="module")
def package_dir(tmp_path_factory) -> Path:
    src = tmp_path_factory.mktemp("src") / "c"
    shutil.copytree(EXAMPLE / "yaml", src, ignore=shutil.ignore_patterns("dist", "__pycache__"))
    zip_path, _ = build(src)
    out = tmp_path_factory.mktemp("pkg")
    with zipfile.ZipFile(zip_path) as z:
        z.extractall(out)
    return out


def _run(package_dir: Path, job: dict, *, fixture: Path | None = FIXTURE, extra=None):
    env = {"PATH": "/usr/bin:/bin"}
    if fixture is not None:
        env["AUSPEX_SDK_RUN_FIXTURE"] = str(fixture)
    proc = subprocess.run(  # noqa: S603 -- our own interpreter and module
        [sys.executable, "-I", "-m", "auspex_sdk.run", str(package_dir)],
        input=json.dumps(job), capture_output=True, text=True, timeout=30, env=env,
        cwd=extra or package_dir)
    return proc.returncode, json.loads(proc.stdout), proc.stderr


def test_a_test_command_answers_as_the_harness_does(package_dir, tmp_path):
    code, out, _ = _run(package_dir, {"command": "test", "config": CONFIG,
                                      "secrets": {"siem_token": TOKEN}, "arguments": {}})
    assert code == 0, out
    harness = run_command(EXAMPLE / "yaml", "test",
                          config={"base_url": CONFIG["base_url"]},
                          secrets={"api_token": TOKEN}, fixture=FIXTURE)
    assert out["result"] == harness == {"ok": True, "detail": "reachable"}


def test_a_secret_the_agent_lacks_fails_naming_it_never_a_value(package_dir):
    code, out, _ = _run(package_dir, {"command": "test", "config": CONFIG, "secrets": {},
                                      "arguments": {}})
    assert code == 1
    assert out["error"] == "secret 'siem_token' (for config.api_token) is not on this agent"


def test_what_a_handler_prints_or_raises_is_redacted(package_dir, tmp_path):
    """Review Focus 4: a connector that prints its secret, or puts it in an exception,
    still sends nothing but the placeholder across."""
    leaky = tmp_path / "leaky"
    shutil.copytree(package_dir, leaky)
    module = leaky / "mock_siem.py"
    module.write_text(module.read_text() + (
        "\n\ndef _leak(ctx):\n"
        "    print('token is', str(ctx.config.api_token))\n"
        "    ctx.log.warning('again %s', str(ctx.config.api_token))\n"
        "    raise RuntimeError('failed with ' + str(ctx.config.api_token))\n"
        "check = _leak\n"))
    code, out, err = _run(leaky, {"command": "test", "config": CONFIG,
                                  "secrets": {"siem_token": TOKEN}, "arguments": {}})
    assert code == 1
    text = json.dumps(out) + err
    assert TOKEN not in text
    assert "[secret:api_token]" in out["error"]
    assert any("[secret:api_token]" in line for line in out["log"])


@pytest.mark.parametrize("stdin", ["not json", "[]", '{"command": "test"}'])
def test_a_malformed_job_is_refused_in_words(package_dir, stdin):
    proc = subprocess.run(  # noqa: S603
        [sys.executable, "-I", "-m", "auspex_sdk.run", str(package_dir)], input=stdin,
        capture_output=True, text=True, timeout=30, env={"PATH": "/usr/bin:/bin"})
    assert proc.returncode == 1
    assert json.loads(proc.stdout)["error"].startswith("job:")


def test_a_secret_echoed_in_the_result_is_redacted(package_dir, tmp_path):
    """PR #51 review #3: logs and errors were redacted, the result was not, so a test
    answering "401 for key <secret>" stored and showed it."""
    echo = tmp_path / "echo"
    shutil.copytree(package_dir, echo)
    module = echo / "mock_siem.py"
    module.write_text(module.read_text() + (
        "\n\ndef _echo(ctx):\n"
        "    return {'ok': False, 'detail': '401 for key ' + str(ctx.config.api_token)}\n"
        "check = _echo\n"))
    code, out, _ = _run(echo, {"command": "test", "config": CONFIG,
                               "secrets": {"siem_token": TOKEN}, "arguments": {}})
    assert code == 0
    assert TOKEN not in json.dumps(out)
    assert out["result"] == {"ok": False, "detail": "401 for key [secret:api_token]"}
