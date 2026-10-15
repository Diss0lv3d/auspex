"""Scorecard logic: mode decision thresholds, fingerprint stability, persistence."""

import asyncpg
from _tenancy import ensure_workspace

from auspex.db import create_pool
from auspex.llm.scorecard import (
    CapabilityScorecard,
    decide_agent_mode,
    endpoint_fingerprint,
    load_latest_scorecard,
    save_scorecard,
)


def _sc(**kw) -> CapabilityScorecard:
    kw.setdefault("reachable", True)
    return CapabilityScorecard(base_url="http://example.test", model="m", **kw)


def test_unreachable_is_plan_only():
    assert decide_agent_mode(_sc(reachable=False)) == "plan_only"


def test_native_tools_with_good_rates():
    sc = _sc(native_tool_calling=True, valid_call_rate=0.95, loop_completion_rate=0.85)
    assert decide_agent_mode(sc) == "native_tools"


def test_native_tools_unmeasured_rates_trusts_native_support():
    """Connect-time probe (no harness numbers yet) must not demote a native endpoint."""
    assert decide_agent_mode(_sc(native_tool_calling=True)) == "native_tools"


def test_bad_valid_call_rate_demotes_to_prompted():
    sc = _sc(native_tool_calling=True, valid_call_rate=0.50, json_object_mode=True)
    assert decide_agent_mode(sc) == "prompted_tools"


def test_bad_loop_completion_demotes():
    sc = _sc(
        native_tool_calling=True,
        valid_call_rate=0.95,
        loop_completion_rate=0.10,
        json_object_mode=True,
    )
    assert decide_agent_mode(sc) == "prompted_tools"


def test_no_tools_no_json_is_plan_only():
    assert decide_agent_mode(_sc()) == "plan_only"


def test_schema_adherence_alone_earns_prompted():
    assert decide_agent_mode(_sc(schema_adherence_rate=0.9)) == "prompted_tools"


def test_fingerprint_stable_and_keyless():
    a = endpoint_fingerprint("http://example.test/", "m1")
    b = endpoint_fingerprint("http://example.test", "m1")
    assert a == b, "trailing slash must not change identity"
    assert a != endpoint_fingerprint("http://example.test", "m2")
    assert len(a) == 64


async def test_scorecard_roundtrip_in_postgres(client, settings):
    """save → load returns the same typed scorecard and the derived mode."""
    pool = await create_pool(settings.database_url, retries=2, delay=0.5)
    conn = await asyncpg.connect(settings.database_url)
    try:
        workspace_id = await ensure_workspace(conn, "t-sc-roundtrip")
        sc = _sc(
            native_tool_calling=True,
            native_reasoning=True,
            valid_call_rate=0.9,
            tokens_per_second=42.5,
        )
        await save_scorecard(pool, workspace_id, sc)
        loaded = await load_latest_scorecard(pool, workspace_id, sc.base_url, sc.model)
        assert loaded is not None
        got, mode = loaded
        assert got == sc
        assert got.native_reasoning is True  # new field survives the jsonb round-trip
        assert mode == "native_tools"
    finally:
        await conn.execute("DELETE FROM workspaces WHERE name = 't-sc-roundtrip'")
        await conn.close()
        await pool.close()


def test_native_reasoning_defaults_false():
    assert _sc().native_reasoning is False
