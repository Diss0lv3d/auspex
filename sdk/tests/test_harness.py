"""`auspex-sdk run` (S32, Task 6): a command against recorded exchanges, no network."""

import json
import textwrap
from pathlib import Path

import pytest
from auspex_sdk.build import BuildError
from auspex_sdk.cli import main
from auspex_sdk.harness import HarnessError, run_command
from auspex_sdk.http import HostNotDeclared
from auspex_sdk.results import ResultError

CONNECTOR = '''
from dataclasses import dataclass
from typing import Annotated

from auspex_sdk.runtime import Context, OutputField, Secret, Url, action, command, connector


@connector(id="example.sample", version="1.0.0", name="Sample",
           description="A sample connector.", hosts=("https://{base_url}",))
@dataclass(frozen=True)
class Config:
    base_url: Annotated[Url, "Service URL"]
    api_token: Annotated[Secret, "API token"]


@command("test")
def check(ctx: Context) -> dict:
    r = ctx.http.get(ctx.config.base_url + "/ping")
    return {"ok": r.status_code == 200, "detail": r.json()["msg"]}


@command("fetch")
def pull(ctx: Context, cursor: str | None, limit: int) -> dict:
    params = {"limit": limit, **({"after": cursor} if cursor else {})}
    r = ctx.http.get(ctx.config.base_url + "/alerts", params=params)
    return {"items": r.json()["alerts"], "next_cursor": None}


def close_dry(ctx: Context, alert_id: str, note: str = "") -> dict:
    return {"would": "close", "affects": [alert_id], "reversible": True,
            "detail": {"note": note}}


def close_undo(ctx: Context, alert_id: str, note: str = "") -> dict:
    return {"would": "reopen", "affects": [alert_id], "reversible": True, "detail": {}}


def close_observe(ctx: Context, alert_id: str, note: str = "") -> int:
    return 3


@action("close_alert", risk="write", dry_run=close_dry, observe=close_observe,
        targets="alert_id", output=(OutputField("note", "string", False),))
def close_alert(
    ctx: Context,
    alert_id: Annotated[str, "The alert to close."],
    note: Annotated[str, "Free text."] = "",
) -> dict:
    """Close an alert."""
    return {"would": "closed", "affects": [alert_id], "reversible": False,
            "detail": {"note": note, "extra": 1} if note == "bad" else {"note": note}}
'''

BASE = "https://api.example.test"
CONFIG = {"base_url": BASE}
SECRETS = {"api_token": "tok-0123456789abcdef"}  # placeholder, not a credential


def ex(url, body, method="GET", status=200):
    return {
        "request": {"method": method, "url": url},
        "response": {"status": status, "headers": {}, "json": body},
    }


@pytest.fixture
def src(tmp_path):
    d = tmp_path / "conn"
    d.mkdir()
    (d / "sample.py").write_text(textwrap.dedent(CONNECTOR))
    return d


def fixture(tmp_path: Path, *exchanges) -> Path:
    p = tmp_path / "fx.json"
    p.write_text(json.dumps({"exchanges": list(exchanges)}))
    return p


def run(src, tmp_path, command, *exchanges, config=CONFIG, arguments=None):
    return run_command(
        src,
        command,
        config=config,
        secrets=SECRETS,
        fixture=fixture(tmp_path, *exchanges),
        arguments=arguments,
    )


def test_test_runs_against_the_fixture(src, tmp_path):
    out = run(src, tmp_path, "test", ex(f"{BASE}/ping", {"msg": "reachable"}))
    assert out == {"ok": True, "detail": "reachable"}


def test_an_unmatched_request_fails_naming_its_url(src, tmp_path):
    with pytest.raises(HarnessError, match=r"GET https://api\.example\.test/ping"):
        run(src, tmp_path, "test", ex(f"{BASE}/other", {}))


def test_an_undeclared_host_fails_before_the_fixture_is_consulted(src, tmp_path):
    # the fixture holds the exchange; the host check must still refuse first
    text = (src / "sample.py").read_text()
    other = "https://elsewhere.example.test/ping"
    (src / "sample.py").write_text(text.replace('ctx.config.base_url + "/ping"', f'"{other}"'))
    with pytest.raises(HostNotDeclared):
        run(src, tmp_path, "test", ex(other, {"msg": "x"}))


def test_query_order_does_not_matter_and_fetch_items_come_back(src, tmp_path):
    out = run(
        src,
        tmp_path,
        "fetch",
        ex(f"{BASE}/alerts?after=c1&limit=5", {"alerts": [{"a": 1}]}),
        arguments={"cursor": "c1", "limit": 5},
    )
    assert out == {"items": [{"a": 1}], "next_cursor": None}


def test_fetch_defaults_are_no_cursor_and_limit_100(src, tmp_path):
    out = run(src, tmp_path, "fetch", ex(f"{BASE}/alerts?limit=100", {"alerts": []}))
    assert out["items"] == []


def test_a_fetch_item_that_is_not_an_object_is_refused(src, tmp_path):
    with pytest.raises(HarnessError, match=r"items\[0\]"):
        run(src, tmp_path, "fetch", ex(f"{BASE}/alerts?limit=100", {"alerts": ["x"]}))


