"""Tool registry with permission levels (S3, ROADMAP step 2).

Every tool carries a permission LEVEL (read/write/destructive) — the single
input the permission gate (auspex/agent/permissions.py, D-014) reads to decide
allow-vs-propose. The OpenAI function envelope is built with the shared
`tool_spec()` builder (auspex/llm/client.py) so the wire shape is identical to
what the capability probe and harness already exercise.

SARA pattern reference (reused, not copied): sara/core/permissions.py:25-42
(READ/WRITE/DESTRUCTIVE) and sara/tools/registry.py.

Tool-arg design note (S2 harness finding, docs/probes/2026-07-15-ollama-endpoint.md):
tools SHOULD take short observable IDs, never raw 64-char strings — every model
tested mangled long hashes in arguments. That is an authoring convention for the
real tools (S4/S5); the registry itself is content-agnostic.
"""

from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass
from enum import StrEnum

from auspex.llm.client import tool_spec

# A tool handler takes the parsed argument object and returns a JSON-serialisable
# result dict. Only READ handlers are ever invoked by the loop; write/destructive
# handlers exist for the eventual approved-execution path (S18), never auto-run.
ToolHandler = Callable[[dict], Awaitable[dict]]


class ToolLevel(StrEnum):
    """Permission class of a tool. Ordered least→most privileged.

    READ auto-executes; WRITE/DESTRUCTIVE are gated into proposals (D-014).
    str-valued so it serialises straight into proposal records / JSON.
    """

    READ = "read"
    WRITE = "write"
    DESTRUCTIVE = "destructive"


@dataclass(frozen=True)
class Tool:
    """One registered capability: its wire spec, its level, its executor."""

    name: str
    description: str
    parameters: dict[str, dict]  # JSON-schema `properties`
    required: list[str]
    level: ToolLevel
    handler: ToolHandler
    # TD-043: how many times one turn may call this tool. None is no budget of
    # its own (the loop's step cap still bounds it). Declared with the tool,
    # because whether a repeat call can find something new is a property of
    # what the tool looks up, not of the loop.
    max_calls_per_turn: int | None = None

    @property
    def spec(self) -> dict:
        """OpenAI function-tool envelope (the only shape the wire accepts)."""
        return tool_spec(self.name, self.description, self.parameters, self.required)


class ToolRegistry:
    """Name → Tool. Registration is explicit and duplicate-safe."""

    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> Tool:
        if tool.name in self._tools:
            raise ValueError(f"tool {tool.name!r} already registered")
        self._tools[tool.name] = tool
        return tool

    def add(
        self,
        name: str,
        description: str,
        parameters: dict[str, dict],
        required: list[str],
        level: ToolLevel,
        handler: ToolHandler,
        max_calls_per_turn: int | None = None,
    ) -> Tool:
        """Convenience constructor+register in one call."""
        return self.register(
            Tool(name, description, parameters, required, level, handler, max_calls_per_turn)
        )

    def get(self, name: str) -> Tool | None:
        """Resolve a called tool; None means the model named an unknown tool
        (the loop feeds that back as an error rather than crashing)."""
        return self._tools.get(name)

    def level(self, name: str) -> ToolLevel | None:
        tool = self._tools.get(name)
        return tool.level if tool else None

    def names(self) -> list[str]:
        return list(self._tools)

    def specs(self, names: Iterable[str] | None = None) -> list[dict]:
        """OpenAI tool envelopes to offer the model. `names=None` offers all;
        an explicit subset lets a caller scope which tools a turn may use.
        Unknown names are ignored (never fabricate a spec)."""
        selected = self._tools.values() if names is None else (
            self._tools[n] for n in names if n in self._tools
        )
        return [tool.spec for tool in selected]

    def __contains__(self, name: object) -> bool:
        return name in self._tools

    def __len__(self) -> int:
        return len(self._tools)
