"""The connector manifest v1: one refusal per rule, each with its exact reason (S32, task 2)."""

import copy
import json

import pytest
from auspex_sdk import manifest as mf
from auspex_sdk.manifest import ManifestError, manifest_to_json, parse_manifest, validate_manifest


def reference() -> dict:
    """A small, valid manifest; every rule's row mutates a deep copy of this."""
    return {
        "schema_version": 1,
        "id": "ibm.qradar",
        "version": "1.2.0",
        "name": "QRadar",
        "description": "Pull offenses from QRadar and act on them.",
        "sdk_version": "0.1.0",
        "config": [
            {"name": "base_url", "label": "QRadar URL", "type": "url", "required": True},
            {"name": "api_token", "label": "API token", "type": "secret", "required": True},
            {"name": "tls", "label": "TLS", "type": "tls", "default": "verify"},
            {
                "name": "mode",
                "label": "Mode",
                "type": "enum",
                "values": ["fast", "full"],
                "default": "fast",
            },
            {"name": "page", "label": "Page", "type": "integer", "default": 50},
        ],
        "hosts": ["https://{base_url}", "https://api.vendor.example:8443"],
        "commands": {"test": {}, "fetch": {"serves_many_clients": False}},
        "actions": [
            {
                "name": "close_offense",
                "description": "Close an offense.",
                "risk": "destructive",
                "params": [
                    {
                        "name": "offense_id",
                        "type": "string",
                        "description": "The offense.",
                        "required": True,
                    },
                    {
                        "name": "reason",
                        "type": "string",
                        "description": "Why.",
                        "values": ["fp", "tp"],
                    },
                ],
                "dry_run": "qradar.actions:close_dry_run",
                "undo": {
                    "handler": "qradar.actions:reopen",
                    "restores": "The offense status.",
                    "cannot_restore": ["notes added after closing"],
                },
                "observe": "qradar.actions:close_observe",
                "output": [
                    {"name": "status", "type": "string", "required": True},
                    {"name": "tags", "type": "string[]"},
                ],
                "targets": "offense_id",
            },
            {
                "name": "get_offense",
                "description": "Read an offense.",
                "risk": "read",
                "dry_run": "qradar.actions:get_dry_run",
            },
        ],
    }


def mutate(fn):
    def apply(d: dict) -> dict:
        fn(d)
        return d

    return apply


def set_path(d, *keys, value):
    for k in keys[:-1]:
        d = d[k]
    d[keys[-1]] = value


def test_the_reference_shape_is_valid():
    m = parse_manifest(reference())
    validate_manifest(m)
    assert m.id == "ibm.qradar"
    assert m.fetch is not None and m.fetch.serves_many_clients is False
    assert m.actions[0].undo.cannot_restore == ("notes added after closing",)


def test_the_manifest_round_trips_through_canonical_json():
    m = parse_manifest(reference())
    raw = manifest_to_json(m)
    assert isinstance(raw, bytes) and raw.endswith(b"\n")
    assert raw == manifest_to_json(parse_manifest(json.loads(raw)))
    assert parse_manifest(json.loads(raw)) == m
    # sorted keys, compact separators
    assert raw.startswith(b'{"actions":[')
    assert b", " not in raw and b": " not in raw


def test_canonical_json_keeps_non_ascii_as_utf8():
    d = reference()
    d["description"] = "Bläddra — ok"
    raw = manifest_to_json(parse_manifest(d))
    assert "Bläddra — ok".encode() in raw


def many_clients(d):
    d["commands"]["fetch"]["serves_many_clients"] = True