def test_action_steps_return_the_validated_envelope(src, tmp_path):
    args = {"alert_id": "A-1", "note": "n"}
    dry = run(src, tmp_path, "close_alert.dry_run", arguments=args)
    assert dry == {
        "would": "close",
        "affects": ["A-1"],
        "reversible": True,
        "detail": {"note": "n"},
    }
    assert run(src, tmp_path, "close_alert.execute", arguments=args)["reversible"] is False
    assert run(src, tmp_path, "close_alert.observe", arguments=args) == 3


def test_an_envelope_detail_outside_the_declared_output_is_refused(src, tmp_path):
    with pytest.raises(HarnessError, match="detail.extra is not declared"):
        run(src, tmp_path, "close_alert.execute", arguments={"alert_id": "A-1", "note": "bad"})


def test_an_undeclared_argument_is_refused_by_name(src, tmp_path):
    with pytest.raises(HarnessError, match="'colour'"):
        run(src, tmp_path, "close_alert.dry_run", arguments={"alert_id": "A", "colour": "red"})


def test_a_missing_required_argument_is_refused(src, tmp_path):
    with pytest.raises(HarnessError, match="'alert_id' is required"):
        run(src, tmp_path, "close_alert.dry_run", arguments={})


def test_an_omitted_optional_param_arrives_as_none(src, tmp_path):
    (src / "sample.py").write_text(
        (src / "sample.py")
        .read_text()
        .replace(
            'def close_dry(ctx: Context, alert_id: str, note: str = "") -> dict:\n',
            'def close_dry(ctx: Context, alert_id: str, note: str = "") -> dict:\n'
            "    assert note is None\n",
        )
    )
    assert run(src, tmp_path, "close_alert.dry_run", arguments={"alert_id": "A"})["would"]


def test_an_undo_the_action_does_not_declare_and_unknown_commands_are_refused(src, tmp_path):
    with pytest.raises(HarnessError, match="declares no undo"):
        run(src, tmp_path, "close_alert.undo", arguments={"alert_id": "A"})
    with pytest.raises(HarnessError, match="expected test, fetch"):
        run(src, tmp_path, "nonsense")


def test_a_handler_result_json_cannot_carry_is_refused(src, tmp_path):
    (src / "sample.py").write_text(
        (src / "sample.py").read_text().replace('r.json()["msg"]', "{1, 2}")
    )
    with pytest.raises((ResultError, HarnessError)):
        run(src, tmp_path, "test", ex(f"{BASE}/ping", {"msg": "x"}))


def test_a_missing_handler_module_is_a_build_error(src, tmp_path):
    (src / "sample.py").write_text(
        (src / "sample.py").read_text().replace("@command", "import nothere  # noqa\n@command", 1)
    )
    with pytest.raises(BuildError):
        run(src, tmp_path, "test")


def test_cli_prints_the_canonical_result_and_exits_zero(src, tmp_path, capsys):
    cfg = tmp_path / "cfg.json"
    cfg.write_text(json.dumps(CONFIG))
    sec = tmp_path / "sec.json"
    sec.write_text(json.dumps(SECRETS))
    fx = fixture(tmp_path, ex(f"{BASE}/ping", {"msg": "reachable"}))
    code = main(
        ["run", str(src), "test", "--config", str(cfg), "--secrets", str(sec), "--fixture", str(fx)]
    )
    assert code == 0
    assert json.loads(capsys.readouterr().out) == {"ok": True, "detail": "reachable"}


def test_cli_exits_one_with_a_one_line_reason(src, tmp_path, capsys):
    cfg = tmp_path / "cfg.json"
    cfg.write_text(json.dumps(CONFIG))
    sec = tmp_path / "sec.json"
    sec.write_text(json.dumps(SECRETS))
    fx = fixture(tmp_path)
    code = main(
        ["run", str(src), "test", "--config", str(cfg), "--secrets", str(sec), "--fixture", str(fx)]
    )
    assert code == 1
    err = capsys.readouterr().err
    assert err.count("\n") == 1 and "/ping" in err


def test_a_yaml_connector_runs_with_a_config_built_from_the_manifest(tmp_path):
    d = tmp_path / "ym"
    d.mkdir()
    (d / "h.py").write_text(
        "def check(ctx):\n"
        "    r = ctx.http.get(ctx.config.base_url + '/ping')\n"
        "    return {'ok': True, 'detail': f'{r.status_code} page={ctx.config.page}'}\n"
    )
    (d / "connector.yaml").write_text(
        textwrap.dedent("""
        schema_version: 1
        id: example.yml
        version: 1.0.0
        name: Yml
        description: A YAML connector.
        config:
          - {name: base_url, label: Service URL, type: url, required: true}
          - {name: page, label: Page, type: integer, required: false, default: 50}
        hosts: ["https://{base_url}"]
        commands:
          test: {handler: "h:check"}
        """)
    )
    out = run_command(
        d, "test", config=CONFIG, secrets={}, fixture=fixture(tmp_path, ex(f"{BASE}/ping", {}))
    )
    assert out == {"ok": True, "detail": "200 page=50"}
