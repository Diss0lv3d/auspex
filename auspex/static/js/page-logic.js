// The chat page's pure logic (D-052): no DOM, no clock of its own. The page
// imports it (js/chat.js) and tests/js/page_logic.test.mjs imports it under
// Node, so what is tested is the module the browser runs.

import { mayChange } from "./shell-logic.js";

// F1 measured the server at ~1 ms a delta and the page at ~3 ms to paint;
// the endpoint's bursts and silences are what the analyst feels. Arrived
// frames are released smoothly, and no text waits longer than this.
export const PACE_MAX_HOLD_MS = 200;
// A silence shorter than this is not worth announcing.
export const QUIET_MS = 1000;

// One ordered queue for every frame of a turn, so pacing the text can never
// re-order it against a tool line, a proposal or an error (D-031). Only
// text is paced, and only text the server has already scanned.
export function createPacer(maxHoldMs = PACE_MAX_HOLD_MS) {
  const queue = [];
  const textKey = (f) => ("reasoning" in f ? "reasoning" : "content" in f ? "content" : null);
  // Adjacent pieces of the same kind leave as one: the answer re-renders
  // its markdown per piece (D-053).
  const emit = (out, key, text) => {
    const last = out[out.length - 1];
    if (last && key in last && Object.keys(last).length === 1) last[key] += text;
    else out.push({ [key]: text });
  };
  return {
    push(frame, now) {
      const key = textKey(frame);
      queue.push({ at: now, frame, key, rest: key ? String(frame[key]) : "" });
    },
    // What to paint on the animation frame at `now`, `dt` ms after the last.
    // The rate is the slowest that still releases every character by its
    // own deadline (arrival + maxHoldMs), so a burst is spread out and an
    // overdue character goes at once.
    take(now, dt) {
      let cum = 0, rate = 0;
      for (const it of queue) {
        if (!it.key) continue;
        cum += it.rest.length;
        rate = Math.max(rate, cum / Math.max(it.at + maxHoldMs - now, dt));
      }
      let budget = Math.ceil(rate * dt);
      const out = [];
      while (queue.length) {
        const it = queue[0];
        if (!it.key) { out.push(it.frame); queue.shift(); continue; }
        if (it.rest && budget <= 0) break;
        const part = it.rest.slice(0, budget);
        budget -= part.length;
        it.rest = it.rest.slice(part.length);
        if (part) emit(out, it.key, part);
        if (it.rest) break;
        queue.shift();
      }
      return out;
    },
    flush() {
      const out = [];
      for (const it of queue) {
        if (!it.key) out.push(it.frame);
        else if (it.rest) emit(out, it.key, it.rest);
      }
      queue.length = 0;
      return out;
    },
  };
}

// What the turn is waiting on, in our words. The server names a tool only
// when it is one the platform offers; anything else is a lookup.
export const TOOL_COPY = {
  search_knowledge: "Searching the knowledge base",
  enrich_observable: "Checking the indicator against connected sources",
  lookup_cve: "Looking up the CVE",
  annotate_observable: "Preparing a proposal for your approval",
  isolate_host: "Preparing a proposal for your approval",
};

export function statusLabel(status) {
  if (status && status.phase === "tool") {
    return Object.hasOwn(TOOL_COPY, status.tool) ? TOOL_COPY[status.tool] : "Running a lookup";
  }
  if (status && status.phase === "held") return "Writing the answer, shown once it is checked";
  return "Thinking";
}

