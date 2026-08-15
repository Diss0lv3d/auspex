"""S18 Step 0 — lead 3: four clauses now decide whether a quiet digest may be
believed. Execute the matrix.

    if not self.checkers:                                       -> False   (1)
    if any(c.degraded ...):                                     -> False   (2)
    if any(c.consecutive_failures and not c.ever_succeeded):    -> False   (3)
    return any(c.ever_succeeded ...)                                       (4)

The named questions: does a healthy `ingest-cycle` MASK a degraded consumer?
What does ingest-DISABLED report? Is clause 3 too eager on a transient that heals?
"""

import sys

sys.path.insert(0, ".")

from auspex.checks import DEGRADED_AFTER, CheckerStatus, FailureCounter
from auspex.timeline.types import Digest


def st(name, *, fails=0, ever=False, err=None):
    return CheckerStatus(
        name=name,
        consecutive_failures=fails,
        degraded=fails >= DEGRADED_AFTER,
        last_error=err,
        ever_succeeded=ever,
    )


def digest(*checkers):
    from datetime import UTC, datetime, timedelta

    now = datetime.now(UTC)
    return Digest(
        since=now - timedelta(days=7), now=now,
        matches=(), flips=(), contradicted=(), decayed=(),
        checkers=tuple(checkers),
    )


def row(label, *checkers, expect=None):
    d = digest(*checkers)
    got = d.trustworthy
    verdict = ""
    if expect is not None:
        verdict = "  <-- AS EXPECTED" if got == expect else "  <<<< SURPRISE"
    roster = ", ".join(
        f"{c.name}(f={c.consecutive_failures},ever={c.ever_succeeded},deg={c.degraded})"
        for c in checkers
    ) or "(empty roster)"
    print(f"  quiet={d.quiet}  trustworthy={str(got):>5}  {label}{verdict}")
    print(f"      roster: {roster}")
    return got


print("=" * 78)
print("MATRIX — may a quiet digest be believed?")
print("=" * 78)

print("\n-- the baseline cases S17 fixed --")
row("no roster at all (ingest disabled / not started)", expect=False)
row("healthy cycle counter only", st("ingest-cycle", ever=True), expect=True)
row("crash loop: cycle failing, never succeeded",
    st("ingest-cycle", fails=1, ever=False, err="ConnectionError"), expect=False)
row("3 restarts' worth of failure but a past success",
    st("ingest-cycle", fails=2, ever=True, err="ConnectionError"), expect=True)
row("degraded (>=3 consecutive)",
    st("ingest-cycle", fails=DEGRADED_AFTER, ever=True), expect=False)

print("\n-- Q1: does a healthy ingest-cycle MASK a degraded consumer? --")
row("cycle healthy + watchers DEGRADED",
    st("watchers", fails=DEGRADED_AFTER, ever=True), st("ingest-cycle", ever=True),
    expect=False)
row("cycle healthy + watchers failing but under the threshold",
    st("watchers", fails=DEGRADED_AFTER - 1, ever=True), st("ingest-cycle", ever=True),
    expect=True)
print("      ^ intended: DEGRADED_AFTER tolerates a bad batch AMONG SUCCESSES")

print("\n-- Q1b: the consumer that has NEVER RUN (0 failures, 0 successes) --")
got = row("cycle healthy + a consumer that never ran at all",
          st("retrohunt", fails=0, ever=False), st("ingest-cycle", ever=True))
print("      clause (3) needs consecutive_failures to be TRUTHY, so a checker that")
print("      never ran contributes nothing; clause (4) is ANY, so the cycle vouches.")
print(f"      => a never-run consumer is reported as believable: trustworthy={got}")

print("\n-- Q2: ingest DISABLED --")
sched_disabled_roster = (st("ingest-cycle", fails=0, ever=False),)
row("scheduler exists, disabled, no cycle ever ran", *sched_disabled_roster, expect=False)
print("      (checker_health ALWAYS appends ingest-cycle, so the roster is never")
print("       empty when a scheduler exists — clause (1) fires only with no scheduler)")

print("\n-- Q3: is clause (3) too eager? a first-cycle transient that then heals --")
c = FailureCounter("ingest-cycle")
print(f"  fresh process            -> trustworthy={digest(c.status).trustworthy}")
c.failed(TimeoutError())
print(f"  cycle 1 fails (transient)-> trustworthy={digest(c.status).trustworthy}")
c.succeeded()
print(f"  cycle 2 succeeds         -> trustworthy={digest(c.status).trustworthy}  "
      f"(heals immediately, not sticky)")
c.failed(TimeoutError())
c.failed(TimeoutError())
print(f"  then 2 more failures     -> trustworthy={digest(c.status).trustworthy}  "
      f"(tolerated: there is a success to weigh against)")

print("\n-- Q4: can a roster of ONLY never-run checkers ever read as believable? --")
row("two consumers that never ran + a cycle that never ran",
    st("retrohunt"), st("watchers"), st("ingest-cycle"), expect=False)
print("      clause (4) saves it: nothing ever succeeded -> False")
