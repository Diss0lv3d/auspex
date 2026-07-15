"""Tool registry level + spec tests (S3 step 2). Pure, offline."""

import pytest

from auspex.agent.registry import ToolLevel, ToolRegistry


async def _noop(args: dict) -> dict:
    return {"ok": True, "echo": args}


def _registry() -> ToolRegistry:
    reg = ToolRegistry()
    reg.add("lookup_ip", "Look up IP reputation.",
            {"ip": {"type": "string"}}, ["ip"], ToolLevel.READ, _noop)
    reg.add("create_ticket", "Create an incident ticket.",
            {"title": {"type": "string"}}, ["title"], ToolLevel.WRITE, _noop)
    reg.add("quarantine_host", "Isolate a host from the network.",
            {"hostname": {"type": "string"}}, ["hostname"], ToolLevel.DESTRUCTIVE, _noop)
    return reg


def test_levels_are_recorded_and_queryable():
    reg = _registry()
    assert reg.level("lookup_ip") is ToolLevel.READ
    assert reg.level("create_ticket") is ToolLevel.WRITE
    assert reg.level("quarantine_host") is ToolLevel.DESTRUCTIVE
    assert reg.level("nope") is None  # unknown tool → no level


def test_all_three_levels_exist_and_are_distinct():
    values = {level.value for level in ToolLevel}
    assert values == {"read", "write", "destructive"}


def test_spec_is_valid_openai_envelope():
    reg = _registry()
    spec = reg.get("lookup_ip").spec
    assert spec["type"] == "function"
    assert spec["function"]["name"] == "lookup_ip"
    params = spec["function"]["parameters"]
    assert params["type"] == "object"
    assert params["properties"] == {"ip": {"type": "string"}}
    assert params["required"] == ["ip"]


def test_specs_offers_all_by_default_and_subset_on_request():
    reg = _registry()
    assert {s["function"]["name"] for s in reg.specs()} == {
        "lookup_ip", "create_ticket", "quarantine_host"
    }
    subset = reg.specs(["lookup_ip"])
    assert [s["function"]["name"] for s in subset] == ["lookup_ip"]


def test_specs_ignores_unknown_names():
    reg = _registry()
    assert reg.specs(["lookup_ip", "ghost_tool"]) == reg.specs(["lookup_ip"])


def test_duplicate_registration_rejected():
    reg = _registry()
    with pytest.raises(ValueError, match="already registered"):
        reg.add("lookup_ip", "dup", {}, [], ToolLevel.READ, _noop)


def test_get_unknown_returns_none_membership_and_len():
    reg = _registry()
    assert reg.get("ghost") is None
    assert "lookup_ip" in reg
    assert "ghost" not in reg
    assert len(reg) == 3


async def test_read_handler_executes():
    reg = _registry()
    tool = reg.get("lookup_ip")
    assert tool.level is ToolLevel.READ
    assert await tool.handler({"ip": "203.0.113.7"}) == {"ok": True, "echo": {"ip": "203.0.113.7"}}