ROWS = [
    # (id, mutation, rule, path)
    (
        "destructive_without_undo",
        lambda d: d["actions"][0].pop("undo"),
        "destructive_without_undo",
        "actions[0].undo",
    ),
    (
        "undo_on_read",
        lambda d: d["actions"][1].update(
            undo={"handler": "q:u", "restores": "x", "cannot_restore": []}
        ),
        "undo_on_read",
        "actions[1].undo",
    ),
    (
        "placeholder_naming_no_field",
        lambda d: d["hosts"].append("https://{nope}"),
        "undeclared_host",
        "hosts[2]",
    ),
    (
        "placeholder_naming_non_url_field",
        lambda d: d["hosts"].append("https://{mode}"),
        "undeclared_host",
        "hosts[2]",
    ),
    ("url_field_used_by_no_host", lambda d: d["hosts"].pop(0), "undeclared_host", "config[0]"),
    (
        "http_host",
        lambda d: d["hosts"].append("http://api.vendor.example"),
        "undeclared_host",
        "hosts[2]",
    ),
    (
        "wildcard_host",
        lambda d: d["hosts"].append("https://*.vendor.example"),
        "undeclared_host",
        "hosts[2]",
    ),
    (
        "port_out_of_range",
        lambda d: d["hosts"].append("https://api.vendor.example:99999"),
        "undeclared_host",
        "hosts[2]",
    ),
    (
        "host_with_path",
        lambda d: d["hosts"].append("https://api.vendor.example/v1"),
        "undeclared_host",
        "hosts[2]",
    ),
    (
        "placeholder_with_suffix",
        lambda d: d["hosts"].append("https://{base_url}.evil.example"),
        "undeclared_host",
        "hosts[2]",
    ),
    (
        "tls_off_string",
        lambda d: d["config"][2].update(default="off"),
        "tls_off",
        "config[2].default",
    ),
    (
        "tls_off_false",
        lambda d: d["config"][2].update(default=False),
        "tls_off",
        "config[2].default",
    ),
    (
        "tls_off_none",
        lambda d: d["config"][2].update(default="none"),
        "tls_off",
        "config[2].default",
    ),
    (
        "tls_off_insecure",
        lambda d: d["config"][2].update(default="insecure"),
        "tls_off",
        "config[2].default",
    ),
    (
        "tls_off_object",
        lambda d: d["config"][2].update(default={"verify": False}),
        "tls_off",
        "config[2].default",
    ),
    (
        "tls_default_not_verify",
        lambda d: d["config"][2].update(default={"ca_pem": "x"}),
        "bad_type",
        "config[2].default",
    ),
    (
        "missing_dry_run_absent",
        lambda d: d["actions"][1].pop("dry_run"),
        "missing_dry_run",
        "actions[1].dry_run",
    ),
    (
        "missing_dry_run_empty",
        lambda d: d["actions"][1].update(dry_run=""),
        "missing_dry_run",
        "actions[1].dry_run",
    ),
    ("shared_fetch_without_routing_key_is_a_runtime_check", None, None, None),
    (
        "bad_action_name",
        lambda d: d["actions"][0].update(name="close-offense"),
        "bad_name",
        "actions[0].name",
    ),
    (
        "platform_keyword_action_name",
        lambda d: d["actions"][0].update(name="workspace_id"),
        "bad_name",
        "actions[0].name",
    ),
    (
        "platform_keyword_param_name",
        lambda d: d["actions"][0]["params"][0].update(name="proposal_id"),
        "bad_name",
        "actions[0].params[0].name",
    ),
    (
        "long_action_name",
        lambda d: d["actions"][0].update(name="a" * 65),
        "bad_name",
        "actions[0].name",
    ),
    ("non_dotted_id", lambda d: d.update(id="qradar"), "bad_name", "id"),
    ("uppercase_id", lambda d: d.update(id="IBM.qradar"), "bad_name", "id"),
    ("bad_version", lambda d: d.update(version="1.2"), "bad_name", "version"),
    (
        "targets_names_no_param",
        lambda d: d["actions"][0].update(targets="ghost"),
        "bad_name",
        "actions[0].targets",
    ),
    (
        "unknown_config_type",
        lambda d: d["config"][4].update(type="float"),
        "unknown_type",
        "config[4].type",
    ),
    (
        "unknown_param_type",
        lambda d: d["actions"][0]["params"][0].update(type="array"),
        "unknown_type",
        "actions[0].params[0].type",
    ),
    (
        "unknown_output_type",
        lambda d: d["actions"][0]["output"][0].update(type="object"),
        "unknown_type",
        "actions[0].output[0].type",
    ),
    (
        "secret_with_default",
        lambda d: d["config"][1].update(default="hunter2"),
        "secret_with_default",
        "config[1].default",
    ),
    ("schema_version_2", lambda d: d.update(schema_version=2), "schema_version", "schema_version"),
    ("schema_version_true", lambda d: d.update(schema_version=True), "bad_type", "schema_version"),
    (
        "duplicate_config_name",
        lambda d: d["config"][4].update(name="mode"),
        "duplicate_name",
        "config[4].name",
    ),
    (
        "duplicate_action_name",
        lambda d: d["actions"][1].update(name="close_offense"),
        "duplicate_name",
        "actions[1].name",
    ),
    (
        "duplicate_param_name",
        lambda d: d["actions"][0]["params"][1].update(name="offense_id"),
        "duplicate_name",
        "actions[0].params[1].name",
    ),
    (
        "duplicate_output_name",
        lambda d: d["actions"][0]["output"][1].update(name="status"),
        "duplicate_name",
        "actions[0].output[1].name",
    ),
    (
        "http_url_default",
        lambda d: d["config"][0].update(default="http://qradar.example"),
        "http_url_default",
        "config[0].default",
    ),
    (
        "url_default_with_userinfo",
        lambda d: d["config"][0].update(default="https://admin:hunter2@q.example"),
        "secret_with_default",
        "config[0].default",
    ),
    (
        "url_default_user_only",
        lambda d: d["config"][0].update(default="https://admin@q.example"),
        "secret_with_default",
        "config[0].default",
    ),
    (
        "url_default_bad_port",
        lambda d: d["config"][0].update(default="https://q.example:99999"),
        "http_url_default",
        "config[0].default",
    ),
    (
        "url_default_port_zero",
        lambda d: d["config"][0].update(default="https://q.example:0"),
        "http_url_default",
        "config[0].default",
    ),
    (
        "url_default_ipv6",
        lambda d: d["config"][0].update(default="https://[::1]:99999/x"),
        "http_url_default",
        "config[0].default",
    ),
    (
        "url_default_ipv6_valid_port",
        lambda d: d["config"][0].update(default="https://[::1]:8443/x"),
        "http_url_default",
        "config[0].default",
    ),
    (
        "host_port_zero",
        lambda d: d["hosts"].append("https://api.vendor.example:0"),
        "undeclared_host",
        "hosts[2]",
    ),
    (
        "ftp_url_default",
        lambda d: d["config"][0].update(default="ftp://qradar.example"),
        "http_url_default",
        "config[0].default",
    ),
    (
        "description_too_long",
        lambda d: d.update(description="x" * 2001),
        "description_too_long",
        "description",
    ),
    (
        "action_description_too_long",
        lambda d: d["actions"][1].update(description="x" * 2001),
        "description_too_long",
        "actions[1].description",
    ),
    ("enum_without_values", lambda d: d["config"][3].pop("values"), "bad_type", "config[3].values"),
    (
        "enum_default_outside_values",
        lambda d: d["config"][3].update(default="slow"),
        "bad_type",
        "config[3].default",
    ),
    (
        "integer_default_is_a_string",
        lambda d: d["config"][4].update(default="50"),
        "bad_type",
        "config[4].default",
    ),
    (
        "integer_default_is_a_bool",
        lambda d: d["config"][4].update(default=True),
        "bad_type",
        "config[4].default",
    ),
    (
        "malformed_handler",
        lambda d: d["actions"][0].update(dry_run="no colon here"),
        "bad_type",
        "actions[0].dry_run",
    ),
    ("wrong_json_type", lambda d: d.update(name=7), "bad_type", "name"),
    (
        "wrong_json_type_nested",
        lambda d: d["actions"][0].update(params="x"),
        "bad_type",
        "actions[0].params",
    ),
    ("missing_test_command", lambda d: d["commands"].pop("test"), "bad_type", "commands.test"),
]
ROWS = [r for r in ROWS if r[1] is not None]


