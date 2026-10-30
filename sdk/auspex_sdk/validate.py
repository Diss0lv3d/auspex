"""What each connector command must return, checked (S33; D-062: core code validates
every result before anything stores it, shows it or hands it to the model).

One copy, shared: the harness checks a local run with it, the core checks what an Edge
Agent posts with it. Pure on purpose: it imports only `auspex_sdk.manifest`, so the core
may import it (tests/test_connector_structure.py).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from auspex_sdk.manifest import Action, Manifest, ManifestError, check_fetch_item


class ResultInvalid(ValueError):
    """A command's result breaks the contract. The message says how."""


def check_test(r: Any) -> None:
    if not (isinstance(r, dict) and set(r) == {"ok", "detail"}):
        raise ResultInvalid("test must return exactly {ok, detail}")
    if not isinstance(r["ok"], bool) or not isinstance(r["detail"], str):
        raise ResultInvalid("test: ok is a bool and detail a string")


def check_fetch(m: Manifest, r: Any) -> None:
    if not (isinstance(r, dict) and set(r) == {"items", "next_cursor"}):
        raise ResultInvalid("fetch must return exactly {items, next_cursor}")
    if not isinstance(r["items"], list):
        raise ResultInvalid("fetch: items is a list")
    if r["next_cursor"] is not None and not isinstance(r["next_cursor"], str):
        raise ResultInvalid("fetch: next_cursor is a string or None")
    for i, item in enumerate(r["items"]):
        try:
            check_fetch_item(m, item)
        except ManifestError as e:
            raise ResultInvalid(f"fetch: items[{i}]: {e.message}") from e


OUTPUT_OK: dict[str, Callable[[Any], bool]] = {
    "string": lambda v: isinstance(v, str),
    "integer": lambda v: isinstance(v, int) and not isinstance(v, bool),
    "number": lambda v: isinstance(v, int | float) and not isinstance(v, bool),
    "boolean": lambda v: isinstance(v, bool),
    "string[]": lambda v: isinstance(v, list | tuple) and all(isinstance(s, str) for s in v),
}


def check_envelope(a: Action, step: str, r: Any) -> None:
    if not (isinstance(r, dict) and set(r) == {"would", "affects", "reversible", "detail"}):
        raise ResultInvalid(
            f"{a.name}.{step} must return exactly {{would, affects, reversible, detail}}"
        )
    if not isinstance(r["would"], str):
        raise ResultInvalid(f"{a.name}.{step}: would is a string")
    if not isinstance(r["affects"], list | tuple) or not all(
        isinstance(s, str) for s in r["affects"]
    ):
        raise ResultInvalid(f"{a.name}.{step}: affects is a list of strings")
    if not isinstance(r["reversible"], bool):
        raise ResultInvalid(f"{a.name}.{step}: reversible is a bool")
    detail = r["detail"]
    if not isinstance(detail, dict):
        raise ResultInvalid(f"{a.name}.{step}: detail is an object")
    declared = {o.name: o for o in a.output}
    for key in detail:
        if key not in declared:
            raise ResultInvalid(
                f"{a.name}.{step}: detail.{key} is not declared in the action's output"
            )
    for name, o in declared.items():
        if name not in detail:
            if o.required:
                raise ResultInvalid(f"{a.name}.{step}: detail.{name} is required and missing")
            continue
        if detail[name] is None and not o.required:
            continue
        if not OUTPUT_OK[o.type](detail[name]):
            raise ResultInvalid(f"{a.name}.{step}: detail.{name} is not a {o.type}")


def check_observe(a: Action, r: Any) -> None:
    if isinstance(r, bool) or not isinstance(r, int) or r < 0:
        raise ResultInvalid(f"{a.name}.observe must return a non-negative integer")


__all__ = ["OUTPUT_OK", "ResultInvalid", "check_envelope", "check_fetch", "check_observe",
           "check_test"]
