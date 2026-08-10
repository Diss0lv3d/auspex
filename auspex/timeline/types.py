"""Verdict timeline types — S16 (Living Verdicts, Phase 3).

A verdict's life has been written down since S5 and readable nowhere. Four
tables already hold it, each built for its own question:

* `verdicts`     — the append-only trail (D-017), with the decay parameters
* `verdict_flips`— S14: what changed, and what prompted the re-look
* `retrohunt_matches` — S14: what intel re-opened a settled question
* `watchers`     — S15: what the verdict committed to being wrong about, and
                   which of those claims have since been contradicted

Nothing in this module writes. It is a reading of rows that already exist plus
arithmetic that was already pinned by a test — which is the point: if rendering
a verdict's history required storing something new, the history was not really
being kept.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from auspex.checks import CheckerStatus
from auspex.retrohunt.types import RetroHuntMatch, VerdictFlip
from auspex.timeline.staleness import Staleness, Standing
from auspex.watchers.types import Watcher


@dataclass(frozen=True)
class DecayedVerdict:
    """One row of the trail with its decay worked out at read time.

    `confidence_at_write` is what the platform asserted; `confidence_now` is
    what it still asserts. S5 wrote both semantics and only ever surfaced the
    first, so every consumer has been reading a month-old belief at full
    strength."""

    id: UUID
    label: str
    confidence_at_write: float
    confidence_now: float
    floor: float
    half_life_days: float
    half_lives_elapsed: float
    staleness: Staleness
    source: str
    created_at: datetime
    # True for the newest row only — "the current verdict" is a position in the
    # trail, not a column, and S15 Step 0 found what happens when the two
    # disagree.
    current: bool


@dataclass(frozen=True)
class StandingClaim:
    """A registered falsification condition, with the S16 answer to whether it
    still carries weight (see staleness.Standing). `standing` is None for
    claims that are no longer open — a contradicted or superseded claim is a
    historical fact, and asking how much weight it carries is the wrong
    question."""

    watcher: Watcher
    standing: Standing | None


@dataclass(frozen=True)
class VerdictTimeline:
    """Everything the platform knows about how it came to believe what it
    believes about one observable."""

    workspace_id: UUID
    observable_id: UUID
    obs_id: str
    type: str
    value: str
    trail: tuple[DecayedVerdict, ...]  # newest first
    flips: tuple[VerdictFlip, ...]
    matches: tuple[RetroHuntMatch, ...]
    claims: tuple[StandingClaim, ...]

    @property
    def current(self) -> DecayedVerdict | None:
        return self.trail[0] if self.trail else None


@dataclass(frozen=True)
class Decayed:
    """A verdict that crossed a staleness band while nobody was looking.

    The only item in the digest that is not an event someone else recorded:
    nothing writes a row when a verdict goes stale, because staleness is the
    passage of time rather than something that happened. It is computed from
    the same curve at two instants — `was` at the cutoff, `now` today."""

    observable_id: UUID
    obs_id: str
    type: str
    value: str
    label: str
    was: Staleness
    now: Staleness
    confidence_at_write: float
    confidence_now: float
    half_lives_elapsed: float
    created_at: datetime


@dataclass(frozen=True)
class Digest:
    """"Your past got re-scored" — what changed since `since`.

    `checkers` carries the status of the things that would have PRODUCED the
    other four fields (auspex/checks.py). It is not decoration: when this digest
    comes back empty, every other field is an absence claim, and an absence
    claim is only worth as much as the thing that looked."""

    since: datetime
    now: datetime
    matches: tuple[RetroHuntMatch, ...]  # new intel re-opened these
    flips: tuple[VerdictFlip, ...]  # these labels actually changed
    contradicted: tuple[Watcher, ...]  # claims that stopped being true
    decayed: tuple[Decayed, ...]  # these went stale by themselves
    checkers: tuple[CheckerStatus, ...]
    # The page size these four lists were cut to, and which of them had more
    # rows waiting (S17 Step 0). Field names are this dataclass's own; the route
    # translates them into the names its payload gives the same lists.
    limit: int = 0
    truncated: tuple[str, ...] = ()

    @property
    def quiet(self) -> bool:
        return not (self.matches or self.flips or self.contradicted or self.decayed)

    @property
    def complete(self) -> bool:
        """Whether these lists are all of it. A quiet digest is trivially
        complete; a busy one is only complete if nothing was cut."""
        return not self.truncated

    @property
    def trustworthy(self) -> bool:
        """Whether "nothing happened" may be rendered as reassurance.

        Requires checkers to be present AND healthy. An empty roster is the
        honest answer when ingest is disabled or has not started: nothing was
        watching, so quiet is not evidence of quiet. Defaulting an unknown
        roster to trustworthy would be the same mistake in a nicer place.

        S17 Step 0 executed the two ways a pristine-looking roster lies, both
        rooted in `FailureCounter` living in the process rather than the
        database (auspex/checks.py):

        * **Nothing has run yet.** A freshly started process reports every
          checker at zero failures. Zero failures out of zero attempts is not
          health, so a roster where NOTHING has ever succeeded cannot support an
          absence claim. Measured: a process that had run no cycle at all
          reported `quiet=True, trustworthy=True`.
        * **The counter forgets across restarts.** A crash-looping app fails its
          checks every single cycle and never reaches `DEGRADED_AFTER`, because
          the count resets before it gets there. Measured: three restarts, every
          cycle failing, `degraded=False` and `trustworthy=True` throughout. So
          a checker whose only evidence in this process is failure is treated as
          untrustworthy at the FIRST failure — `DEGRADED_AFTER` exists to
          tolerate a bad batch among successes, and with no successes there is
          nothing to tolerate it against.

        Both live here rather than in `CheckerStatus.degraded`, which stays the
        breaker-shaped fact it has always been: this property is the one that
        makes a claim, so it is the one that has to be careful. What is still
        NOT caught is a checker that succeeded and then stopped being run at all
        — `ever_succeeded` never expires — which needs a heartbeat with a
        timestamp behind it (TD-022).

        `ever_succeeded` alone would have been too strict, and that is why the
        scheduler counts completed CYCLES (`ingest-cycle`): a consumer only
        records success when a relevant change actually arrives, so in a quiet
        week nothing but the cycle counter can prove the platform is alive."""
        if not self.checkers:
            return False
        if any(c.degraded for c in self.checkers):
            return False
        # Failure with nothing to weigh it against — see the second case above.
        if any(c.consecutive_failures and not c.ever_succeeded for c in self.checkers):
            return False
        return any(c.ever_succeeded for c in self.checkers)
