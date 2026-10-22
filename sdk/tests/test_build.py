"""`auspex-sdk build` (S32, Task 5): two authoring formats, one canonical manifest.

Sample connectors are written to tmp_path: a Python-first one and its YAML twin with identical
declarations. The twin's handlers are the same functions without decorators.
"""

import sys
import textwrap
import zipfile
from pathlib import Path

import pytest
from auspex_sdk.build import BuildError, build, check_handlers, load_manifest
from auspex_sdk.cli import main
from auspex_sdk.manifest import ManifestError
from auspex_sdk.package import read_package

HANDLERS = """
def check(ctx):
    return {"ok": True, "detail": "reachable"}


def pull(ctx, cursor, limit):
    return {"items": [], "next_cursor": None}


def close_dry(ctx, alert_id, note=""):
    return {"would": "close", "affects": [alert_id], "reversible": True, "detail": {}}


def close_observe(ctx, alert_id, note=""):
    return {"state": "closed"}


def close_alert(ctx, alert_id, note=""):
    return {"status": "closed"}
"""

PYTHON_FIRST = '''
from dataclasses import dataclass
from typing import Annotated

from auspex_sdk.runtime import (
    Context, OutputField, Secret, Url, action, command, connector,
)


@connector(id="example.sample", version="1.0.0", name="Sample",
           description="A sample connector.", hosts=("https://{base_url}",))
@dataclass(frozen=True)
class Config:
    base_url: Annotated[Url, "Service URL"]
    api_token: Annotated[Secret, "API token"]
    page: Annotated[int, "Page size"] = 50


@command("test")
def check(ctx: Context) -> dict:
    return {"ok": True, "detail": "reachable"}


@command("fetch")
def pull(ctx: Context, cursor: str | None, limit: int) -> dict:
    return {"items": [], "next_cursor": None}


def close_dry(ctx: Context, alert_id: str, note: str = "") -> dict:
    return {"would": "close", "affects": [alert_id], "reversible": True, "detail": {}}


def close_observe(ctx: Context, alert_id: str, note: str = "") -> dict:
    return {"state": "closed"}


@action("close_alert", risk="write", dry_run=close_dry, observe=close_observe,
        targets="alert_id", output=(OutputField("status", "string", True),))
def close_alert(
    ctx: Context,
    alert_id: Annotated[str, "The alert to close."],
    note: Annotated[str, "Free text."] = "",
) -> dict:
    """Close an alert."""
    return {"status": "closed"}
'''

YAML_TWIN = """
schema_version: 1
id: example.sample
version: 1.0.0
name: Sample
description: A sample connector.
config:
  - {name: base_url, label: Service URL, type: url, required: true}
  - {name: api_token, label: API token, type: secret, required: true}
  - {name: page, label: Page size, type: integer, required: false, default: 50}
hosts: ["https://{base_url}"]
commands:
  test: {handler: "sample:check"}
  fetch: {handler: "sample:pull", serves_many_clients: false}
actions:
  - name: close_alert
    description: Close an alert.
    risk: write
    params:
      - {name: alert_id, type: string, description: "The alert to close.", required: true}
      - {name: note, type: string, description: "Free text.", required: false}
    execute: "sample:close_alert"
    dry_run: "sample:close_dry"
    observe: "sample:close_observe"
    output:
      - {name: status, type: string, required: true}
    targets: alert_id
"""
# "1.0.0" is a plain YAML string (not a float); the quotes above are for the colons only.


def write(root: Path, files: dict[str, str]) -> Path:
    for name, text in files.items():
        p = root / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(textwrap.dedent(text).lstrip("\n"))
    return root


@pytest.fixture
def python_first(tmp_path):
    return write(tmp_path / "py", {"sample.py": PYTHON_FIRST})


@pytest.fixture
def yaml_twin(tmp_path):
    return write(tmp_path / "ym", {"sample.py": HANDLERS, "connector.yaml": YAML_TWIN})


def members(zip_path: Path) -> dict[str, bytes]:
    with zipfile.ZipFile(zip_path) as z:
        return {n: z.read(n) for n in z.namelist()}


# --- one canonical form ----------------------------------------------------------------------


def test_python_first_and_yaml_build_to_byte_identical_manifests(python_first, yaml_twin):
    py_zip, _ = build(python_first)
    ym_zip, _ = build(yaml_twin)
    a, b = members(py_zip)["manifest.json"], members(ym_zip)["manifest.json"]
    assert a == b
    assert b'"sdk_version":"0.1.0"' in a  # the build fills it
    assert py_zip.name == "example.sample-1.0.0.zip"
    assert py_zip.parent == python_first / "dist"


def test_each_build_is_deterministic_and_the_two_hashes_differ(python_first, yaml_twin):
    first = build(python_first)
    again = build(python_first)
    assert first[1] == again[1] and first[1].startswith("sha256:")
    assert first[0].read_bytes() == again[0].read_bytes()
    y1, y2 = build(yaml_twin), build(yaml_twin)
    assert y1[1] == y2[1]
    assert first[1] != y1[1]  # the code differs, so the identity differs


