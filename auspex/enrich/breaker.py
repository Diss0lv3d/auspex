"""Per-provider circuit breaker — S5.

Consecutive-failure threshold opens the circuit; after a cooldown the breaker
goes half-open and admits probe calls until one settles: a success closes the
circuit, a failure re-opens it (fresh cooldown). The clock is injectable so
tests never sleep.

Concurrency note: the fan-out launches one task per (provider, observable), so
several calls for one provider can be in flight when the first failure lands.
`record_failure` while already open only refreshes the cooldown; `allow()` in
half-open admits every caller until a result settles the state — an accepted
soft spot (a burst of probes, not one) in exchange for lock-free simplicity.
"""

import time
from collections.abc import Callable


class CircuitBreaker:
    def __init__(
        self,
        *,
        threshold: int = 3,
        cooldown_seconds: float = 60.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if threshold < 1:
            raise ValueError("threshold must be >= 1")
        self._threshold = threshold
        self._cooldown = cooldown_seconds
        self._clock = clock
        self._consecutive_failures = 0
        self._opened_at: float | None = None

    @property
    def state(self) -> str:
        if self._opened_at is None:
            return "closed"
        if self._clock() - self._opened_at >= self._cooldown:
            return "half_open"
        return "open"

    def allow(self) -> bool:
        return self.state != "open"

    def record_success(self) -> None:
        self._consecutive_failures = 0
        self._opened_at = None

    def record_failure(self) -> None:
        self._consecutive_failures += 1
        if self._consecutive_failures >= self._threshold:
            self._opened_at = self._clock()
