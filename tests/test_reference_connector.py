"""The reference connector `example.mock_siem` (S32, Task 7): the SDK path, end to end.

It is written twice, Python-first and as YAML plus handlers. Both must build to the same
manifest.json (the hashes differ: the code differs), and every command of both must run
green through the harness against the recorded mock-SIEM exchanges. Builds go to a tmp copy
so the example's own dist/ stays untouched.
"""

import shutil
import zipfile
from pathlib import Path

import pytest
from auspex_sdk.build import build
from auspex_sdk.harness import run_command
from auspex_sdk.manifest import validate_manifest
from auspex_sdk.package import read_package

EXAMPLE = Path(__file__).resolve().parent.parent / "examples" / "connectors" / "mock_siem"
FORMS = ("python", "yaml")
FIXTURES = EXAMPLE / "fixtures"

CONFIG = {"base_url": "https://siem.example.test"}
SECRETS = {"api_token": "example-token"}  # a placeholder, not a credential


@pytest.fixture
def example(tmp_path) -> Path:
    dst = tmp_path / "mock_siem"
    shutil.copytree(EXAMPLE, dst, ignore=shutil.ignore_patterns("dist", "__pycache__"))
    return dst


def manifest_bytes(zip_path: Path) -> bytes:
    with zipfile.ZipFile(zip_path) as z:
        return z.read("manifest.json")


def test_both_builds_have_the_same_manifest_and_different_hashes(example):
    (py_zip, py_hash), (ym_zip, ym_hash) = (build(example / f) for f in FORMS)
    assert manifest_bytes(py_zip) == manifest_bytes(ym_zip)
    assert py_hash != ym_hash  # the code differs, so the identity does


@pytest.mark.parametrize("form", FORMS)
def test_each_build_is_deterministic_and_valid(example, form):
    zip_path, digest = build(example / form)
    again_path, again = build(example / form)
    assert digest == again and zip_path.read_bytes() == again_path.read_bytes()
    manifest, read_digest, _files = read_package(zip_path.read_bytes())
    assert read_digest == digest
    validate_manifest(manifest)
    assert (manifest.id, manifest.version) == ("example.mock_siem", "1.0.0")
    assert manifest.hosts == ("https://{base_url}",)
    assert manifest.fetch is not None and manifest.fetch.serves_many_clients is False
    (close,) = manifest.actions
    assert close.risk == "write" and close.targets == "alert_id"
    assert close.undo is not None and close.observe


def run(form: str, command: str, fixture: str, arguments: dict | None = None):
    return run_command(
        EXAMPLE / form,
        command,
        config=CONFIG,
        secrets=SECRETS,
        fixture=FIXTURES / f"{fixture}.json",
        arguments=arguments,
    )


@pytest.mark.parametrize("form", FORMS)
def test_test_command(form):
    assert run(form, "test", "test") == {"ok": True, "detail": "reachable"}


@pytest.mark.parametrize("form", FORMS)
def test_fetch_without_and_with_a_cursor(form):
    first = run(form, "fetch", "fetch_first_page")
    assert first["next_cursor"] == "c2"
    (item,) = first["items"]
    assert item["external_id"] == "A-1001" and item["kind"] == "alert"
    assert item["observed_at"].endswith("Z") and item["updated_at"].endswith("Z")
    assert item["severity"] == "high" and isinstance(item["raw"], str)
    last = run(form, "fetch", "fetch_next_page", {"cursor": first["next_cursor"]})
    assert last["next_cursor"] is None
    assert [i["external_id"] for i in last["items"]] == ["A-1002"]


@pytest.mark.parametrize("form", FORMS)
@pytest.mark.parametrize("args", [{"alert_id": "A-1001"}, {"alert_id": "A-1001", "note": "dup"}])
def test_close_alert_steps(form, args):
    dry = run(form, "close_alert.dry_run", "alert_open", args)
    assert dry["affects"] == ["A-1001"] and dry["detail"] == {"status": "open"}
    done = run(form, "close_alert.execute", "close", args)
    assert done["detail"] == {"status": "closed"}
    undone = run(form, "close_alert.undo", "reopen", args)
    assert undone["detail"] == {"status": "open"}
    assert run(form, "close_alert.observe", "alert_closed", args) == 1
    assert run(form, "close_alert.observe", "alert_open", args) == 0