@pytest.mark.parametrize(
    ("mutation", "rule", "path"), [r[1:] for r in ROWS], ids=[r[0] for r in ROWS]
)
def test_each_rule_refuses_with_its_reason(mutation, rule, path):
    d = reference()
    mutation(d)
    with pytest.raises(ManifestError) as ei:
        validate_manifest(parse_manifest(d))
    assert ei.value.rule == rule
    assert ei.value.path == path
    assert path in str(ei.value) and rule in str(ei.value)


def test_the_rule_names_are_the_ones_the_contract_documents():
    assert {r[2] for r in ROWS} <= set(mf.RULES)


def test_shared_fetch_without_routing_key_refuses_the_item():
    m = parse_manifest(reference())
    ok = {"external_id": "1", "kind": "alert"}
    mf.check_fetch_item(m, ok)  # not serving many clients: no routing key needed
    d = reference()
    many_clients(d)
    shared = parse_manifest(d)
    mf.check_fetch_item(shared, {**ok, "routing_key": "client-a"})
    for bad in (ok, {**ok, "routing_key": ""}, {**ok, "routing_key": 5}):
        with pytest.raises(ManifestError) as ei:
            mf.check_fetch_item(shared, bad)
        assert ei.value.rule == "shared_fetch_without_routing_key"
        assert ei.value.path == "routing_key"


def test_a_shared_fetch_manifest_is_itself_valid():
    d = reference()
    many_clients(d)
    validate_manifest(parse_manifest(d))


def test_unknown_keys_are_refused_at_every_level():
    paths = {
        "top": (lambda d: d.update(extra=1), "extra"),
        "config": (lambda d: d["config"][0].update(extra=1), "config[0].extra"),
        "commands": (lambda d: d["commands"].update(extra={}), "commands.extra"),
        "fetch": (lambda d: d["commands"]["fetch"].update(extra=1), "commands.fetch.extra"),
        "action": (lambda d: d["actions"][0].update(extra=1), "actions[0].extra"),
        "param": (
            lambda d: d["actions"][0]["params"][0].update(extra=1),
            "actions[0].params[0].extra",
        ),
        "undo": (lambda d: d["actions"][0]["undo"].update(extra=1), "actions[0].undo.extra"),
        "output": (
            lambda d: d["actions"][0]["output"][0].update(extra=1),
            "actions[0].output[0].extra",
        ),
    }
    for _, (mutation, path) in paths.items():
        d = reference()
        mutation(d)
        with pytest.raises(ManifestError) as ei:
            parse_manifest(d)
        assert (ei.value.rule, ei.value.path) == ("unknown_key", path)