// The working line for a turn at `now`, or null when it should not show.
// It shows from Send until something is painted, then again whenever
// nothing has been painted for QUIET_MS, counting from when the wait began.
export function indicatorText(turn, now) {
  const began = Math.max(turn.sentAt, turn.lastPaintAt ?? -Infinity, turn.statusAt ?? -Infinity);
  if (turn.lastPaintAt != null && now - began < QUIET_MS) return null;
  return `${statusLabel(turn.status)} · ${Math.floor((now - began) / 1000)} s`;
}
// D-053: the answer's markdown, as elements the page chose. `h(tag, props,
// children)` makes one element; children are elements or strings, and a
// string is only ever text. No HTML is parsed anywhere on this path.
export const INLINE_RE = /`([^`\n]+)`|\*\*([^*\n]+?)\*\*|\[([^\]\n]+)\]\(([^)\s]+)\)/g;

// Only a plain https URL is a link; anything else is shown as written.
export function safeLink(raw) {
  let url;
  try { url = new URL(raw); } catch (e) { return null; }
  if (url.protocol !== "https:" || url.username || url.password || !raw.startsWith("https://")) return null;
  return url;
}

export function inlineNodes(text, h) {
  const out = [];
  let last = 0;
  for (const m of text.matchAll(INLINE_RE)) {
    const [whole, code, bold, label, href] = m;
    let node = null;
    if (code !== undefined) node = [h("code", {}, [code])];
    else if (bold !== undefined) node = [h("strong", {}, [bold])];
    else {
      const url = safeLink(href);
      if (url) {
        node = [
          h("a", { href: url.href, target: "_blank", rel: "noopener noreferrer", referrerPolicy: "no-referrer" }, [label]),
          h("span", { className: "md-host" }, [" ↗ " + url.hostname]),
        ];
      }
    }
    if (!node) continue;  // a link that is not safe stays literal text
    if (m.index > last) out.push(text.slice(last, m.index));
    out.push(...node);
    last = m.index + whole.length;
  }
  if (last < text.length) out.push(text.slice(last));
  return out;
}

// Two passes: the lines become plain blocks first, then each element is
// made once, with all its children (a real element's children cannot be
// edited the way an array can).
export function markdownBlocks(text) {
  const lines = String(text).split("\n");
  const blocks = [];
  let open = null;  // the paragraph or list still taking lines
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    if (/^```/.test(line)) {
      const body = [];
      for (i++; i < lines.length && !/^```\s*$/.test(lines[i]); i++) body.push(lines[i]);
      blocks.push({ type: "pre", text: body.join("\n") });
      open = null;
      continue;
    }
    if (!line.trim()) { open = null; continue; }
    const heading = line.match(/^(#{1,6})\s+(\S.*)$/);
    const item = line.match(/^\s*[-*]\s+(.*)$/) || line.match(/^\s*\d+[.)]\s+(.*)$/);
    if (heading) {
      blocks.push({ type: "h" + (Math.min(heading[1].length, 3) + 2), text: heading[2] });  // # → h3
      open = null;
    } else if (item) {
      const type = /^\s*[-*]/.test(line) ? "ul" : "ol";
      if (!open || open.type !== type) { open = { type, items: [] }; blocks.push(open); }
      open.items.push(item[1]);
    } else if (open && open.type === "p") {
      open.text += "\n" + line;
    } else {
      open = { type: "p", text: line };
      blocks.push(open);
    }
  }
  return blocks;
}

export function markdownNodes(text, h) {
  return markdownBlocks(text).map((b) => {
    if (b.type === "pre") return h("pre", {}, [h("code", {}, [b.text])]);
    if (b.type === "ul" || b.type === "ol") {
      return h(b.type, {}, b.items.map((it) => h("li", {}, inlineNodes(it, h))));
    }
    return h(b.type, {}, inlineNodes(b.text, h));
  });
}
// -- The approvals panel (docs/superpowers/specs/2026-10-12-approvals-panel-design.md).
// The doors and their rules are the server's (auspex/routes/proposals.py); this
// only decides which of them a card shows. A stale approval or a stale claim is
// in the queue BECAUSE it is stale, so no page clock decides it.
export const CONFIRM_MS = 5000;

// `role` is the active workspace's (GET /api/auth/me). A role that may not
// change anything gets no door at all; the server refuses them anyway (F4).
export function doorsFor(p, role) {
  if (!mayChange(role)) return [];
  const card = p.card || {};
  const runs = (door, label, consequence) => ({ door, label, confirm: true, consequence });
  const undo = card.undo
    ? [runs("undo", "Undo", "This puts it back: " + card.undo.description)]
    : [];
  switch (p.status) {
    case "pending_approval":
      return [runs("approve", "Approve", "This runs it now: " + (card.summary || p.action)),
              { door: "reject", label: "Reject" }];
    case "approved":
      return [runs("execute", "Run now", "This runs the approved action now: " + (card.summary || p.action)),
              { door: "withdraw", label: "Withdraw" }];
    case "executing":
    case "undoing":
      return [{ door: "abandon", label: "Abandon", consequence: "Records that nobody knows whether it ran" }];
    case "incomplete":
      return [{ door: "keep", label: "Keep as it is" }, ...undo];
    case "executed":
    case "kept":
    case "abandoned":
      return undo;
    default:
      return [];
  }
}

export function ago(iso, now) {
  const min = Math.max(0, Math.floor((now - Date.parse(iso)) / 60000));
  return min < 1 ? "under a minute" : min < 60 ? `${min} min` : `${Math.floor(min / 60)} h`;
}

export function statusText(p, now) {
  const effects = (p.result || {}).effects;
  switch (p.status) {
    case "pending_approval": return "Waiting for your approval";
    case "approved": return `Approved ${ago(p.decided_at, now)} ago, never started`;
    case "executing": return `Claimed ${ago(p.claimed_at, now)} ago; the run may have died`;
    case "undoing": return `Undo claimed ${ago(p.claimed_at, now)} ago; it may have died`;
    case "incomplete":
      return effects === "unknown"
        ? "It failed, and cannot tell whether any of it landed"
        : "Part of it landed before it failed";
    case "executed": return "Done";
    case "kept": return "Kept as the run left it";
    case "abandoned": return "Abandoned: nobody knows whether it ran";
    case "rejected": return "Rejected";
    case "withdrawn": return "Withdrawn";
    case "undone": return "Undone";
    case "failed": return "Failed; nothing of it landed";
    default: return p.status;
  }
}

export function undoText(card) {
  if (!card || !card.undo) return "No undo — this cannot be taken back";
  const lost = card.undo.cannot_restore || [];
  return "Undo: " + card.undo.description + (lost.length ? " · cannot restore: " + lost.join(", ") : "");
}

// The undo line matters while the action may run or has run; on a card that
// never ran, or is finished, it is noise that reads like an offer.
export function undoLineFor(p) {
  return ["rejected", "withdrawn", "undone", "failed"].includes(p.status) ? null : undoText(p.card);
}

// `identical_pending` is null where nobody looked, which is not "no twins".
export function askedText(p) {
  const n = (p.identical_pending || []).length;
  return n === 0 ? null : n === 1 ? "Asked once more" : `Asked ${n} more times`;
}

export function mergeQueue(waiting, decided) {
  const inQueue = new Set(waiting.map((p) => p.id));
  return { waiting, decided: decided.filter((p) => !inQueue.has(p.id)) };
}

export function armDoor(id, door, now) { return { id, door, at: now }; }

export function confirmable(armed, id, door, now) {
  return !!armed && armed.id === id && armed.door === door && now - armed.at <= CONFIRM_MS;
}
// -- What a turn spent (D-054): calls and tokens, never money (the customer's
// price is theirs). Usage the endpoint did not report is not a zero.
export const kTokens = (n) => (n < 1000 ? String(n) : (n / 1000).toFixed(1) + "k");
export const calls = (n) => n + (n === 1 ? " engine call" : " engine calls");

export function spendText(done) {
  if (done.path === "shortcut") return "Answered without the engine";
  if (typeof done.engine_calls !== "number") return null;
  const u = done.usage;
  if (!u) return calls(done.engine_calls) + " · tokens not reported";
  return `${calls(done.engine_calls)} · ${kTokens(u.total_tokens)} tokens ` +
    `(${kTokens(u.prompt_tokens)} in · ${kTokens(u.completion_tokens)} out)`;
}

export function chatSpendText(t) {
  if (!t || !t.turns) return null;
  const tokens = t.prompt_tokens == null && t.completion_tokens == null
    ? "" : ` · ${kTokens((t.prompt_tokens || 0) + (t.completion_tokens || 0))} tokens`;
  return `This chat: ${t.turns} ${t.turns === 1 ? "turn" : "turns"} · ${calls(t.engine_calls)}${tokens}`;
}

// -- A chat survives a reload (docs/superpowers/specs/2026-10-12-chat-survives-reload-design.md).
// The open chat's id lives in the URL hash, and only a UUID is one.
export const CHAT_HASH_RE = /^#chat=([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})$/i;
export function chatIdFromHash(hash) {
  const m = CHAT_HASH_RE.exec(String(hash ?? ""));
  return m ? m[1].toLowerCase() : null;
}

// An age in words. "yesterday" is 24 to 48 hours ago, not a calendar day:
// the page knows no time zone of the analyst's to be right about.
export function relativeTime(then, now) {
  if (!Number.isFinite(then) || !Number.isFinite(now)) return "";  // an unparseable time says nothing, and throws nothing
  const s = Math.max(0, Math.floor((now - then) / 1000));
  if (s < 60) return "just now";
  const min = Math.floor(s / 60);
  if (min < 60) return min + " min";
  const hrs = Math.floor(min / 60);
  if (hrs < 24) return hrs + " h";
  const days = Math.floor(hrs / 24);
  if (days < 2) return "yesterday";
  if (days < 7) return days + " days";
  return new Date(then).toISOString().slice(0, 10);
}

export function chatListLabel(chat, now) {
  const age = relativeTime(Date.parse(chat.last_at), now);
  const n = chat.spend && chat.spend.engine_calls;
  return { title: chat.title || "Untitled chat", meta: n ? `${age} · ${calls(n)}` : age };
}

// A ledger row's line reads exactly as the live one (spendText).
export function ledgerSpendText(spend) {
  if (!spend) return null;
  const p = spend.prompt_tokens, c = spend.completion_tokens;
  const usage = p == null && c == null ? null
    : { prompt_tokens: p || 0, completion_tokens: c || 0, total_tokens: (p || 0) + (c || 0) };
  return spendText({ path: "ledger", engine_calls: spend.engine_calls, usage });
}

export const ENDING_COPY = {
  endpoint_error: "No answer: the engine returned an error",
  output_guard: "No answer: stopped by the platform's output check",
  usage_refused: "No answer: the workspace's usage limit was reached",
  empty_answer: "No answer: the engine returned none",
};
export function endingText(ending) {
  return Object.hasOwn(ENDING_COPY, ending ?? "") ? ENDING_COPY[ending] : "No answer was stored";
}

// A filed proposal's line in a reopened turn, in the panel's words for its
// status now. The panel calls this again whenever it learns a newer row, so a
// line never goes on saying what a door has since changed (STATE.md #20). A
// turn's row carries `summary`; the panel's full row carries `card.summary`.
export function proposalLine(p, now) {
  const summary = p.summary || (p.card && p.card.summary) || p.action;
  return `Proposal: ${summary} · ${statusText(p, now)}`;
}

// What a reopened turn renders, in order. Reasoning and tool lines were
// never stored (the chat says so once, above its turns); proposals come
// back with their CURRENT status, in the panel's own words.
export function reopenedTurnPlan(turn, now) {
  const parts = [{ kind: "question", text: String(turn.question) }];
  parts.push(turn.answer
    ? { kind: "answer", text: String(turn.answer) }
    : { kind: "no-answer", text: endingText(turn.spend && turn.spend.ending) });
  const spend = ledgerSpendText(turn.spend);
  if (spend) parts.push({ kind: "spend", text: spend });
  for (const p of turn.proposals || []) {
    parts.push({ kind: "proposal", id: String(p.id), text: proposalLine(p, now) });
  }
  return parts;
}

// A live turn the engine ended with no answer (S26): said in the words a
// reopened turn uses, and why when the budget ran out mid-thought. A turn
// whose error frame already said why, or a shortcut, gets nothing.
export function noAnswerNote(done, seen) {
  if (seen.content || seen.error || done.path === "shortcut") return null;
  const note = endingText("empty_answer") + ".";
  return done.finish_reason === "length"
    ? note + " It used its whole budget thinking. Try a narrower question."
    : note;
}

// Which overlay is open after an action (F2 narrow pass). Below 900 px the
// chat list and the approvals panel both overlay the chat: one at a time,
// and a dismissal (the backdrop, Esc) closes whichever is open. Above it the
// chat list is always on, so only the panel's half of this matters.
export function overlayAfter(state, action) {
  switch (action) {
    case "toggle-chats": return state.chats ? { ...state, chats: false } : { chats: true, approvals: false };
    case "close-chats": return { ...state, chats: false };
    case "open-approvals": return { chats: false, approvals: true };
    case "close-approvals": return { ...state, approvals: false };
    case "dismiss": return { chats: false, approvals: false };
    default: return state;
  }
}
