"""A chat survives a reload (F2): the list and the turns a stored chat replays.

Spec: docs/superpowers/specs/2026-10-12-chat-survives-reload-design.md. The
pairing is pure (auspex/chat_history.py) and tested on plain rows here; the
routes are tested against Postgres further down, with rows inserted directly,
so nothing in this file spends inference.
"""

import json
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from auspex.chat_history import TITLE_MAX, pair_turns, title_of

T0 = datetime(2026, 10, 12, 9, 0, tzinfo=UTC)


def at(minutes: float) -> datetime:
    return T0 + timedelta(minutes=minutes)


def msg(role: str, content: str, minutes: float) -> dict:
    return {"id": uuid4(), "role": role, "content": content, "created_at": at(minutes)}


def ledger(minutes: float, *, message_id=None, calls=1, prompt=10, completion=4, ending="stop"):
    return {"message_id": message_id, "engine_calls": calls, "prompt_tokens": prompt,
            "completion_tokens": completion, "ending": ending, "created_at": at(minutes)}


def filed(minutes: float, *, status="pending_approval", summary="Attach a note", result=None):
    return {"id": uuid4(), "tool_name": "annotate_observable", "status": status,
            "card": {"summary": summary}, "decided_at": None, "claimed_at": None,
            "result": result, "created_at": at(minutes)}


# -- the title ------------------------------------------------------------------


def test_a_title_is_the_first_question_with_its_whitespace_collapsed():
    pasted = '\n  {"rule": {"name": "Suspicious PowerShell"},\n   "host": "fin-ws-12"}\n'
    assert title_of(pasted) == '{"rule": {"name": "Suspicious PowerShell"}, "host": "fin-ws-12"}'
    assert title_of("check 8.8.8.8") == "check 8.8.8.8"
    assert title_of("   ") == "" and title_of(None) == ""


def test_a_long_title_is_cut_at_eighty_characters():
    title = title_of("word " * 40)
    assert len(title) == TITLE_MAX == 80
    assert title.endswith("…") and not title.endswith(" …")
    assert title_of("x" * 80) == "x" * 80  # exactly the limit is not cut


# -- the pairing ----------------------------------------------------------------


def test_an_answered_turn_gets_its_own_ledger_row():
    q, a = msg("user", "what is T1059?", 0), msg("assistant", "An answer.", 1)
    [turn] = pair_turns([q, a], [ledger(1, message_id=a["id"], calls=3)], [])
    assert turn == {
        "question": "what is T1059?",
        "asked_at": at(0).isoformat(),
        "answer": "An answer.",
        "spend": {"engine_calls": 3, "prompt_tokens": 10, "completion_tokens": 4, "ending": "stop"},
        "proposals": [],
    }


def test_a_failed_turns_row_lands_under_its_own_question():
    """The ledger row of a turn that stored no answer has no message_id: it is
    placed by time, inside its own question's window and nobody else's."""
    q1, a1 = msg("user", "one", 0), msg("assistant", "first", 1)
    q2 = msg("user", "two", 2)
    q3, a3 = msg("user", "three", 4), msg("assistant", "third", 5)
    rows = [ledger(1, message_id=a1["id"]), ledger(3, ending="endpoint_error", calls=2),
            ledger(5, message_id=a3["id"])]
    turns = pair_turns([q1, a1, q2, q3, a3], rows, [])
    assert [t["answer"] for t in turns] == ["first", None, "third"]
    assert [t["spend"]["ending"] for t in turns] == ["stop", "endpoint_error", "stop"]
    assert turns[1]["spend"]["engine_calls"] == 2


def test_a_shortcut_answer_has_no_spend():
    """D-054 records deep turns only, so a shortcut answer has no row."""
    [turn] = pair_turns([msg("user", "8.8.8.8", 0), msg("assistant", "No signal.", 0.5)], [], [])
    assert turn["answer"] == "No signal." and turn["spend"] is None


def test_each_proposal_lands_under_the_turn_that_filed_it():
    q1, a1, q2 = msg("user", "one", 0), msg("assistant", "first", 1), msg("user", "two", 2)
    p1, p2 = filed(0.5, status="executed"), filed(2.5)
    turns = pair_turns([q1, a1, q2], [], [p1, p2])
    assert [p["id"] for p in turns[0]["proposals"]] == [str(p1["id"])]
    assert [p["id"] for p in turns[1]["proposals"]] == [str(p2["id"])]
    assert turns[0]["proposals"][0]["status"] == "executed"


def test_a_proposal_carries_only_what_the_panel_words_its_status_from():
    """The page words a status with the panel's statusText, which reads status,
    decided_at, claimed_at and result.effects; nothing else of the result is
    served. A row as asyncpg returns it holds jsonb as a JSON string."""
    p = filed(0.5, status="incomplete")
    p["card"] = json.dumps({"summary": "Attach a note to ipv4 203.0.113.9"})
    p["result"] = json.dumps({"effects": "unknown", "error": "TimeoutError"})
    p["decided_at"] = at(0.6)
    [turn] = pair_turns([msg("user", "one", 0)], [], [p])
    assert turn["proposals"] == [{
        "id": str(p["id"]), "action": "annotate_observable",
        "summary": "Attach a note to ipv4 203.0.113.9", "status": "incomplete",
        "decided_at": at(0.6).isoformat(), "claimed_at": None,
        "result": {"effects": "unknown"},
    }]


def test_two_rows_without_an_answer_in_one_turn_take_the_first():
    q = msg("user", "one", 0)
    rows = [ledger(1, ending="output_guard"), ledger(2, ending="empty_answer")]
    [turn] = pair_turns([q], rows, [])
    assert turn["spend"]["ending"] == "output_guard"
