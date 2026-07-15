"""Test doubles for the agent loop — no live LLM, no DB (CI stays hermetic).

`FakeLLMClient` replays a scripted list of ChatResults in order and records the
message list it was called with each turn, so tests can assert what got fed
back. `InMemoryProposalStore` captures gated proposals without Postgres.
"""

from collections.abc import AsyncIterator
from typing import Any

from auspex.agent.permissions import ProposalStore
from auspex.llm.client import ChatResult, LLMError, StreamEvent


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
