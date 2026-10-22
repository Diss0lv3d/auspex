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
