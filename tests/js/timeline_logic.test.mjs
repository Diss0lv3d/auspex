// The timeline page's pure logic (S16, S17), run under Node's built-in test
// runner: no dependencies, no browser. It imports the module the page itself
// imports. tests/test_timeline_logic.py runs this file inside the pytest gate.
//
//   node --test tests/js/timeline_logic.test.mjs
import assert from "node:assert/strict";
import { test } from "node:test";
import {
  count, pct, conf, claimStatusClass, standingClass, digestBanner, labelClass,
} from "../../auspex/static/js/timeline-logic.js";

const rows = (n) => Array.from({ length: n }, () => ({}));
const digest = (over = {}) => ({
  quiet: false, trustworthy: true, complete: true, limit: 50,
  checkers: [{ name: "retrohunt", degraded: false }], truncated: [],
  reopened: [], flipped: [], contradicted: [], decayed: [], ...over,
});

test("a list the server did not cut is stated as its length", () => {
  assert.equal(count(digest({ decayed: rows(3) }), "decayed"), "3");
});

test("a list the server cut is stated as a floor, never a total (S17)", () => {
  assert.equal(count(digest({ decayed: rows(50), truncated: ["decayed"] }), "decayed"), "at least 50");
});

test("a cut on one list does not make another list a floor", () => {
  const d = digest({ decayed: rows(50), reopened: rows(2), truncated: ["decayed"] });
  assert.equal(count(d, "reopened"), "2");
});

test("pct turns a confidence into a bar width, clamped to 0..100", () => {
  assert.equal(pct(0), 0);
  assert.equal(pct(1), 100);
  assert.equal(pct(0.456), 46);
  assert.equal(pct(-0.2), 0);
  assert.equal(pct(1.7), 100);
});

test("a missing confidence is an empty bar, not NaN", () => {
  for (const x of [null, undefined, NaN, "0.5"]) assert.equal(pct(x), 0, String(x));
});

test("conf shows a confidence to two places", () => {
  assert.equal(conf(0.5), "0.50");
  assert.equal(conf(0), "0.00");
});

test("a missing confidence reads as a dash instead of throwing", () => {
  for (const x of [null, undefined, NaN]) assert.equal(conf(x), "—", String(x));
});

test("a claim's status picks its colour", () => {
  assert.equal(claimStatusClass("satisfied"), "malicious");
  assert.equal(claimStatusClass("superseded"), "slate");
  assert.equal(claimStatusClass("registered"), "benign");
});

test("a lapsed standing is slate, anything else fresh", () => {
  assert.equal(standingClass("lapsed"), "slate");
  assert.equal(standingClass("standing"), "fresh");
});

test("a quiet week is reassuring only when everything was watching", () => {
  assert.deepEqual(digestBanner(digest({ quiet: true, trustworthy: true })), {
    kind: "ok",
    text: "Nothing re-scored your past this week — and everything that would have noticed was running.",
  });
});

test("a quiet week with a degraded checker is not evidence", () => {
  const d = digest({ quiet: true, trustworthy: false, checkers: [{ name: "retrohunt", degraded: true }] });
  assert.deepEqual(digestBanner(d), {
    kind: "warn",
    text: "Nothing to report, but this silence is not evidence: a checker is degraded.",
  });
});

test("a quiet week with nothing watching says so", () => {
  const d = digest({ quiet: true, trustworthy: false, checkers: [] });
  assert.deepEqual(digestBanner(d), {
    kind: "warn",
    text: "Nothing to report, but this silence is not evidence: nothing was watching.",
  });
});

test("an active week counts each list", () => {
  const d = digest({ reopened: rows(1), flipped: rows(2), contradicted: rows(3), decayed: rows(4) });
  assert.deepEqual(digestBanner(d), {
    kind: "warn",
    text: "Your past got re-scored. 1 re-opened · 2 changed label · 3 claims contradicted · 4 went stale.",
  });
});

test("an active week the server cut states floors and says how to see the rest", () => {
  const d = digest({ complete: false, decayed: rows(50), truncated: ["decayed"] });
  assert.deepEqual(digestBanner(d), {
    kind: "warn",
    text: "Your past got re-scored. 0 re-opened · 0 changed label · 0 claims contradicted · at least 50 went stale."
      + " Showing the first 50 of each — widen the page to see the rest.",
  });
});

test("a pill's class is one the stylesheet knows, or slate; a feed label cannot add classes", () => {
  for (const known of ["malicious", "suspicious", "benign", "unknown", "fresh", "aging", "stale", "lapsed", "held", "slate"]) {
    assert.equal(labelClass(known), known);
  }
  assert.equal(labelClass("benign current"), "slate");
  assert.equal(labelClass("x onclick"), "slate");
  assert.equal(labelClass(undefined), "slate");
});
