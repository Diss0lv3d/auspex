"""The streaming agent turn (S25, D-031) — `AgentLoop.run_stream`.

All against fakes: no live LLM, no DB, no route. Nothing here spends an
inference call, so the `usage_counters` refund discipline that governs
test_chat_sse.py does not apply — there is no counter to leave behind.

What these hold, and why each is easy to lose:

1. **The answer streams after the tool steps.** D-031 decision 1 rests on a
   measurement (a tool turn emits zero content before its tool calls), and the
   value of it is that the analyst never reads prose the tool results then
   contradict. A test that only checked "the answer arrived" would pass with the
   ordering inverted.
2. **Arguments are parsed only once the stream ends.** One IP was measured
   arriving as nine fragments split mid-token.
3. **Every model call is claimed.** A loop makes up to nine calls; the route used
   to claim one or two up front. Metering that gets this wrong is invisible until
   a workspace is over its ceiling.
4. **`run` and `run_stream` must not drift.** They answer the same question two
   ways; if their messages differ, so will their answers.
"""

import json

import pytest
from _fakes import InMemoryProposalStore, SequencedStreamingFakeLLMClient

from auspex.agent.loop import AgentLoop
from auspex.agent.registry import ToolLevel, ToolRegistry
from auspex.llm.client import StreamEvent, Usage

WORKSPACE = "00000000-0000-0000-0000-000000000001"


def _registry() -> tuple[ToolRegistry, list]:
    """One READ tool that records the ARGS IT RECEIVED — the parsed dict, which
    is what proves fragments were assembled before parsing."""
    seen: list[dict] = []
    reg = ToolRegistry()

    async def lookup_ip(args: dict) -> dict:
        seen.append(args)
        return {"ip": args.get("ip"), "reputation": "malicious", "score": 88}

    reg.add(
        name="lookup_ip",
        description="Look up an IP.",
        parameters={"ip": {"type": "string", "description": "the IP"}},
        required=["ip"],
        level=ToolLevel.READ,
        handler=lookup_ip,
    )
    return reg, seen


def _loop(registry, **over) -> AgentLoop:
    return AgentLoop(
        registry, InMemoryProposalStore(), mode="native_tools", workspace_id=WORKSPACE, **over
    )


