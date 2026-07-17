"""Test doubles for the agent loop — no live LLM, no DB (CI stays hermetic).

`FakeLLMClient` replays a scripted list of ChatResults in order and records the
message list it was called with each turn, so tests can assert what got fed
back. `InMemoryProposalStore` captures gated proposals without Postgres.
"""

from collections.abc import AsyncIterator
from typing import Any

from auspex.agent.permissions import ProposalStore
from auspex.llm.client import ChatResult, LLMError, StreamEvent

# One canonical list for the brand rule (engine never named in user-visible
# strings, D-002/CLAUDE.md) — imported by test_ui, test_models, test_shortcuts
# so a newly-added provider name can't leak through a stale copy.
FORBIDDEN_ENGINE_NAMES = [
    "qwen",
    "ollama",
    "llama",
    "vllm",
    "northflank",
    "gpt",
    "openai",
    "scout",
    "nvidia",
    "claude",
    "anthropic",
    "mistral",
    "deepseek",
]


class FakeLLMClient:
    """Duck-typed LLMClient: exposes the one method the loop calls, `chat()`."""

    def __init__(self, scripted: list[ChatResult]):
        self._scripted = list(scripted)
        self.calls: list[dict[str, Any]] = []  # one record per chat() invocation

    async def chat(self, messages: list[dict], **kwargs: Any) -> ChatResult:
        self.calls.append({"messages": [dict(m) for m in messages], "kwargs": kwargs})
        if not self._scripted:
            raise AssertionError("FakeLLMClient ran out of scripted responses")
        return self._scripted.pop(0)

    @property
    def turns(self) -> int:
        return len(self.calls)

    def last_messages(self) -> list[dict]:
        return self.calls[-1]["messages"]


class StreamingFakeLLMClient:
    """Duck-typed LLMClient for the SSE endpoint: `chat_stream` replays scripted
    StreamEvents; set `raise_error` to simulate an endpoint failure mid-stream."""

    def __init__(self, events: list[StreamEvent], *, raise_error: LLMError | None = None):
        self._events = list(events)
        self._raise_error = raise_error
        self.closed = False
        self.stream_calls: list[dict[str, Any]] = []

    async def chat_stream(self, messages: list[dict], **kwargs: Any) -> AsyncIterator[StreamEvent]:
        self.stream_calls.append({"messages": [dict(m) for m in messages], "kwargs": kwargs})
        for event in self._events:
            yield event
        if self._raise_error is not None:
            raise self._raise_error

    async def aclose(self) -> None:
        self.closed = True

    @property
    def turns(self) -> int:
        return len(self.stream_calls)

    def last_messages(self) -> list[dict]:
        return self.stream_calls[-1]["messages"]


class SequencedStreamingFakeLLMClient:
    """Like StreamingFakeLLMClient but takes a LIST of scripts (one per
    chat_stream call) so the two-pass reasoning path can script pass-1 then
    pass-2 distinctly. Records every call's messages/kwargs in `stream_calls`."""

    def __init__(self, scripts: list[list[StreamEvent]], *, raise_on_call: int | None = None):
        self._scripts = [list(s) for s in scripts]
        self._raise_on_call = raise_on_call  # 0-indexed call that raises LLMError
        self.closed = False
        self.stream_calls: list[dict[str, Any]] = []

    async def chat_stream(self, messages: list[dict], **kwargs: Any) -> AsyncIterator[StreamEvent]:
        idx = len(self.stream_calls)
        self.stream_calls.append({"messages": [dict(m) for m in messages], "kwargs": kwargs})
        if self._raise_on_call == idx:
            raise LLMError(500, "simulated endpoint failure")
        script = self._scripts[idx] if idx < len(self._scripts) else []
        for event in script:
            yield event

    async def aclose(self) -> None:
        self.closed = True


class FakeEnrichmentService:
    """Duck-typed EnrichmentService for the chat route (S5): scripted outcome,
    records the observables each turn asked about, never touches the network."""

    def __init__(self, outcome: Any, coverage: dict | None = None, *, active: bool = True):
        self.outcome = outcome
        self.coverage = coverage or {}
        self.active = active
        self.enrich_calls: list[tuple] = []

    async def enrich(self, observables: tuple) -> Any:
        self.enrich_calls.append(observables)
        return self.outcome

    async def aclose(self) -> None:
        pass


class FakeKnowledgeService:
    """Duck-typed KnowledgeService for the chat route (S6): scripted hits,
    records what each turn asked, never touches OpenSearch. Set
    `unavailable` to make every call raise KBUnavailable (KB down, not off)."""

    def __init__(self, hits: list | None = None, *, active: bool = True, unavailable: bool = False):
        self.hits = hits or []
        self.active = active
        self.unavailable = unavailable
        self.lookup_calls: list[tuple] = []
        self.lookup_topks: list[int] = []  # top_k per lookup_ids call, in order
        self.search_calls: list[str] = []

    def _answer(self) -> list:
        if self.unavailable:
            from auspex.kb import KBUnavailable

            # Diagnostic message vs analyst-facing public clause, like the real
            # service — chat tests assert the PUBLIC one is what gets rendered.
            raise KBUnavailable(
                "knowledge base unreachable: SimulatedConnectError",
                public="it was unreachable",
            )
        return self.hits

    async def lookup_ids(self, ids: tuple, *, top_k: int = 8) -> list:
        self.lookup_calls.append(ids)
        self.lookup_topks.append(top_k)
        return self._answer()

    async def search(self, query: str, *, top_k: int = 5) -> list:
        self.search_calls.append(query)
        return self._answer()

    async def aclose(self) -> None:
        pass


class InMemoryProposalStore(ProposalStore):
    """Records proposals in a list; returns a synthetic id."""

    def __init__(self) -> None:
        self.proposals: list[dict[str, Any]] = []

    async def create(
        self,
        *,
        workspace_id: Any,
        tool_name: str,
        tool_level: str,
        tool_input: dict,
        session_id: Any = None,
    ) -> str:
        proposal_id = f"prop-{len(self.proposals) + 1}"
        self.proposals.append(
            {
                "id": proposal_id,
                "workspace_id": str(workspace_id),
                "session_id": str(session_id) if session_id is not None else None,
                "tool_name": tool_name,
                "tool_level": tool_level,
                "tool_input": tool_input,
                "status": "pending_approval",
            }
        )
        return proposal_id
