"""Safe result encoding: what a handler returns, as bytes the queue can store (S32, spec 6).

`encode_result` is the SDK's half of "what a result may carry" (Hunaiza's call): it refuses
to emit what Postgres JSONB or the core cannot hold, naming the path of the offending value
(`$.items[0].title`), instead of letting the queue fail later:

- NaN and +/-Infinity (not JSON; `allow_nan=False` is the backstop);
- `\\x00` in any string or key (JSONB refuses it);
- a lone surrogate (not encodable as UTF-8);
- a non-string dict key, and any object JSON cannot carry (bytes, sets, datetimes, ...);
- a cycle.

A tuple becomes a list (S31's `_clean_json` gap). The bytes are canonical: sorted keys,
compact separators, UTF-8. The core validates again against the command's output schema
before storing anything (D-062); that check is S33's.
"""

import json
import math
import re
from typing import Any

_IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


class ResultError(ValueError):
    """A handler's result cannot be carried. `.path` says where (`$` is the result itself)."""

    def __init__(self, path: str, message: str) -> None:
        self.path = path
        super().__init__(f"{path}: {message}")


def _key_path(path: str, key: str) -> str:
    return f"{path}.{key}" if _IDENT.fullmatch(key) else f"{path}[{json.dumps(key)}]"


def _string(s: str, path: str) -> str:
    # The plain value first, through the base type's own slot: a subclass's __str__ (an Enum
    # member's "E.OPEN") or __contains__ must not decide what is checked or written.
    s = str.__str__(s)
    if "\x00" in s:
        raise ResultError(path, "a string may not hold \\x00")
    try:
        s.encode("utf-8")
    except UnicodeEncodeError:
        raise ResultError(path, "a string must be valid Unicode (a lone surrogate)") from None
    return s


def _clean(v: Any, path: str, open_ids: set[int]) -> Any:
    if v is None or v is True or v is False:
        return v
    if isinstance(v, int):
        return int.__int__(v)  # the plain int (an IntEnum member is its value)
    if isinstance(v, float):
        f = float.__float__(v)  # the plain float, whatever a subclass's __float__ says
        if not math.isfinite(f):
            raise ResultError(path, f"{f!r} is not a JSON number")
        return f
    if isinstance(v, str):
        return _string(v, path)
    if isinstance(v, (list, tuple, dict)):
        if id(v) in open_ids:
            raise ResultError(path, "the result contains itself (a cycle)")
        open_ids.add(id(v))
        try:
            if isinstance(v, dict):
                out = {}
                for k, item in v.items():
                    if not isinstance(k, str):
                        raise ResultError(path, f"a key must be a string, not {type(k).__name__}")
                    kp = _key_path(path, k)
                    out[_string(k, kp)] = _clean(item, kp, open_ids)
                return out
            return [_clean(item, f"{path}[{i}]", open_ids) for i, item in enumerate(v)]
        finally:
            open_ids.discard(id(v))
    raise ResultError(path, f"{type(v).__name__} cannot be carried in JSON")


def encode_result(value: Any) -> bytes:
    """Canonical JSON bytes for a handler's result, or ResultError naming the bad path."""
    try:
        clean = _clean(value, "$", set())
    except RecursionError:
        raise ResultError("$", "the result is nested too deeply") from None
    try:
        text = json.dumps(
            clean, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
        )
        return text.encode("utf-8")
    except (ValueError, UnicodeEncodeError) as exc:  # a backstop: _clean should have caught it
        raise ResultError("$", f"cannot be encoded: {exc}") from None
