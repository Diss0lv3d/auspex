"""Is a background checker alive, or just quiet? — S16.

Both ingest consumers swallow their own exceptions on purpose: intel landing in
the KB matters more than either of them, so a failed sweep or a failed watcher
check must never take an ingest cycle down. `FanoutSink` then swallows again, so
one consumer cannot sink another. The posture is right and stays.

What S16 Step 0 executed is the cost nobody had priced. Fifty consecutive
cycles with the watcher check failing every time produced fifty stack traces in
the log and **an analyst-facing surface identical to fifty quiet cycles**: the
same open claims, the same events, the same empty `falsifies`. A checker that
died on Tuesday and a checker with nothing to do are the same shape.

That matters more here than in most places, because the falsification surfaces
make ABSENCE claims. "No claim of yours has been contradicted" is only true if
something looked. This module is the smallest thing that lets a surface tell the
difference, and it deliberately does not change the swallow-and-continue
posture — it only counts.

Shape borrowed from `auspex/enrich/breaker.py` (consecutive failures, threshold,
reset on success), minus the circuit: there is nothing to trip. A checker that
keeps failing should keep trying — its next attempt costs one indexed query, and
the alternative is a checker that stops watching without being asked to.
"""

from __future__ import annotations

from dataclasses import dataclass

# Three in a row before a checker is called degraded, matching the breaker's
# default. One failure is a bad batch (a feed hiccup, a lock timeout); three
# consecutive is a thing that is not working.
DEGRADED_AFTER = 3


@dataclass(frozen=True)
class CheckerStatus:
    """What is known about a checker's last few attempts.

    `last_error` is the exception's TYPE NAME and never its message: an
    exception raised while checking a watcher can carry an observable value, and
    tenant data does not belong in a status payload (org data-handling rule —
    the same reason both sinks log counts rather than values)."""

    name: str
    consecutive_failures: int
    degraded: bool
    last_error: str | None
    # False until the checker has completed one attempt without failing. A
    # process that has only just started has not yet earned "healthy", and
    # saying so is cheaper than a surface quietly assuming it.
    ever_succeeded: bool


class FailureCounter:
    """Consecutive-failure tracking for one checker. Not thread-safe and does
    not need to be: the scheduler runs one cycle at a time."""

    def __init__(self, name: str, *, degraded_after: int = DEGRADED_AFTER) -> None:
        if degraded_after < 1:
            raise ValueError("degraded_after must be >= 1")
        self._name = name
        self._degraded_after = degraded_after
        self._consecutive = 0
        self._last_error: str | None = None
        self._ever_succeeded = False

    def succeeded(self) -> None:
        self._consecutive = 0
        self._last_error = None
        self._ever_succeeded = True

    def failed(self, exc: BaseException) -> None:
        self._consecutive += 1
        self._last_error = type(exc).__name__

    @property
    def status(self) -> CheckerStatus:
        return CheckerStatus(
            name=self._name,
            consecutive_failures=self._consecutive,
            degraded=self._consecutive >= self._degraded_after,
            last_error=self._last_error,
            ever_succeeded=self._ever_succeeded,
        )
