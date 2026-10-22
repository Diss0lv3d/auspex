"""The closed vocabularies a connector manifest is written in (S32).

The SDK is its own distribution and must never import the core, so these restate the
core's names. `tests/test_connector_vocab.py` pins each one equal to its core counterpart:
`ToolLevel` (auspex/agent/registry.py), `ParamType`, `_WIRE_NAME` and `PLATFORM_KEYWORDS`
(auspex/actions/types.py). Pure on purpose: stdlib `re` only.
"""

import re

# An action's risk is its permission level. Same three values as the core's ToolLevel.
RISKS: tuple[str, ...] = ("read", "write", "destructive")

# The JSON-schema primitives an action parameter may declare.
PARAM_TYPES: tuple[str, ...] = ("string", "integer", "number", "boolean")

# A tool/parameter name must survive the wire as-is. Use with fullmatch.
WIRE_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")

# A tool name on an OpenAI-compatible wire is at most this many characters. The core has
# no constant of its own: auspex.connectors.compile imports this one (S32, Task 8).
MAX_TOOL_NAME = 64

# The integration prefix of a compiled action's tool name `<prefix>__<action>` (spec
# decision 5). The manifest caps action names so that any legal prefix still fits.
MAX_PREFIX = 24

# Names the platform passes every handler itself; a manifest parameter may not shadow them.
PLATFORM_KEYWORDS = frozenset({"workspace_id", "proposal_id", "idempotency_key"})

# A connector id: a lowercase vendor segment, then one or more dotted name segments.
# Use with fullmatch (no core counterpart).
CONNECTOR_ID = re.compile(r"^[a-z][a-z0-9]*(\.[a-z][a-z0-9_]*)+$")
