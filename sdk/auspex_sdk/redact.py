"""Log redaction: a logging filter that replaces resolved secret values (S32, spec section 9).

A connector's config holds secrets the agent resolved (D-063). Connector code logs; this
filter makes sure no secret value leaves a log record. It replaces each secret, and its
URL-encoded, base64, repr-escaped and JSON-escaped forms, with `[secret:<name>]` in:

- the message, after its %-args are merged (the record then carries no args), so a secret
  split across msg and args, or inside a dict arg's repr, is still caught;
- the exception text: the traceback is rendered here, redacted into `exc_text`, and
  `exc_info` is dropped, so no later handler can render the raw exception again;
- `stack_info`;
- every `extra=` attribute: a string is redacted in place; any other value whose str() or
  repr() holds a secret is replaced by its redacted str().

A secret shorter than MIN_SECRET_LEN is refused (ValueError naming the secret, never its
value): replacing "abc" everywhere would shred the logs, and not replacing it would leak it.
Base64 is matched only as the encoding of the whole secret on its own; a secret inside a
larger encoded blob (`user:password` in Basic auth) is not found by substring. Do not log
encoded credentials.

A filter attached to a logger sees only records logged on that logger: `Context` attaches it
to `ctx.log`, the logger handlers are given.
"""

import base64
import json
import logging
import re
import weakref
from collections.abc import Mapping
from urllib.parse import quote, quote_plus

MIN_SECRET_LEN = 4

# Attributes every LogRecord has; anything else on a record came in through `extra=`.
_STANDARD = frozenset(vars(logging.makeLogRecord({}))) | {"message", "asctime"}
_PLAIN = (int, float, bool, type(None))


def _forms(value: str) -> set[str]:
    raw = value.encode("utf-8")
    forms = {
        value,
        quote(value, safe=""),
        quote(value, safe="/:@!$&'()*+,;="),  # a URL path as httpx writes it (RFC 3986 pchar)
        quote_plus(value, safe=""),
        repr(value)[1:-1],
        json.dumps(value)[1:-1],
    }
    for enc in (base64.b64encode(raw), base64.urlsafe_b64encode(raw)):
        text = enc.decode("ascii")
        forms.update({text, text.rstrip("=")})
    return {f for f in forms if len(f) >= MIN_SECRET_LEN}


class RedactingFilter(logging.Filter):
    """Replaces secret values in a record with `[secret:<name>]`. Never drops a record."""

    def __init__(self, secrets: Mapping[str, str | None]) -> None:
        super().__init__()
        names: dict[str, str] = {}
        for name, value in secrets.items():
            if value is None:
                continue
            if not isinstance(value, str):
                raise TypeError(f"secret {name!r} must be a string")
            if len(value) < MIN_SECRET_LEN:
                raise ValueError(
                    f"secret {name!r} is shorter than {MIN_SECRET_LEN} characters: "
                    "too short to redact from logs safely"
                )
            for form in _forms(value):
                names.setdefault(form, name)
        self._names = names
        # Longest first, so a secret that contains another is replaced whole.
        self._pattern = (
            re.compile("|".join(re.escape(f) for f in sorted(names, key=len, reverse=True)))
            if names
            else None
        )

    def redact(self, text: str) -> str:
        if self._pattern is None:
            return text
        return self._pattern.sub(lambda m: f"[secret:{self._names[m.group(0)]}]", text)

    def _hit(self, text: str) -> bool:
        return self._pattern is not None and self._pattern.search(text) is not None

    def filter(self, record: logging.LogRecord) -> bool:
        if self._pattern is None:
            return True
        try:
            message = record.getMessage()
        except Exception:  # a broken format string: keep both halves, redacted
            message = f"{record.msg} {record.args!r}"
        record.msg = self.redact(str(message))
        record.args = None
        if record.exc_info:
            text = record.exc_text or logging.Formatter().formatException(record.exc_info)
            record.exc_text = self.redact(text)
            record.exc_info = None
        elif record.exc_text:
            record.exc_text = self.redact(record.exc_text)
        if record.stack_info:
            record.stack_info = self.redact(record.stack_info)
        for key, value in list(vars(record).items()):
            if key in _STANDARD or isinstance(value, _PLAIN):
                continue
            if isinstance(value, str):
                setattr(record, key, self.redact(value))
                continue
            try:
                text, rep = str(value), repr(value)
            except Exception:
                setattr(record, key, "[unprintable]")
                continue
            if self._hit(text) or self._hit(rep):
                setattr(record, key, self.redact(text))
        return True


def redacting_filter(secrets: dict[str, str]) -> logging.Filter:
    """A filter that redacts these secrets ({name: resolved value}) from every record."""
    return RedactingFilter(secrets)


# PR #43 review #9: httpx (and httpcore beneath it) log each request on their own
# loggers, the URL with its query string included, so a filter on `ctx.log` alone
# missed them. One shared filter sits on those loggers and applies every live
# context's redactor; the set is weak, so a finished run's secrets leave with it, and
# the shared loggers never gather a filter per run.
LIBRARY_LOGGERS = ("httpx", "httpcore.connection", "httpcore.http11", "httpcore.http2",
                   "httpcore.proxy", "httpcore.socks")
_LIVE: weakref.WeakSet[logging.Filter] = weakref.WeakSet()


class _LibraryRedactor(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        for redactor in list(_LIVE):
            redactor.filter(record)
        return True


_LIBRARY_REDACTOR = _LibraryRedactor()


def redact_library_logs(redactor: logging.Filter) -> None:
    """Apply `redactor` to the HTTP library's own log records while it lives."""
    _LIVE.add(redactor)
    for name in LIBRARY_LOGGERS:
        lib = logging.getLogger(name)
        if _LIBRARY_REDACTOR not in lib.filters:
            lib.addFilter(_LIBRARY_REDACTOR)
