// The chat page's pure logic (D-052), run under Node's built-in test runner:
// no dependencies, no browser. It imports auspex/static/js/page-logic.js, the
// module the page itself imports, so what is tested is what the page runs.
// tests/test_page_logic.py runs this file inside the pytest gate.
//
//   node --test tests/js/page_logic.test.mjs
import assert from "node:assert/strict";
import { test } from "node:test";
import {
  createPacer, indicatorText, markdownNodes,
  doorsFor, statusText, undoText, undoLineFor, askedText, mergeQueue, armDoor, confirmable,
  spendText, chatSpendText, chatIdFromHash, relativeTime, chatListLabel, ledgerSpendText, endingText, reopenedTurnPlan,
  noAnswerNote, overlayAfter,
} from "../../auspex/static/js/page-logic.js";

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

test("text of one kind released together comes out as one piece", () => {
  // The answer re-renders its markdown on every piece (D-053), so a frame that
  // released twenty deltas must hand over one string, not twenty.
  const pacer = createPacer();
  for (let i = 0; i < 20; i++) pacer.push({ content: "word " }, 0);
  pacer.push({ tool: { name: "x", status: "executed", call: "x" } }, 0);
  pacer.push({ content: "after" }, 0);
  const out = pacer.flush();
  assert.deepEqual(out.map((p) => Object.keys(p)[0]), ["content", "tool", "content"]);
  assert.equal(out[0].content, "word ".repeat(20));
  const taken = createPacer();
  for (let i = 0; i < 20; i++) taken.push({ reasoning: "ab" }, 0);
  assert.equal(taken.take(250, FRAME_MS).length, 1);
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

// -- safe minimal markdown in the answer (D-053) -----------------------------
//
// `markdownNodes(text, h)` builds the answer through an element factory: the
// page passes one that calls createElement and appends strings as text nodes;
// here a plain-object factory makes the tree inspectable. Nothing in it can
// turn model text into markup, because nothing in it ever parses HTML.

// Frozen, like the page's real elements in the one way that matters here: a
// DOM element's `children` cannot be pushed to or reassigned, so a builder
// that edits an element after making it must fail here too.
const h = (tag, props = {}, children = []) =>
  Object.freeze({ tag, ...props, children: Object.freeze([...children]) });
const walk = (nodes) => nodes.flatMap((n) => (typeof n === "string" ? [] : [n, ...walk(n.children)]));
const textOf = (n) => (typeof n === "string" ? n : n.children.map(textOf).join(""));
const tags = (nodes) => nodes.map((n) => n.tag);

test("HTML in an answer is shown as text, never built as elements", () => {
  const nodes = markdownNodes('<img src=x onerror="alert(1)"> and <script>steal()</script>', h);
  assert.deepEqual(walk(nodes).map((n) => n.tag), ["p"]);
  assert.equal(textOf(nodes[0]), '<img src=x onerror="alert(1)"> and <script>steal()</script>');
});

test("headings, paragraphs and the line breaks inside a paragraph", () => {
  const nodes = markdownNodes("## Risk\nCRITICAL\nscore 90\n\n### Note\nend", h);
  assert.deepEqual(tags(nodes), ["h4", "p", "h5", "p"]);
  assert.equal(textOf(nodes[0]), "Risk");
  assert.equal(textOf(nodes[1]), "CRITICAL\nscore 90");
});

test("lists, with bold and code inside an item", () => {
  const nodes = markdownNodes("- **TTP**: `T1558.003`\n- second\n\n1. one\n2) two", h);
  assert.deepEqual(tags(nodes), ["ul", "ol"]);
  assert.deepEqual(tags(nodes[0].children), ["li", "li"]);
  const first = nodes[0].children[0].children;
  assert.deepEqual(first.map((c) => (typeof c === "string" ? c : `${c.tag}:${textOf(c)}`)),
    ["strong:TTP", ": ", "code:T1558.003"]);
  assert.deepEqual(nodes[1].children.map(textOf), ["one", "two"]);
});

test("a fenced block is code, kept verbatim", () => {
  const nodes = markdownNodes("Run:\n```powershell\nGet-Process **x** | `y`\n```\ndone", h);
  assert.deepEqual(tags(nodes), ["p", "pre", "p"]);
  assert.equal(nodes[1].children[0].tag, "code");
  assert.equal(textOf(nodes[1]), "Get-Process **x** | `y`");
});

test("an https link opens apart from the page and shows its real host", () => {
  const nodes = markdownNodes("See [VirusTotal](https://evil.example.net/vt?ip=1.2.3.4).", h);
  const a = walk(nodes).find((n) => n.tag === "a");
  assert.equal(a.href, "https://evil.example.net/vt?ip=1.2.3.4");
  assert.equal(a.target, "_blank");
  assert.equal(a.rel, "noopener noreferrer");
  assert.equal(a.referrerPolicy, "no-referrer");
  assert.equal(textOf(a), "VirusTotal");
  assert.match(textOf(nodes[0]), /VirusTotal ↗ evil\.example\.net\./);
});

test("anything but a plain https URL stays literal text", () => {
  for (const url of ["javascript:alert(1)", "data:text/html,<b>x</b>", "http://example.com",
    "https://user:pass@example.com/", "//example.com", "vbscript:x"]) {
    const md = `[click](${url})`;
    const nodes = markdownNodes(md, h);
    assert.equal(walk(nodes).filter((n) => n.tag === "a").length, 0, url);
    assert.equal(textOf(nodes[0]), md, url);
  }
});

test("an unclosed marker stays literal while the answer is still streaming", () => {
  for (const partial of ["a **bold", "run `whoami", "[x](https://exa", "## "]) {
    const nodes = markdownNodes(partial, h);
    assert.equal(walk(nodes).filter((n) => ["strong", "code", "a"].includes(n.tag)).length, 0, partial);
  }
  assert.equal(textOf(markdownNodes("a **bold", h)[0]), "a **bold");
});

test("underscores are text, not italics", () => {
  const nodes = markdownNodes("call enrich_observable on _this_", h);
  assert.equal(textOf(nodes[0]), "call enrich_observable on _this_");
  assert.deepEqual(walk(nodes).map((n) => n.tag), ["p"]);
});

// -- the approvals panel (docs/superpowers/specs/2026-10-12-approvals-panel-design.md)

const UNDO = { description: "removes the note", restores: "the observable as it was", cannot_restore: [] };
const proposal = (status, extra = {}) => ({
  id: "4f0c2a9e-0000-0000-0000-000000000000", action: "annotate_observable", risk: "write", status,
  created_at: "2026-10-12T02:00:00Z", decided_at: null, claimed_at: null, result: null,
  identical_pending: null, card: { summary: "add a note to 8.8.8.8", undo: UNDO, systems: [] }, ...extra,
});
const doors = (p, role = "analyst") => doorsFor(p, role).map((d) => `${d.door}${d.confirm ? "²" : ""}`);

test("each status gets the server's doors for it, and only those", () => {
  assert.deepEqual(doors(proposal("pending_approval")), ["approve²", "reject"]);
  assert.deepEqual(doors(proposal("approved")), ["execute²", "withdraw"]);
  assert.deepEqual(doors(proposal("executing")), ["abandon"]);
  assert.deepEqual(doors(proposal("undoing")), ["abandon"]);
  assert.deepEqual(doors(proposal("incomplete")), ["keep", "undo²"]);
  for (const s of ["executed", "kept", "abandoned"]) assert.deepEqual(doors(proposal(s)), ["undo²"], s);
  for (const s of ["rejected", "withdrawn", "undone", "failed"]) assert.deepEqual(doors(proposal(s)), [], s);
});

test("an action that declares no undo is never offered one", () => {
  const noUndo = (s) => proposal(s, { card: { summary: "isolate 10.0.0.5", undo: null, systems: [] } });
  assert.deepEqual(doors(noUndo("incomplete")), ["keep"]);
  assert.deepEqual(doors(noUndo("executed")), []);
});

test("a door that runs something says what it will run before it is confirmed", () => {
  const approve = doorsFor(proposal("pending_approval"), "analyst").find((d) => d.door === "approve");
  assert.match(approve.consequence, /add a note to 8\.8\.8\.8/);
  const undo = doorsFor(proposal("executed"), "analyst").find((d) => d.door === "undo");
  assert.match(undo.consequence, /removes the note/);
});

test("a viewer gets no door on any card, whatever its status; the server refuses them anyway", () => {
  const all = ["pending_approval", "approved", "executing", "undoing", "incomplete", "executed",
    "kept", "abandoned", "rejected", "withdrawn", "undone", "failed"];
  for (const s of all) assert.deepEqual(doors(proposal(s), "viewer"), [], s);
  // not doors(): its default role would turn undefined into "analyst"
  assert.deepEqual(doorsFor(proposal("pending_approval"), undefined), [], "no role is no door");
  assert.deepEqual(doors(proposal("pending_approval"), "admin"), ["approve²", "reject"]);
});

test("the status line says what the row is waiting on, in words", () => {
  const now = Date.parse("2026-10-12T02:10:00Z");
  assert.equal(statusText(proposal("pending_approval"), now), "Waiting for your approval");
  assert.equal(statusText(proposal("approved", { decided_at: "2026-10-12T02:04:00Z" }), now),
    "Approved 6 min ago, never started");
  assert.equal(statusText(proposal("executing", { claimed_at: "2026-10-12T01:10:00Z" }), now),
    "Claimed 1 h ago; the run may have died");
  assert.equal(statusText(proposal("incomplete", { result: { effects: "present" } }), now),
    "Part of it landed before it failed");
  assert.equal(statusText(proposal("incomplete", { result: { effects: "unknown" } }), now),
    "It failed, and cannot tell whether any of it landed");
  assert.equal(statusText(proposal("abandoned"), now), "Abandoned: nobody knows whether it ran");
});

test("the undo line names what cannot be restored, or that there is no undo", () => {
  assert.equal(undoText({ undo: { ...UNDO, cannot_restore: ["the audit log entry", "alerts already sent"] } }),
    "Undo: removes the note · cannot restore: the audit log entry, alerts already sent");
  assert.equal(undoText({ undo: UNDO }), "Undo: removes the note");
  assert.equal(undoText({ undo: null }), "No undo — this cannot be taken back");
});

test("an approver is told when they are being asked twice", () => {
  assert.equal(askedText(proposal("pending_approval", { identical_pending: ["a", "b"] })), "Asked 2 more times");
  assert.equal(askedText(proposal("pending_approval", { identical_pending: ["a"] })), "Asked once more");
  assert.equal(askedText(proposal("pending_approval", { identical_pending: [] })), null);
  assert.equal(askedText(proposal("executing")), null, "null means nobody looked, not 'no twins'");
});

test("decided cards follow the waiting ones, and one the queue still shows is not duplicated", () => {
  const w1 = { ...proposal("pending_approval"), id: "w1" };
  const w2 = { ...proposal("incomplete"), id: "w2" };
  const d1 = { ...proposal("executed"), id: "d1" };
  const back = { ...proposal("rejected"), id: "w2" };  // decided here, then back in the queue
  const merged = mergeQueue([w1, w2], [d1, back]);
  assert.deepEqual(merged.waiting.map((p) => p.id), ["w1", "w2"]);
  assert.deepEqual(merged.decided.map((p) => p.id), ["d1"]);
});

test("a confirm is the same door on the same card within five seconds", () => {
  const armed = armDoor("p1", "approve", 1000);
  assert.equal(confirmable(armed, "p1", "approve", 5900), true);
  assert.equal(confirmable(armed, "p1", "approve", 6001), false, "a stale arm still ran");
  assert.equal(confirmable(armed, "p2", "approve", 1500), false, "another card's arm ran this one");
  assert.equal(confirmable(armed, "p1", "undo", 1500), false, "another door's arm ran this one");
  assert.equal(confirmable(null, "p1", "approve", 1500), false);
});

test("a card that never ran, or is finished, says nothing about an undo", () => {
  // Seen live: a rejected card still read "Undo: Remove the note this approval added".
  for (const st of ["rejected", "withdrawn", "undone", "failed"]) assert.equal(undoLineFor(proposal(st)), null, st);
  assert.equal(undoLineFor(proposal("pending_approval")), "Undo: removes the note");
  assert.equal(undoLineFor(proposal("executed", { card: { undo: null } })), "No undo — this cannot be taken back");
});

// -- what a turn spent (D-054) ------------------------------------------------

test("an answer says what it spent on the engine, in calls and tokens", () => {
  const usage = { prompt_tokens: 9130, completion_tokens: 3210, total_tokens: 12340 };
  assert.equal(spendText({ path: "agent", engine_calls: 4, usage }),
    "4 engine calls · 12.3k tokens (9.1k in · 3.2k out)");
  assert.equal(spendText({ path: "model", engine_calls: 1, usage: { prompt_tokens: 640, completion_tokens: 210, total_tokens: 850 } }),
    "1 engine call · 850 tokens (640 in · 210 out)");
});

test("a shortcut says it spent nothing, and missing usage is not a zero", () => {
  assert.equal(spendText({ path: "shortcut", usage: null }), "Answered without the engine");
  assert.equal(spendText({ path: "model", engine_calls: 2, usage: null }), "2 engine calls · tokens not reported");
  assert.equal(spendText({ path: "model" }), null, "a server that does not count calls gets no line");
});

test("the chat's total counts every turn the server recorded", () => {
  assert.equal(chatSpendText({ turns: 3, engine_calls: 9, prompt_tokens: 25000, completion_tokens: 6200 }),
    "This chat: 3 turns · 9 engine calls · 31.2k tokens");
  assert.equal(chatSpendText({ turns: 1, engine_calls: 1, prompt_tokens: null, completion_tokens: null }),
    "This chat: 1 turn · 1 engine call");
  assert.equal(chatSpendText({ turns: 0, engine_calls: 0, prompt_tokens: null, completion_tokens: null }), null);
});

// -- a chat survives a reload (docs/superpowers/specs/2026-10-12-chat-survives-reload-design.md)

const CHAT = "6b1f0c2e-1d2a-4c3b-9e8f-0a1b2c3d4e5f";
const NOON = Date.parse("2026-10-12T12:00:00Z");

test("a chat id comes from the hash only when it is a UUID", () => {
  assert.equal(chatIdFromHash("#chat=" + CHAT), CHAT);
  assert.equal(chatIdFromHash("#chat=" + CHAT.toUpperCase()), CHAT);
  for (const bad of ["", "#", "#chat=", "#chat=not-a-uuid", "#chat=" + CHAT + "x",
    "#other=" + CHAT, "#chat=" + CHAT + "&x=1", null, undefined]) {
    assert.equal(chatIdFromHash(bad), null, String(bad));
  }
});

test("a chat's age reads in minutes, hours, yesterday, days, then a date", () => {
  const ago = (s) => NOON - s * 1000;
  assert.equal(relativeTime(ago(5), NOON), "just now");
  assert.equal(relativeTime(ago(120), NOON), "2 min");
  assert.equal(relativeTime(ago(3600 * 3), NOON), "3 h");
  assert.equal(relativeTime(ago(3600 * 30), NOON), "yesterday");
  assert.equal(relativeTime(ago(86400 * 3), NOON), "3 days");
  assert.equal(relativeTime(Date.parse("2026-09-01T08:00:00Z"), NOON), "2026-09-01");
  assert.equal(relativeTime(NOON + 5000, NOON), "just now", "a clock a little ahead is not negative");
});

test("an unparseable time reads as nothing and does not throw", () => {
  assert.equal(relativeTime(NaN, NOON), "");
  assert.equal(relativeTime(Date.parse("not a date"), NOON), "");
  const bad = { id: CHAT, title: "t", last_at: "not a date", spend: { engine_calls: 0 } };
  assert.doesNotThrow(() => chatListLabel(bad, NOON));
  assert.equal(chatListLabel(bad, NOON).meta, "");
});

test("a list entry shows its title, its age and what it spent", () => {
  const chat = (extra) => ({ id: CHAT, title: "We saw 185.220.101.133 beaconing", last_at: "2026-10-12T11:58:00Z",
    spend: { turns: 2, engine_calls: 6, prompt_tokens: 5100, completion_tokens: 900 }, ...extra });
  assert.deepEqual(chatListLabel(chat(), NOON), { title: "We saw 185.220.101.133 beaconing", meta: "2 min · 6 engine calls" });
  assert.deepEqual(chatListLabel(chat({ spend: { turns: 0, engine_calls: 0, prompt_tokens: null, completion_tokens: null } }), NOON),
    { title: "We saw 185.220.101.133 beaconing", meta: "2 min" }, "a chat the engine never ran says only its age");
  assert.equal(chatListLabel(chat({ title: "" }), NOON).title, "Untitled chat");
});

test("a ledger row reads like the live spend line, and missing usage is not a zero", () => {
  assert.equal(ledgerSpendText({ engine_calls: 4, prompt_tokens: 2800, completion_tokens: 300, ending: "stop" }),
    "4 engine calls · 3.1k tokens (2.8k in · 300 out)");
  assert.equal(ledgerSpendText({ engine_calls: 1, prompt_tokens: null, completion_tokens: null, ending: "endpoint_error" }),
    "1 engine call · tokens not reported");
  assert.equal(ledgerSpendText(null), null);
});

test("a turn with no answer says why, in words", () => {
  assert.equal(endingText("endpoint_error"), "No answer: the engine returned an error");
  assert.equal(endingText("output_guard"), "No answer: stopped by the platform's output check");
  assert.equal(endingText("usage_refused"), "No answer: the workspace's usage limit was reached");
  assert.equal(endingText("empty_answer"), "No answer: the engine returned none");
  assert.equal(endingText(null), "No answer was stored");
  assert.equal(endingText("toString"), "No answer was stored", "an inherited name is not an ending");
});

const turn = (extra) => ({ question: "check 8.8.8.8 and add a note", asked_at: "2026-10-12T11:00:00Z",
  answer: "## Verdict\nclean", spend: { engine_calls: 4, prompt_tokens: 2800, completion_tokens: 300, ending: "stop" },
  proposals: [], ...extra });
const filed = (id, status, extra = {}) => ({ id, action: "annotate_observable", summary: "add a note to 8.8.8.8",
  status, decided_at: null, claimed_at: null, result: { effects: null }, ...extra });

test("a reopened turn is its question, its answer, then what it spent", () => {
  assert.deepEqual(reopenedTurnPlan(turn(), NOON), [
    { kind: "question", text: "check 8.8.8.8 and add a note" },
    { kind: "answer", text: "## Verdict\nclean" },
    { kind: "spend", text: "4 engine calls · 3.1k tokens (2.8k in · 300 out)" },
  ]);
  assert.deepEqual(reopenedTurnPlan(turn({ spend: null }), NOON).map((p) => p.kind), ["question", "answer"],
    "a shortcut answer has no ledger row, so no spend line");
});

test("a reopened turn with no answer says why, and still shows what it spent", () => {
  assert.deepEqual(reopenedTurnPlan(turn({ answer: null,
    spend: { engine_calls: 2, prompt_tokens: null, completion_tokens: null, ending: "output_guard" } }), NOON), [
    { kind: "question", text: "check 8.8.8.8 and add a note" },
    { kind: "no-answer", text: "No answer: stopped by the platform's output check" },
    { kind: "spend", text: "2 engine calls · tokens not reported" },
  ]);
  assert.deepEqual(reopenedTurnPlan(turn({ answer: null, spend: null }), NOON)[1],
    { kind: "no-answer", text: "No answer was stored" });
});

test("a reopened turn's proposals carry their current status, worded as the panel words it", () => {
  const done = filed("11111111-0000-0000-0000-000000000000", "executed", { decided_at: "2026-10-12T11:00:00Z" });
  const waiting = filed("22222222-0000-0000-0000-000000000000", "pending_approval");
  assert.deepEqual(reopenedTurnPlan(turn({ proposals: [done, waiting] }), NOON).slice(3), [
    { kind: "proposal", id: done.id, text: "Proposal: add a note to 8.8.8.8 · Done" },
    { kind: "proposal", id: waiting.id, text: "Proposal: add a note to 8.8.8.8 · Waiting for your approval" },
  ]);
});

test("a stored answer is still text: HTML in it is never built as elements", () => {
  const stored = '<img src=x onerror="alert(1)"> and <script>steal()</script>';
  const [, answer] = reopenedTurnPlan(turn({ answer: stored }), NOON);
  assert.deepEqual(answer, { kind: "answer", text: stored });
  const nodes = markdownNodes(answer.text, h);
  assert.deepEqual(walk(nodes).map((n) => n.tag), ["p"]);
  assert.equal(textOf(nodes[0]), stored);
});

// -- a turn that ends with no answer says so (S26's UX edge, F2) --------------

test("a turn the engine ended with no answer says so, and why when the budget ran out", () => {
  const none = { content: false, error: false };
  assert.equal(noAnswerNote({ path: "agent", finish_reason: "stop" }, none), "No answer: the engine returned none.");
  assert.equal(noAnswerNote({ path: "model", finish_reason: "length" }, none),
    "No answer: the engine returned none. It used its whole budget thinking. Try a narrower question.");
});

test("a turn that answered, explained its error, or took the shortcut gets no note", () => {
  const done = { path: "agent", finish_reason: "stop" };
  assert.equal(noAnswerNote(done, { content: true, error: false }), null);
  assert.equal(noAnswerNote({ ...done, finish_reason: "output_guard" }, { content: false, error: true }), null,
    "the leak copy already says why");
  assert.equal(noAnswerNote({ path: "shortcut", finish_reason: "stop" }, { content: false, error: false }), null);
});

// -- narrow screens: the chat list and the approvals panel overlay the chat (F2) --

test("only one overlay is open at a time", () => {
  const none = { chats: false, approvals: false };
  assert.deepEqual(overlayAfter(none, "toggle-chats"), { chats: true, approvals: false });
  assert.deepEqual(overlayAfter({ chats: true, approvals: false }, "open-approvals"), { chats: false, approvals: true });
  assert.deepEqual(overlayAfter({ chats: false, approvals: true }, "toggle-chats"), { chats: true, approvals: false });
  assert.deepEqual(overlayAfter({ chats: true, approvals: false }, "toggle-chats"), none);
});

test("the backdrop and Esc close whatever is open; a close button closes only its own", () => {
  const none = { chats: false, approvals: false };
  assert.deepEqual(overlayAfter({ chats: true, approvals: false }, "dismiss"), none);
  assert.deepEqual(overlayAfter({ chats: false, approvals: true }, "dismiss"), none);
  assert.deepEqual(overlayAfter({ chats: false, approvals: true }, "close-chats"), { chats: false, approvals: true });
  assert.deepEqual(overlayAfter({ chats: true, approvals: false }, "close-approvals"), { chats: true, approvals: false });
  assert.deepEqual(overlayAfter({ chats: true, approvals: false }, "nonsense"), { chats: true, approvals: false });
});
