// The chat page's own pacing and indicator logic (D-052), run under Node's
// built-in test runner: no dependencies, no browser. The logic is read from
// auspex/static/index.html itself, between its `// <page-logic>` markers, so
// what is tested is what the page runs. tests/test_page_logic.py runs this
// file inside the pytest gate.
//
//   node --test tests/js/page_logic.test.mjs
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

const html = readFileSync(new URL("../../auspex/static/index.html", import.meta.url), "utf8");
const block = html.match(/\/\/ <page-logic>([\s\S]*?)\/\/ <\/page-logic>/);
assert.ok(block, "index.html has no // <page-logic> block");
const { createPacer, indicatorText } = new Function(
  `${block[1]}; return { createPacer, indicatorText };`,
)();

const FRAME_MS = 1000 / 60;

// Drive a pacer the way the page does: frames arrive at given times, and an
// animation frame takes from it every FRAME_MS. Returns each released piece
// with the time it was released.
function run(arrivals, { until = 2000 } = {}) {
  const pacer = createPacer();
  const released = [];
  const pending = [...arrivals].sort((a, b) => a.at - b.at);
  for (let now = 0; now <= until; now += FRAME_MS) {
    while (pending.length && pending[0].at <= now) {
      const { at, frame } = pending.shift();
      pacer.push(frame, at);
    }
    for (const piece of pacer.take(now, FRAME_MS)) released.push({ now, piece });
  }
  return released;
}

// A glm-4.5-air burst as measured at F1: ~25 small reasoning deltas in one
// network read, then silence.
const burst = (at, n = 25, text = "word ") =>
  Array.from({ length: n }, () => ({ at, frame: { reasoning: text } }));

test("no text waits longer than 200 ms between arriving and being released", () => {
  const arrivals = [...burst(0), ...burst(40), ...burst(1500, 60, "longer words ")];
  const released = run(arrivals);
  // Per character: release order is arrival order, so walk the arrivals.
  const times = [];
  for (const { now, piece } of released) for (let i = 0; i < piece.reasoning.length; i++) times.push(now);
  const arrivedAt = [];
  for (const { at, frame } of arrivals) for (let i = 0; i < frame.reasoning.length; i++) arrivedAt.push(at);
  assert.equal(times.length, arrivedAt.length, "every character is released");
  const worst = Math.max(...times.map((t, i) => t - arrivedAt[i]));
  assert.ok(worst <= 200, `a character waited ${worst.toFixed(1)} ms`);
});

test("a burst is spread over several frames, not painted in one", () => {
  const released = run(burst(0));
  const firstFrame = released.filter((r) => r.now === released[0].now);
  const firstChars = firstFrame.reduce((n, r) => n + r.piece.reasoning.length, 0);
  assert.ok(firstChars < 125 / 4, `the first frame released ${firstChars} of 125 characters`);
  assert.ok(new Set(released.map((r) => r.now)).size >= 5, "released over fewer than 5 frames");
});

test("frames come out in the order they arrived, text joined back intact", () => {
  const arrivals = [
    { at: 0, frame: { reasoning: "Look it up. " } },
    { at: 0, frame: { status: { phase: "tool", tool: "search_knowledge" } } },
    { at: 5, frame: { tool: { name: "search_knowledge", status: "executed", call: "q" } } },
    { at: 5, frame: { reasoning: "Found it." } },
    { at: 10, frame: { content: "The answer." } },
  ];
  const out = run(arrivals).map((r) => r.piece);
  const kinds = out.map((p) => Object.keys(p)[0]).filter((k, i, a) => k !== a[i - 1]);
  assert.deepEqual(kinds, ["reasoning", "status", "tool", "reasoning", "content"]);
  const text = (k) => out.filter((p) => k in p).map((p) => p[k]).join("");
  assert.equal(text("reasoning"), "Look it up. Found it.");
  assert.equal(text("content"), "The answer.");
});

test("a frame that is not text is released as soon as the text before it is", () => {
  const pacer = createPacer();
  pacer.push({ tool: { name: "lookup_cve", status: "executed", call: "x" } }, 0);
  assert.deepEqual(pacer.take(0, FRAME_MS).map((p) => Object.keys(p)[0]), ["tool"]);
});

test("flush releases everything still queued, in order, at once", () => {
  const pacer = createPacer();
  pacer.push({ reasoning: "a".repeat(500) }, 0);
  pacer.push({ content: "answer" }, 0);
  pacer.push({ done: { finish_reason: "stop" } }, 0);
  pacer.take(0, FRAME_MS);
  const out = pacer.flush();
  assert.deepEqual(out.map((p) => Object.keys(p)[0]), ["reasoning", "content", "done"]);
  assert.deepEqual(pacer.flush(), [], "a flushed pacer holds nothing");
});

// -- the working indicator ---------------------------------------------------

test("the indicator shows from Send, before anything has arrived", () => {
  assert.equal(indicatorText({ sentAt: 1000 }, 1000), "Thinking · 0 s");
  assert.equal(indicatorText({ sentAt: 1000 }, 3600), "Thinking · 2 s");
});

test("the indicator hides while text is arriving", () => {
  const turn = { sentAt: 0, lastPaintAt: 5000, status: { phase: "engine" }, statusAt: 100 };
  assert.equal(indicatorText(turn, 5900), null);
});

test("after a second of silence it returns, counting from when the silence began", () => {
  const turn = { sentAt: 0, lastPaintAt: 5000, status: { phase: "engine" }, statusAt: 100 };
  assert.equal(indicatorText(turn, 7400), "Thinking · 2 s");
});

test("a wait on a tool names the tool in our words, and counts from its start", () => {
  const turn = {
    sentAt: 0, lastPaintAt: 7900, status: { phase: "tool", tool: "search_knowledge" }, statusAt: 8000,
  };
  assert.equal(indicatorText(turn, 8500), null, "shown before a second had passed");
  assert.equal(indicatorText(turn, 9100), "Searching the knowledge base · 1 s");
});

test("a tool with no name, or one the page does not know, is a lookup", () => {
  for (const tool of [null, "something_new", "__proto__", "constructor"]) {
    const turn = { sentAt: 0, status: { phase: "tool", tool }, statusAt: 0 };
    assert.equal(indicatorText(turn, 2000), "Running a lookup · 2 s", String(tool));
  }
});

test("a held answer says it is being written", () => {
  const turn = { sentAt: 0, lastPaintAt: 3000, status: { phase: "held" }, statusAt: 3100 };
  assert.equal(indicatorText(turn, 6200), "Writing the answer, shown once it is checked · 3 s");
});