def test_a_non_object_manifest_is_refused():
    with pytest.raises(ManifestError) as ei:
        parse_manifest([])  # type: ignore[arg-type]
    assert ei.value.rule == "bad_type"


def test_validate_raises_on_the_first_violation_in_a_stable_order():
    d = reference()
    d["schema_version"] = 2
    d["id"] = "nodots"
    d["actions"][0].pop("undo")
    m = parse_manifest(d)
    for _ in range(3):
        with pytest.raises(ManifestError) as ei:
            validate_manifest(m)
        assert ei.value.rule == "schema_version"


def test_tls_values_parse_in_their_three_forms_and_never_off():
    assert mf.parse_tls_value("verify") == mf.Tls()
    pem = "-----BEGIN CERTIFICATE-----\nMIIB\n-----END CERTIFICATE-----\n"
    assert mf.parse_tls_value({"ca_pem": pem}) == mf.Tls(ca_pem=pem)
    pin = "ab" * 32
    assert mf.parse_tls_value({"cert_sha256": pin}) == mf.Tls(cert_sha256=pin)
    for off in ("off", False, "none", "insecure", {"verify": False}, {"verify": "false"}):
        with pytest.raises(ManifestError) as ei:
            mf.parse_tls_value(off)
        assert ei.value.rule == "tls_off"
    for bad in (
        None,
        {},
        {"cert_sha256": "xy"},
        {"ca_pem": "a", "cert_sha256": pin},
        {"ca_pem": "not a certificate"},
        5,
        "other",
    ):
        with pytest.raises(ManifestError) as ei:
            mf.parse_tls_value(bad)
        assert ei.value.rule == "bad_type"


PEM = "-----BEGIN CERTIFICATE-----\nMIIB\n-----END CERTIFICATE-----\n"


@pytest.mark.parametrize(
    "kwargs",
    [
        {"ca_pem": PEM, "cert_sha256": "ab" * 32},  # two forms at once
        {"ca_pem": "MIIB"},  # not a PEM certificate
        {"ca_pem": ""},
        {"cert_sha256": "ab" * 31},  # 62 hex
        {"cert_sha256": "zz" * 32},  # not hex
        {"cert_sha256": "ab" * 32 + "\n"},
    ],
)
def test_tls_built_directly_holds_exactly_one_valid_form(kwargs):
    # S32 carry from Task 2's review: the HTTP client trusts a Tls value as given, so a Tls
    # built in code (not through parse_tls_value) must not carry two forms or a malformed one.
    with pytest.raises(ManifestError) as ei:
        mf.Tls(**kwargs)
    assert ei.value.rule == "bad_type"


def test_tls_built_directly_accepts_each_single_form():
    assert mf.Tls().ca_pem is None and mf.Tls().cert_sha256 is None
    assert mf.Tls(ca_pem=PEM).ca_pem == PEM
    assert mf.Tls(cert_sha256="AB" * 32).cert_sha256 == "AB" * 32


def test_frozen_dataclasses():
    m = parse_manifest(copy.deepcopy(reference()))
    with pytest.raises(AttributeError):
        m.name = "other"  # type: ignore[misc]


def test_check_fetch_item_enforces_the_raw_cap_in_utf8_bytes():
    m = parse_manifest(reference())
    ok = {"external_id": "1", "kind": "alert"}
    mf.check_fetch_item(m, {**ok, "raw": "a" * mf.MAX_RAW_BYTES})
    # one more byte, and a multi-byte char that is 1 char but 2 bytes
    for raw in ("a" * (mf.MAX_RAW_BYTES + 1), "a" * (mf.MAX_RAW_BYTES - 1) + "\u00e9"):
        with pytest.raises(ManifestError) as ei:
            mf.check_fetch_item(m, {**ok, "raw": raw})
        assert (ei.value.rule, ei.value.path) == ("description_too_long", "raw")
    with pytest.raises(ManifestError) as ei:
        mf.check_fetch_item(m, {**ok, "raw": {"x": 1}})
    assert (ei.value.rule, ei.value.path) == ("bad_type", "raw")


def test_check_fetch_item_refuses_a_non_dict_item():
    m = parse_manifest(reference())
    for item in ([], "x", None, 5):
        with pytest.raises(ManifestError) as ei:
            mf.check_fetch_item(m, item)  # type: ignore[arg-type]
        assert ei.value.rule == "bad_type"
