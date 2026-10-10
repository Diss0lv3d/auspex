"""Capability probe: native_reasoning detection (S3.5/D-016). Hermetic — a fake
client drives the whole battery; no live LLM."""

from collections.abc import AsyncIterator

from auspex.llm.capability import probe_capabilities
from auspex.llm.client import ChatResult


class _ProbeFake:
    """Minimal LLMClient stand-in for the connect-time battery. The basic-chat
    probe (message contains 'pong') returns `basic_reasoning`; every other probe
    returns an empty ChatResult so the other capabilities read False."""

    def __init__(self, *, basic_reasoning: str = ""):
        self.base_url = "http://fake.test"
        self.model = "fake"
        self._basic_reasoning = basic_reasoning

    async def check_reachable(self) -> tuple[bool, str]:
        return True, "ok"

    async def chat(self, messages, **kwargs) -> ChatResult:
        blob = " ".join(m.get("content") or "" for m in messages)
        if "pong" in blob:
            return ChatResult(content="pong", reasoning=self._basic_reasoning, finish_reason="stop")
        return ChatResult(content="", finish_reason="stop")

    async def chat_stream(self, messages, **kwargs) -> AsyncIterator:
        return
        yield  # pragma: no cover — makes this an async generator


async def test_native_reasoning_detected_from_basic_probe():
    sc = await probe_capabilities(_ProbeFake(basic_reasoning="Hmm, let me think..."))
    assert sc.reachable is True
    assert sc.native_reasoning is True


async def test_native_reasoning_absent_when_no_reasoning_field():
    sc = await probe_capabilities(_ProbeFake(basic_reasoning=""))
    assert sc.reachable is True
    assert sc.native_reasoning is False


async def test_native_reasoning_detected_when_spelled_reasoning_content():
    """The same detection through the other spelling: a fake whose basic-probe
    answer is parsed from a Z.ai-shaped body, so the field name is the only
    difference from the test above."""
    from auspex.llm.client import LLMClient

    class _ZaiShaped(_ProbeFake):
        async def chat(self, messages, **kwargs) -> ChatResult:
            blob = " ".join(m.get("content") or "" for m in messages)
            if "pong" in blob:
                return LLMClient.parse_completion({"choices": [{"message": {
                    "content": "pong", "reasoning_content": "The user wants pong."}}]})
            return ChatResult(content="", finish_reason="stop")

    sc = await probe_capabilities(_ZaiShaped())
    assert sc.reachable is True
    assert sc.native_reasoning is True