def test_the_built_zip_passes_read_package_and_its_hash_is_returned(python_first):
    path, digest = build(python_first)
    manifest, got, files = read_package(path.read_bytes())
    assert got == digest
    assert manifest.id == "example.sample" and "sample.py" in files


def test_a_rebuild_does_not_hash_the_previous_dist(python_first):
    _, h1 = build(python_first)
    _, h2 = build(python_first)  # dist/ now exists
    assert h1 == h2


# --- what the package holds ------------------------------------------------------------------


def test_the_zip_excludes_yaml_tests_caches_dotfiles_and_dist(yaml_twin):
    write(
        yaml_twin,
        {
            "lib/util.py": "X = 1\n",
            "lib/__init__.py": "",
            "data/map.json": "{}\n",
            "tests/test_a.py": "def test_a(): pass\n",
            "test_sample.py": "def test_b(): pass\n",
            "notes.yml": "a: 1\n",
            ".hidden": "x\n",
            "__pycache__/sample.cpython-312.pyc": "junk",
            "dist/old.zip": "stale",
        },
    )
    path, _ = build(yaml_twin)
    assert set(members(path)) == {
        "manifest.json",
        "sample.py",
        "lib/util.py",
        "lib/__init__.py",
        "data/map.json",
    }


def test_the_build_leaves_no_caches_or_import_traces(python_first):
    before_path = list(sys.path)
    build(python_first)
    assert sys.path == before_path
    assert "sample" not in sys.modules
    assert not (python_first / "__pycache__").exists()


def test_a_source_manifest_json_is_refused(python_first):
    (python_first / "manifest.json").write_text("{}")
    with pytest.raises(BuildError, match="manifest.json"):
        build(python_first)


def test_a_symlink_in_the_source_is_refused(python_first, tmp_path):
    (tmp_path / "outside.txt").write_text("not yours")
    (python_first / "link.txt").symlink_to(tmp_path / "outside.txt")
    with pytest.raises(BuildError, match="symlink"):
        build(python_first)


# --- handler checks --------------------------------------------------------------------------


def test_a_yaml_naming_a_missing_function_is_refused_by_its_reference(yaml_twin):
    y = (yaml_twin / "connector.yaml").read_text().replace("sample:close_dry", "sample:nope")
    (yaml_twin / "connector.yaml").write_text(y)
    with pytest.raises(BuildError) as ei:
        build(yaml_twin)
    assert "sample:nope" in str(ei.value) and "actions[0].dry_run" in str(ei.value)


def test_a_yaml_naming_a_missing_execute_is_refused_by_its_reference(yaml_twin):
    y = (yaml_twin / "connector.yaml").read_text().replace("sample:close_alert", "sample:gone")
    (yaml_twin / "connector.yaml").write_text(y)
    with pytest.raises(BuildError) as ei:
        build(yaml_twin)
    assert "sample:gone" in str(ei.value) and "actions[0].execute" in str(ei.value)


def test_a_yaml_execute_with_a_parameter_mismatch_is_refused(yaml_twin):
    src = (yaml_twin / "sample.py").read_text()
    old = 'def close_alert(ctx, alert_id, note=""):'
    assert old in src
    (yaml_twin / "sample.py").write_text(src.replace(old, "def close_alert(ctx, alert_id):"))
    with pytest.raises(BuildError, match="actions.0..execute.*close_alert|close_alert.*must take"):
        build(yaml_twin)


def test_a_python_first_manifest_carries_the_execute_reference(python_first):
    path, _ = build(python_first)
    assert b'"execute":"sample:close_alert"' in members(path)["manifest.json"]


def test_a_yaml_naming_a_missing_module_is_refused_by_its_reference(yaml_twin):
    y = (yaml_twin / "connector.yaml").read_text().replace("sample:check", "ghost:check")
    (yaml_twin / "connector.yaml").write_text(y)
    with pytest.raises(BuildError, match="ghost"):
        build(yaml_twin)


@pytest.mark.parametrize(
    ("old", "new"),
    [
        ('def close_dry(ctx, alert_id, note="")', "def close_dry(ctx, alert_id)"),  # forgot one
        ('def close_dry(ctx, alert_id, note="")', 'def close_dry(ctx, alert_id, note="", extra=1)'),
        ('def close_dry(ctx, alert_id, note="")', "def close_dry(ctx, note, alert_id)"),  # order
        (
            'def close_dry(ctx, alert_id, note="")',
            'def close_dry(alert_id, note="")',
        ),
        ('def close_observe(ctx, alert_id, note="")', "def close_observe(ctx, **kw)"),
        ("def check(ctx)", "def check(ctx, extra)"),
        ("def pull(ctx, cursor, limit)", "def pull(ctx, cursor)"),
    ],
    ids=["missing", "extra", "order", "no_ctx", "kwargs", "test_cmd", "fetch_cmd"],
)
def test_a_parameter_mismatch_is_refused(yaml_twin, old, new):
    src = (yaml_twin / "sample.py").read_text()
    assert old in src
    (yaml_twin / "sample.py").write_text(src.replace(old, new))
    with pytest.raises(BuildError, match="must take"):
        build(yaml_twin)


