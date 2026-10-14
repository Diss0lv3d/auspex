// The timeline page's pure logic (S16, S17): no DOM, imported by the page
// (js/timeline.js) and by tests/js/timeline_logic.test.mjs. The page holds no
// decay arithmetic: a band is the server's `staleness`, rendered as given.

// A count the page is allowed to state. `truncated` names the lists the server
// cut at `limit`, and for those the length of what arrived is a floor, not a
// total — "50 went stale" when 32,930 did is a wrong answer, not a short one.
export function count(d, name) {
  const n = d[name].length;
  return d.truncated.includes(name) ? `at least ${n}` : `${n}`;
}

// A confidence as a bar width. A missing one is an empty bar, not "NaN%".
export function pct(x) {
  return Number.isFinite(x) ? Math.max(0, Math.min(100, Math.round(x * 100))) : 0;
}

// A confidence as written on the card. A missing one is a dash, not a throw
// that would take the whole timeline down with it.
export function conf(x) {
  return Number.isFinite(x) ? x.toFixed(2) : "—";
}

export function claimStatusClass(status) {
  if (status === "satisfied") return "malicious";
  if (status === "superseded") return "slate";
  return "benign";
}

export function standingClass(standing) {
  return standing === "lapsed" ? "slate" : "fresh";
}

// The reassuring version is only rendered when it can be believed.
export function digestBanner(d) {
  if (d.quiet) {
    if (d.trustworthy) {
      return {
        kind: "ok",
        text: "Nothing re-scored your past this week — and everything that would have noticed was running.",
      };
    }
    const why = d.checkers.length ? "a checker is degraded" : "nothing was watching";
    return { kind: "warn", text: `Nothing to report, but this silence is not evidence: ${why}.` };
  }
  const counts = `${count(d, "reopened")} re-opened · ${count(d, "flipped")} changed label · `
    + `${count(d, "contradicted")} claims contradicted · ${count(d, "decayed")} went stale.`;
  const cut = d.complete ? "" : ` Showing the first ${d.limit} of each — widen the page to see the rest.`;
  return { kind: "warn", text: `Your past got re-scored. ${counts}${cut}` };
}
