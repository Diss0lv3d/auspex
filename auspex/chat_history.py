"""What a stored chat replays (F2): its title and its turns.

Pure: the routes in auspex/routes/chat.py fetch the rows and this pairs them,
so the pairing is tested on plain rows (tests/test_chat_history.py). Spec:
docs/superpowers/specs/2026-10-12-chat-survives-reload-design.md.

A question opens a turn, and the turn runs until the next question. Only one
link is an exact key: a ledger row names its answer (`turn_spend.message_id`).
A turn that stored no answer, and every proposal, is placed by time (TD-050).
Reasoning and tool lines were never stored, so nothing here can return them.
"""

from __future__ import annotations

import json
from bisect import bisect_right
from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any

TITLE_MAX = 80


def title_of(question: str | None) -> str:
    """A chat's title: its first question with the whitespace collapsed, cut at
    TITLE_MAX characters. Collapsed, not first-line: a pasted JSON alert's first
    line is "{"."""
    text = " ".join((question or "").split())
    if len(text) <= TITLE_MAX:
        return text
    return text[: TITLE_MAX - 1].rstrip() + "…"


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _json(value: Any) -> Any:
    return json.loads(value) if isinstance(value, str) else value


def _spend(row: Mapping) -> dict:
    return {
        "engine_calls": row["engine_calls"],
        "prompt_tokens": row["prompt_tokens"],
        "completion_tokens": row["completion_tokens"],
        "ending": row["ending"],
    }


def _proposal(row: Mapping) -> dict:
    """Only what the page words a status from (the panel's statusText), never
    the whole stored result."""
    card = _json(row["card"]) or {}
    result = _json(row["result"])
    return {
        "id": str(row["id"]),
        "action": row["tool_name"],
        "summary": card.get("summary"),
        "status": row["status"],
        "decided_at": _iso(row["decided_at"]),
        "claimed_at": _iso(row["claimed_at"]),
        "result": {"effects": result.get("effects") if isinstance(result, dict) else None},
    }


def pair_turns(
    messages: Sequence[Mapping],
    spend: Sequence[Mapping],
    proposals: Sequence[Mapping],
) -> list[dict]:
    turns: list[dict] = []
    starts: list[datetime] = []
    answer_ids: dict[Any, int] = {}
    for m in messages:
        if m["role"] == "user":
            turns.append({"question": m["content"], "asked_at": _iso(m["created_at"]),
                          "answer": None, "spend": None, "proposals": []})
            starts.append(m["created_at"])
        elif m["role"] == "assistant" and turns and turns[-1]["answer"] is None:
            turns[-1]["answer"] = m["content"]
            answer_ids[m["id"]] = len(turns) - 1

    def turn_at(when: datetime) -> int | None:
        i = bisect_right(starts, when) - 1
        return i if i >= 0 else None

    for row in spend:
        if row["message_id"] is not None:
            i = answer_ids.get(row["message_id"])
        else:
            i = turn_at(row["created_at"])
            if i is not None and turns[i]["answer"] is not None:
                i = None  # an answered turn's row names its answer
        if i is not None and turns[i]["spend"] is None:
            turns[i]["spend"] = _spend(row)

    for row in proposals:
        i = turn_at(row["created_at"])
        if i is not None:
            turns[i]["proposals"].append(_proposal(row))
    return turns
