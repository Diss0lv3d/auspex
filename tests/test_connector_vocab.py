"""S32: the SDK's vocabulary is pinned equal to the core's.

The SDK is a separate distribution that must never import the core, so it restates the
core's closed vocabularies. This test is the one place both are imported, and it fails the
moment either side drifts. It also proves `auspex_sdk` imports beside the core (R1).
"""

from auspex_sdk.vocab import CONNECTOR_ID, PARAM_TYPES, RISKS, WIRE_NAME
from auspex_sdk.vocab import PLATFORM_KEYWORDS as SDK_PLATFORM_KEYWORDS

from auspex.actions.types import _WIRE_NAME, PLATFORM_KEYWORDS, ParamType
from auspex.agent.registry import ToolLevel


def test_the_sdk_vocabulary_equals_the_cores():
    assert set(RISKS) == {level.value for level in ToolLevel}
    assert set(PARAM_TYPES) == {t.value for t in ParamType}
    assert WIRE_NAME.pattern == _WIRE_NAME.pattern
    assert SDK_PLATFORM_KEYWORDS == PLATFORM_KEYWORDS


def test_connector_id_shape():
    assert CONNECTOR_ID.fullmatch("acme.vt_lookup")
    assert CONNECTOR_ID.fullmatch("com.acme.edr")
    for bad in ("acme", "Acme.x", "acme.", "1acme.x", "acme.x-y", "acme.x\n"):
        assert not CONNECTOR_ID.fullmatch(bad), bad


def test_the_tool_name_budget():
    """S32 Task 8 fix: the core has no tool-name length constant of its own, so the
    SDK's is the only one (compile.py imports it). A compiled name is
    `<prefix>__<action>`; the two caps must leave a valid tool name."""
    from auspex_sdk.manifest import MAX_ACTION_NAME
    from auspex_sdk.vocab import MAX_PREFIX, MAX_TOOL_NAME

    from auspex.connectors import compile as compile_mod

    assert MAX_TOOL_NAME == 64
    assert MAX_PREFIX + len("__") + MAX_ACTION_NAME == MAX_TOOL_NAME
    assert compile_mod.MAX_TOOL_NAME is MAX_TOOL_NAME
    assert compile_mod.MAX_PREFIX is MAX_PREFIX