def _tool_call_script(name="lookup_ip", args='{"ip": "203.0.113.99"}', *, chunks=1,
                      call_id="call_a"):
    """A tool-calling turn: tool_call deltas, then finish. No content, which is
    what the endpoint was measured to do (D-031).

    `call_id` is settable because a turn with two STEPS gets two distinct ids
    from a real endpoint, and a script that reuses one id compares unequal
    against any other path's replay for a reason that is the script's fault."""
    events = [
        StreamEvent(
            kind="tool_call", tool_index=0,
            tool_delta={"id": call_id, "function": {"name": name, "arguments": ""}},
        )
    ]
    size = max(1, len(args) // chunks)
    for i in range(0, len(args), size):
        events.append(
            StreamEvent(
                kind="tool_call", tool_index=0,
                tool_delta={"function": {"arguments": args[i : i + size]}},
            )
        )
    events.append(StreamEvent(kind="finish", finish_reason="tool_calls"))
    return events


def _answer_script(parts=("203.0.113.99 ", "is malicious ", "(score 88)."), usage=True):
    events = [StreamEvent(kind="content", text=p) for p in parts]
    events.append(StreamEvent(kind="finish", finish_reason="stop"))
    if usage:
        events.append(StreamEvent(kind="usage", usage=Usage(10, 20, 30)))
    return events


async def _drain(loop, client, message="check 203.0.113.99", **over):
    return [ev async for ev in loop.run_stream(client, message, **over)]


# -- the shape of the turn ----------------------------------------------------


async def test_the_tool_step_is_narrated_before_the_answer_streams():
    """D-031 decision 1. The ordering is the guarantee: a `tool` event resolves
    BEFORE any answer delta, so the analyst never reads a sentence the tool
    result then contradicts. Asserted as an ordering, not a membership test —
    `{"tool", "content"} <= set(kinds)` would pass with the order inverted."""
    registry, _ = _registry()
    client = SequencedStreamingFakeLLMClient([_tool_call_script(), _answer_script()])

    events = await _drain(_loop(registry), client)

    kinds = [e.kind for e in events]
    assert "tool" in kinds and "content" in kinds
    assert kinds.index("tool") < kinds.index("content"), kinds
    assert kinds[-1] == "done"

    tool_events = [e for e in events if e.kind == "tool"]
    assert len(tool_events) == 1
    assert tool_events[0].invocation.name == "lookup_ip"
    assert tool_events[0].invocation.status == "executed"


async def test_the_answer_arrives_as_deltas_not_one_blob():
    """The whole point of streaming. A coroutine that returned the ChatResult
    would buffer every delta until the call finished and still satisfy "the
    answer arrived" — so the floor is on the COUNT of content events (the S21
    lesson: an assertion over an extracted set needs a floor)."""
    registry, _ = _registry()
    parts = ("one ", "two ", "three ", "four ")
    client = SequencedStreamingFakeLLMClient([_answer_script(parts)])

    events = await _drain(_loop(registry), client)

    content = [e for e in events if e.kind == "content"]
    assert len(content) == len(parts) >= 4, f"answer did not stream: {len(content)} events"
    assert "".join(e.text for e in content) == "".join(parts)
    done = events[-1]
    assert done.kind == "done" and done.text == "".join(parts)
    assert done.stop_reason == "final_answer"


async def test_a_turn_needing_no_tool_streams_straight_through():
    """The control. If this emitted a tool event, the ordering assertion above
    would be measuring the script rather than the loop."""
    registry, seen = _registry()
    client = SequencedStreamingFakeLLMClient([_answer_script(("no tools needed.",))])

    events = await _drain(_loop(registry), client, "what is lateral movement?")

    assert [e.kind for e in events if e.kind == "tool"] == []
    assert seen == []
    assert client.turns == 1


# -- D-031 decision 2: fragments are assembled before anything is parsed ------


@pytest.mark.parametrize("chunks", [1, 4, 9])
async def test_arguments_split_mid_token_reach_the_handler_intact(chunks):
    """One IP was measured arriving as NINE fragments split mid-token. The
    handler must receive the PARSED dict, whole — the assertion is on what the
    tool actually got, not on the loop's internal state."""
    registry, seen = _registry()
    args = '{"ip": "203.0.113.99"}'
    client = SequencedStreamingFakeLLMClient(
        [_tool_call_script(args=args, chunks=chunks), _answer_script()]
    )

    await _drain(_loop(registry), client)

    assert seen == [{"ip": "203.0.113.99"}], f"{chunks} fragments did not reassemble"
    # And the replayed assistant message carries the whole argument string, so a
    # second step reasons from what was actually called.
    replay = json.dumps(client.stream_calls[1]["messages"])
    assert "203.0.113.99" in replay


# -- D-031 decision 4: the claim is per model call ----------------------------


async def test_every_model_call_is_claimed_not_just_the_turn():
    """A loop makes up to nine calls; the route claimed 1-2 up front. Two calls
    here (tool step + answer) must produce two claims — an equality, because
    `>= 1` would pass with the claim left outside the loop."""
    registry, _ = _registry()
    claims = []

    async def claim() -> bool:
        claims.append(1)
        return True

    client = SequencedStreamingFakeLLMClient([_tool_call_script(), _answer_script()])
    await _drain(_loop(registry), client, claim=claim)

    assert client.turns == 2
    assert len(claims) == client.turns == 2


async def test_a_refusal_before_the_first_call_makes_no_call_at_all():
    registry, _ = _registry()

    async def claim() -> bool:
        return False

    client = SequencedStreamingFakeLLMClient([_answer_script()])
    events = await _drain(_loop(registry), client, claim=claim)

    assert client.turns == 0, "the endpoint was called despite a refused claim"
    assert [e.kind for e in events] == ["done"]
    assert events[-1].stop_reason == "usage_refused"


async def test_a_refusal_mid_loop_keeps_what_was_already_gathered():
    """D-031 decision 4: a refusal synthesises from what was gathered rather
    than failing the turn. The tool step already streamed, so the analyst keeps
    the evidence even though the answer cannot be written."""
    registry, seen = _registry()
    allowed = [True, False]

    async def claim() -> bool:
        return allowed.pop(0)

    client = SequencedStreamingFakeLLMClient([_tool_call_script(), _answer_script()])
    events = await _drain(_loop(registry), client, claim=claim)

    assert client.turns == 1, "the second call was made against a refused claim"
    assert seen == [{"ip": "203.0.113.99"}]  # the tool DID run
    tool_events = [e for e in events if e.kind == "tool"]
    assert len(tool_events) == 1
    done = events[-1]
    assert done.kind == "done" and done.stop_reason == "usage_refused"
    assert len(done.invocations) == 1  # what was gathered, carried out


async def test_the_synthesis_pass_is_claimed_like_any_other_call():
    """The step cap's final pass is a model call the customer's endpoint serves.
    Claiming every step but not this one is how a loop costs max_steps+1 and
    charges max_steps."""
    registry, _ = _registry()
    claims = []

    async def claim() -> bool:
        claims.append(1)
        return True

    scripts = [_tool_call_script() for _ in range(2)] + [_answer_script(("summary.",))]
    client = SequencedStreamingFakeLLMClient(scripts)
    events = await _drain(_loop(registry, max_steps=2), client, claim=claim)

    assert client.turns == 3  # 2 steps + synthesis
    assert len(claims) == 3
    assert events[-1].stop_reason == "step_cap"
    assert events[-1].text == "summary."


async def test_a_loop_with_no_claim_still_runs():
    """`claim` is optional so the loop stays usable outside the metered route
    (probes, harnesses). Its absence must not silently disable the tool path."""
    registry, seen = _registry()
    client = SequencedStreamingFakeLLMClient([_tool_call_script(), _answer_script()])

    events = await _drain(_loop(registry), client)

    assert seen == [{"ip": "203.0.113.99"}]
    assert events[-1].stop_reason == "final_answer"


# -- D-031 decision 5: the rail indexes what the turn actually issued ---------


async def test_the_system_message_offered_for_indexing_is_the_one_sent():
    """The output rail indexes `system_message(...)`. If that string is not
    byte-identical to what went on the wire, the rail is indexing something the
    endpoint never saw — and D-030's guarantee is void."""
    registry, _ = _registry()
    loop = _loop(registry)
    client = SequencedStreamingFakeLLMClient([_answer_script()])

    await _drain(loop, client)

    sent = client.stream_calls[0]["messages"][0]
    assert sent["role"] == "system"
    assert sent["content"] == loop.system_message(loop.wire_specs())
    # It is not the bare prompt — the composed message carries the tool prefix,
    # which is exactly why the rail cannot index four fixed strings.
    assert loop.system_prompt in sent["content"]


async def test_the_tool_result_is_a_message_the_answer_can_be_built_from():
    """Tool results ride the conversation as data. The route leaves them
    UNINDEXED and scans them on their own channel (D-031 decision 5); this pins
    that they reach the model at all, which is the half the loop owns."""
    registry, _ = _registry()
    client = SequencedStreamingFakeLLMClient([_tool_call_script(), _answer_script()])

    await _drain(_loop(registry), client)

    second_call = client.stream_calls[1]["messages"]
    tool_messages = [m for m in second_call if m.get("role") == "tool"]
    assert len(tool_messages) == 1
    assert "malicious" in tool_messages[0]["content"]


# -- a turn that produced no answer must not claim it answered ----------------


async def test_a_turn_the_endpoint_never_answered_says_so():
    """S26 Step 0, measured. `run_stream` ended a turn `final_answer` whenever no
    tool calls came back — without asking whether an ANSWER came back.

    The realistic path is a THINKING MODEL: reasoning tokens count against
    `max_tokens`, so a model that thinks past its budget emits reasoning deltas,
    `finish_reason="length"`, and no content at all. The terminal state was then
    byte-identical to a complete answer's, and the route persists `done.text` as
    the assistant turn — so *nothing happened* would be stored and rendered as
    *the answer is nothing*.

    The control is the same script with ONE content delta added, so a passing
    subject cannot be explained by the harness."""
    registry, _ = _registry()
    thinking = [
        StreamEvent(kind="reasoning", text="Let me consider the indicators, and "),
        StreamEvent(kind="reasoning", text="whether enrichment would help here, and "),
        StreamEvent(kind="finish", finish_reason="length"),
    ]

    events = await _drain(_loop(registry), SequencedStreamingFakeLLMClient([thinking]))
    done = events[-1]
    assert [e.kind for e in events if e.kind == "content"] == [], "the control assumes no content"
    assert done.kind == "done"
    assert done.stop_reason == "empty_answer", (
        f"a turn with no answer reported {done.stop_reason!r}"
    )
    assert done.text == ""
    assert done.finish_reason == "length"  # why it stopped is still carried

    answered = [*thinking[:-1],
                StreamEvent(kind="content", text="203.0.113.99 is malicious."),
                StreamEvent(kind="finish", finish_reason="stop")]
    control = await _drain(_loop(registry), SequencedStreamingFakeLLMClient([answered]))
    assert control[-1].stop_reason == "final_answer", (
        "the control did not answer either — the subject proves nothing"
    )
    assert control[-1].text == "203.0.113.99 is malicious."


async def test_an_empty_synthesis_pass_does_not_claim_an_answer():
    """The step-cap pass can come back empty too, and `step_cap` also claims
    'here is the answer'. `step` still carries that the cap was reached, so
    naming the emptiness loses nothing."""
    registry, _ = _registry()
    scripts = [_tool_call_script() for _ in range(2)] + [[StreamEvent(kind="finish",
                                                                     finish_reason="length")]]
    client = SequencedStreamingFakeLLMClient(scripts)

    events = await _drain(_loop(registry, max_steps=2), client)

    done = events[-1]
    assert client.turns == 3, "the synthesis pass did not run"
    assert done.stop_reason == "empty_answer"
    assert done.step == 2, "the cap is still legible in `step`"
    assert len(done.invocations) == 2, "the evidence gathered is still carried out"


async def test_whitespace_is_not_an_answer():
    """A model that emits a newline and stops has answered nothing. Separate from
    the case above because `content` here is truthy — `if not text` would pass."""
    registry, _ = _registry()
    script = [StreamEvent(kind="content", text="  \n "),
              StreamEvent(kind="finish", finish_reason="stop")]
    client = SequencedStreamingFakeLLMClient([script])

    events = await _drain(_loop(registry), client)

    assert [e.kind for e in events if e.kind == "content"] == ["content"], (
        "the delta must still stream — this is about the TERMINAL STATE, not suppression"
    )
    assert events[-1].stop_reason == "empty_answer"


# -- anti-drift: the two turns are the same turn ------------------------------


async def test_run_and_run_stream_compose_the_same_messages():
    """They answer the same question two ways. If their system message or their
    tool specs differ, the streaming answer and the blocking answer differ — the
    exact drift `wire_specs`/`_initial_messages` were extracted to prevent.

    Compares EVERY call, not just the first. Only `wire_specs`/`_initial_messages`
    are shared: the two step loops are duplicated code, so they can agree on the
    opening message and still diverge where the divergence would matter most —
    on the replayed assistant/tool messages of a second step, or on the synthesis
    pass, which is the one call whose kwargs deliberately differ from the rest.

    Arithmetic first (S26 Step 0): the call COUNTS are asserted before the
    messages are compared, because a zipped comparison passes vacuously when one
    side made fewer calls."""
    from _fakes import FakeLLMClient

    from auspex.llm.client import ChatResult, ToolCall

    args = '{"ip": "203.0.113.99"}'

    def blocking_tool_step(call_id):
        return ChatResult(
            content="", finish_reason="tool_calls",
            tool_calls=[ToolCall(id=call_id, name="lookup_ip", arguments=args)],
        )

    registry, _ = _registry()
    # Two tool steps then the step-cap synthesis pass: 3 model calls each.
    streaming = SequencedStreamingFakeLLMClient([
        _tool_call_script(args=args, call_id="call_a"),
        _tool_call_script(args=args, call_id="call_b"),
        _answer_script(("summary.",)),
    ])
    blocking = FakeLLMClient([
        blocking_tool_step("call_a"), blocking_tool_step("call_b"),
        ChatResult(content="summary.", finish_reason="stop"),
    ])

    await _drain(_loop(registry, max_steps=2), streaming, "check 203.0.113.99")
    await _loop(registry, max_steps=2).run(blocking, "check 203.0.113.99")

    assert len(streaming.stream_calls) == len(blocking.calls) == 3, (
        "the two paths did not make three calls each, so comparing them pairwise "
        f"would compare different turns: {len(streaming.stream_calls)} vs {len(blocking.calls)}"
    )
    for i, (s, b) in enumerate(zip(streaming.stream_calls, blocking.calls, strict=True)):
        assert s["messages"] == b["messages"], f"call {i} diverged"
        # The synthesis pass offers no tools on either path; the steps offer them
        # on both. Compared because "same messages, different tools" is drift too.
        assert ("tools" in s["kwargs"]) == ("tools" in b["kwargs"]), f"call {i} tools differ"
    assert "tools" not in streaming.stream_calls[-1]["kwargs"], (
        "the synthesis pass offered tools — the control that makes call 2 "
        "distinguishable from calls 0 and 1 is gone"
    )


async def test_the_wire_specs_offered_are_the_registrys_tools():
    registry, _ = _registry()
    loop = _loop(registry)
    client = SequencedStreamingFakeLLMClient([_answer_script()])

    await _drain(loop, client)

    offered = client.stream_calls[0]["kwargs"].get("tools") or []
    assert [t["function"]["name"] for t in offered] == ["lookup_ip"]