def test_python_first_handlers_are_checked_too(python_first):
    src = (python_first / "sample.py").read_text()
    (python_first / "sample.py").write_text(
        src.replace(
            'def close_dry(ctx: Context, alert_id: str, note: str = "")',
            "def close_dry(ctx: Context, alert_id: str)",
        )
    )
    with pytest.raises(BuildError, match="close_dry"):
        build(python_first)


def test_check_handlers_is_callable_on_a_loaded_manifest(yaml_twin):
    check_handlers(load_manifest(yaml_twin), yaml_twin)  # passes silently


def test_a_handler_module_outside_the_source_dir_is_refused(yaml_twin):
    y = (yaml_twin / "connector.yaml").read_text().replace("sample:check", "json:dumps")
    (yaml_twin / "connector.yaml").write_text(y)
    with pytest.raises(BuildError, match="does not come from the source"):
        build(yaml_twin)


# --- the YAML form ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "match"),
    [
        ("- just\n- a list\n", "must be a mapping"),
        ("a: [unclosed\n", "not valid YAML"),
        ("id: a\nid: b\n", "duplicate key"),
        ("x: !!python/object/apply:os.system ['echo hi']\n", "not valid YAML"),
    ],
    ids=["not_a_mapping", "syntax", "duplicate_key", "unsafe_tag"],
)
def test_yaml_errors(yaml_twin, text, match):
    (yaml_twin / "connector.yaml").write_text(text)
    with pytest.raises(BuildError, match=match):
        build(yaml_twin)


def test_yaml_sdk_version_is_refused(yaml_twin):
    (yaml_twin / "connector.yaml").write_text(
        (yaml_twin / "connector.yaml").read_text() + 'sdk_version: "9.9.9"\n'
    )
    with pytest.raises(BuildError, match="sdk_version"):
        build(yaml_twin)


def test_yaml_manifest_rules_still_apply(yaml_twin):
    y = (yaml_twin / "connector.yaml").read_text().replace("risk: write", "risk: destructive")
    (yaml_twin / "connector.yaml").write_text(y)
    with pytest.raises(ManifestError) as ei:
        build(yaml_twin)
    assert ei.value.rule == "destructive_without_undo"


# --- finding the Python-first module ---------------------------------------------------------


def test_no_connector_anywhere_is_refused(tmp_path):
    write(tmp_path, {"helpers.py": "X = 1\n"})
    with pytest.raises(BuildError, match="no connector.yaml"):
        build(tmp_path)


def test_two_connector_modules_are_refused(python_first):
    (python_first / "other.py").write_text((python_first / "sample.py").read_text())
    with pytest.raises(BuildError, match="more than one"):
        build(python_first)


def test_a_module_that_only_imports_the_connector_is_not_a_second_one(python_first):
    (python_first / "reexport.py").write_text("from sample import Config\n")
    path, _ = build(python_first)
    assert "reexport.py" in members(path)


def test_an_import_error_in_the_authors_module_is_reported(python_first):
    (python_first / "broken.py").write_text("raise RuntimeError('boom')\n")
    with pytest.raises(BuildError, match="broken.*boom"):
        build(python_first)


def test_a_missing_source_dir_is_refused(tmp_path):
    with pytest.raises(BuildError, match="not a directory"):
        build(tmp_path / "nowhere")


# --- the command line ------------------------------------------------------------------------


def test_cli_build_prints_the_hash_and_the_zip_path(python_first, capsys):
    assert main(["build", str(python_first)]) == 0
    out = capsys.readouterr().out.split()
    assert out[0].startswith("sha256:") and out[1].endswith("example.sample-1.0.0.zip")
    assert Path(out[1]).is_file()


def test_cli_refusal_is_one_line_and_exit_code_one(yaml_twin, capsys):
    y = (yaml_twin / "connector.yaml").read_text().replace("sample:close_dry", "sample:nope")
    (yaml_twin / "connector.yaml").write_text(y)
    assert main(["build", str(yaml_twin)]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.count("\n") == 1 and "sample:nope" in captured.err


def test_cli_refuses_a_manifest_rule_with_exit_one(yaml_twin, capsys):
    (yaml_twin / "connector.yaml").write_text(
        YAML_TWIN.replace("schema_version: 1", "schema_version: 2")
    )
    assert main(["build", str(yaml_twin)]) == 1
    assert "schema_version" in capsys.readouterr().err
