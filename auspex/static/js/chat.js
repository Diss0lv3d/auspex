// The chat page's DOM wiring. Its pure logic is ./page-logic.js; the header,
// the sign-in and every request's auth are the shell's (./shell.js, F4). This
// builds elements and talks to the API through the shell's client. Model and
// tool text are always text, never HTML (D-053).
import {
  createPacer, indicatorText, markdownNodes, CONFIRM_MS, doorsFor, statusText, undoLineFor,
  askedText, mergeQueue, waitingCount, armDoor, confirmable, spendText, chatSpendText, chatIdFromHash,
  hashBelongsHere, chatListLabel, reopenedTurnPlan, noAnswerNote, overlayAfter, proposalLine,
} from "./page-logic.js";
import { $, el } from "./dom.js";
import { startShell } from "./shell.js";
import { mayChange, viewerNote, CONNECTION_LOST } from "./shell-logic.js";

let api = null;  // the shell's client, once /me has accepted this tab's token
let me = null;   // GET /api/auth/me: who, where, and as what
let setBusy = () => {};
let pending = () => false;  // the shell: a workspace choice not yet switched to
let sessionId = null;
let busy = false;  // a turn is streaming: the chat cannot be switched under it

// Everything the page does once the shell holds a token /me accepted. A
// viewer gets no door that changes anything; the server refuses them anyway.
function ready(ctx) {
  ({ me, api, setBusy, pending } = ctx);
  if (mayChange(me.workspace.role)) {
    $("prompt").disabled = false; $("send").disabled = false; $("prompt").focus();
  } else {
    $("composer").hidden = true;
    $("new-chat").hidden = true;
    $("role-note").textContent = viewerNote(me);
    $("role-note").hidden = false;
  }
  loadEndpoints();
  startApprovals();
  loadChats();
  // D-070: a hash another workspace or person left in this history entry (Back
  // after a switch) is dropped, never requested under this token.
  const id = chatIdFromHash(location.hash);
  if (id && hashBelongsHere(history.state, me)) openChat(id);
  else if (id) setHash(null);
}

function signedOut() { renderChats(); }

async function loadEndpoints() {
  // Internal switcher: only appears when the server offers >1 endpoint.
  const r = await api.get("/api/models");
  const endpoints = r.ok && r.body ? r.body.endpoints : null;
  if (!endpoints || endpoints.length < 2) return;
  const sel = $("endpoint");
  sel.replaceChildren(...endpoints.map((e) => el("option", { value: e.id }, [e.label])));
  sel.hidden = false;
}

function addMsg(who, cls) {
  const wrap = document.createElement("div");
  wrap.className = "msg " + cls;
  wrap.innerHTML = `<div class="who"></div>`;
  wrap.querySelector(".who").textContent = who;
  $("transcript").appendChild(wrap);
  return wrap;
}

function ensureThink(wrap) {
  let d = wrap.querySelector("details.think");
  if (!d) {
    d = document.createElement("details");
    d.className = "think";
    d.open = true;  // expanded while reasoning streams so it's visible
    d.innerHTML = `<summary>Reasoning</summary><div class="r"></div>`;
    wrap.appendChild(d);
  }
  return d.querySelector(".r");
}

function ensureBubble(wrap) {
  let b = wrap.querySelector(".bubble");
  if (!b) { b = document.createElement("div"); b.className = "bubble"; wrap.appendChild(b); }
  return b;
}

// Each answer bubble's markdown so far; the bubble is rebuilt from it.
const answerText = new WeakMap();

function showError(wrap, text) {
  wrap.appendChild(Object.assign(document.createElement("div"), { className: "err", textContent: text }));
}

// D-054: this chat's total, from the server, so turns that ended badly count.
async function showChatSpend() {
  if (!sessionId || !api) return;
  const asked = sessionId;  // write only if this is still the open chat when the reply lands
  const r = await api.get("/api/chat/sessions/" + encodeURIComponent(asked) + "/spend");
  if (!r.ok) return;  // the total is a convenience; the per-answer lines stand
  const text = chatSpendText(r.body) || "";
  if (asked === sessionId) $("chat-spend").textContent = text;
}

function scroll() { const m = $("transcript"); m.scrollTop = m.scrollHeight; }

function handleEvent(ev, wrap) {
  if ("session" in ev) { sessionId = ev.session; setHash(sessionId); }
  // append(), not textContent +=, which would erase the tool-step lines
  else if ("reasoning" in ev) { ensureThink(wrap).append(ev.reasoning); }
  else if ("tool" in ev) {
    // one agent tool step: the server's line, verbatim — it is exactly
    // what the output rail scanned. Shown as text: it is the model's.
    const line = document.createElement("div");
    line.className = "step " + ev.tool.status;
    line.textContent = "→ " + ev.tool.call + " · " + ev.tool.status;
    ensureThink(wrap).appendChild(line);
    if (ev.tool.proposal) {
      // D-045: a proposal is a decision waiting on a human, so it is shown
      // where the answer is — not folded away with the thinking. The
      // summary is the action's own dry-run sentence, as text.
      const p = document.createElement("div");
      p.className = "proposal";
      p.textContent = "Awaiting your approval: " + ev.tool.proposal.summary +
        " (proposal " + ev.tool.proposal.id.slice(0, 8) + ")";
      const review = Object.assign(document.createElement("button"), { className: "ghost review", textContent: "Review" });
      review.addEventListener("click", () => openApprovals(ev.tool.proposal.id));
      p.appendChild(review);
      wrap.appendChild(p);
    }
  }
  else if ("content" in ev) {
    // reasoning is done once the answer starts — collapse it (stays clickable)
    const think = wrap.querySelector("details.think");
    if (think) think.open = false;
    // D-053: rendered from the whole answer so far, as elements the page
    // chose; an unclosed marker stays literal until it closes.
    const b = ensureBubble(wrap);
    answerText.set(b, (answerText.get(b) || "") + ev.content);
    b.classList.add("md");
    b.replaceChildren(...markdownNodes(answerText.get(b), el));
  }
  // The server's sentence already says what happened: an engine failure, the
  // usage ceiling, or the output rail stopping the turn (S26).
  else if ("error" in ev) { showError(wrap, ev.error); }
  else if ("done" in ev) {
    // S26: a turn that ended with no answer says so, not just a Thinking pane.
    const note = noAnswerNote(ev.done, { content: !!wrap.querySelector(".bubble"), error: !!wrap.querySelector(".err") });
    if (note) wrap.appendChild(Object.assign(document.createElement("div"), { className: "noanswer", textContent: note }));
    // D-054: what this turn spent, from the server's own count.
    const text = spendText(ev.done);
    if (text) wrap.appendChild(Object.assign(document.createElement("div"), { className: "spend", textContent: text }));
  }
  scroll();
}

async function send() {
  const text = $("prompt").value.trim();
  if (!text || !api || busy) return;
  if (pending()) return;  // the shell says where the page still is (PR #41 re-review)
  busy = true;
  setBusy(true);  // the switcher and Sign out wait for the turn (D-070)
  $("prompt").value = ""; $("send").disabled = true; $("prompt").disabled = true;
  addMsg("You", "user").appendChild(Object.assign(document.createElement("div"), { className: "bubble", textContent: text }));
  const wrap = addMsg("Co-analyst", "assistant");
  // D-052: what the turn is waiting on, and its arrived frames painted paced.
  const turn = { sentAt: performance.now(), lastPaintAt: null, status: null, statusAt: null };
  const working = Object.assign(document.createElement("div"), { className: "working" });
  const pacer = createPacer();
  let open = true;
  let lastFrame = performance.now();
  const paint = (frames) => {
    for (const f of frames) {
      if ("status" in f) { turn.status = f.status; turn.statusAt = performance.now(); continue; }
      handleEvent(f, wrap);
      if ("reasoning" in f || "content" in f || "tool" in f) turn.lastPaintAt = performance.now();
    }
  };
  const showWaiting = () => {
    const text = open ? indicatorText(turn, performance.now()) : null;
    working.hidden = text === null;
    if (text !== null) { working.textContent = text; wrap.appendChild(working); }
  };
  const onFrame = (now) => {
    if (!open) return;
    paint(pacer.take(now, Math.min(Math.max(now - lastFrame, 1), 100)));
    lastFrame = now;
    showWaiting();
    requestAnimationFrame(onFrame);
  };
  requestAnimationFrame(onFrame);
  const ticker = setInterval(showWaiting, 250);  // the seconds tick in a hidden tab too
  showWaiting();
  scroll();
  try {
    renderChats();  // inside the try: a throw here must not leave busy set
    const sel = $("endpoint");
    const endpointId = sel.hidden ? undefined : sel.value;
    const r = await api.stream("/api/chat", { message: text, session_id: sessionId, endpoint_id: endpointId });
    if (!r.ok) {
      // A refusal before the stream carries a JSON detail, not SSE frames:
      // the input rail's 400, residency's 403, the usage ceiling's 429, in
      // the server's own sentence (shell-logic's errorText).
      showError(wrap, r.detail);
      return;
    }
    const reader = r.response.body.getReader();
    const dec = new TextDecoder();
    let buf = "";
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      buf += dec.decode(value, { stream: true });
      const frames = buf.split("\n\n");
      buf = frames.pop();
      for (const f of frames) {
        const line = f.split("\n").find((l) => l.startsWith("data:"));
        if (!line) continue;
        let ev;
        try { ev = JSON.parse(line.slice(5).trim()); } catch (e) { continue; }
        pacer.push(ev, performance.now());
        // An ending is never paced, and a hidden tab runs no animation frames.
        if ("done" in ev || "error" in ev || document.hidden) paint(pacer.flush());
      }
    }
  } catch (e) {
    paint(pacer.flush());
    showError(wrap, CONNECTION_LOST);
  } finally {
    // First, everything that gives the analyst the composer back (R7): a throw
    // while painting the turn's ending must not leave it looking alive.
    busy = false;
    setBusy(false);
    open = false;
    clearInterval(ticker);
    $("send").disabled = false; $("prompt").disabled = false;
    try { paint(pacer.flush()); } catch (e) { showError(wrap, "This turn's ending could not be shown. Reload to see what was stored."); }
    working.remove();
    showChatSpend();
    loadChats();
    $("prompt").focus();
  }
}

// <chats-dom>
// Thin: what an entry and a reopened turn show come from the page-logic
// block; this builds elements from it and talks to /api/chat/sessions.
// Every server string is text (D-053's builder for answers).
const chats = { list: [], complete: true, failed: false };

// The history entry that holds a chat hash names whose it is (D-070).
function setHash(id) {
  history.replaceState(id ? { workspace: me.workspace.id, user: me.user.id } : null, "", id ? "#chat=" + id : location.pathname + location.search);
}

async function loadChats() {
  const r = await api.get("/api/chat/sessions");
  if (r.ok && r.body) { chats.list = r.body.sessions; chats.complete = r.body.complete; chats.failed = false; }
  else chats.failed = true;
  renderChats();
}

function renderChats() {
  const now = Date.now();
  $("chats-list").replaceChildren(...chats.list.map((c) => {
    const label = chatListLabel(c, now);
    const b = el("button", { className: c.id === sessionId ? "chat-item current" : "chat-item", disabled: busy, title: label.title },
      [el("span", { className: "t" }, [label.title]), el("span", { className: "m" }, [label.meta])]);
    b.addEventListener("click", () => openChat(c.id));
    return b;
  }));
  $("new-chat").disabled = busy || !api;
  $("chats-note").textContent = !api ? "Sign in to see your chats."
    : chats.failed ? "Couldn't load your chats."
    : !chats.list.length ? "No chats yet."
    : chats.complete ? "" : `Only the ${chats.list.length} most recent are listed.`;
}

function clearTranscript() { $("transcript").replaceChildren(); $("chat-spend").textContent = ""; }

function newChat(note) {
  if (busy) return;
  openSeq++;
  sessionId = null;
  setHash(null);
  clearTranscript();
  if (note) $("transcript").appendChild(el("div", { className: "noanswer" }, [note]));
  setOverlays("close-chats");
  renderChats();
  loadChats();
  $("prompt").focus();
}

// A sequence guard: a reply that arrives after a Send began, or after
// New chat or a later open, must not repaint the page under it.
let openSeq = 0;

async function openChat(id) {
  if (busy || !api) return;
  const seq = ++openSeq;
  const r = await api.get("/api/chat/sessions/" + encodeURIComponent(id) + "/turns");
  if (seq !== openSeq || busy) return;
  if (r.status === 404) { newChat("That chat is not available to you."); return; }
  if (!r.ok) { $("chats-note").textContent = "Couldn't open that chat."; return; }
  const { turns } = r.body;
  if (seq !== openSeq || busy) return;
  sessionId = id;
  setHash(id);
  clearTranscript();
  $("transcript").appendChild(el("div", { className: "reopened" },
    ["Reopened · answers and spend only; reasoning and tool steps aren't kept."]));
  const now = Date.now();
  for (const turn of turns) renderReopenedTurn(reopenedTurnPlan(turn, now));
  setOverlays("close-chats");
  renderChats();
  showChatSpend();
  scroll();
}

function renderReopenedTurn(parts) {
  let wrap = null;
  for (const part of parts) {
    if (part.kind === "question") {
      addMsg("You", "user").appendChild(el("div", { className: "bubble" }, [part.text]));
      wrap = addMsg("Co-analyst", "assistant");
    } else if (part.kind === "answer") {
      wrap.appendChild(el("div", { className: "bubble md" }, markdownNodes(part.text, el)));
    } else if (part.kind === "no-answer") {
      wrap.appendChild(el("div", { className: "noanswer" }, [part.text]));
    } else if (part.kind === "spend") {
      wrap.appendChild(el("div", { className: "spend" }, [part.text]));
    } else if (part.kind === "proposal") {
      const review = el("button", { className: "ghost review" }, ["Review"]);
      review.addEventListener("click", () => reviewProposal(part.id));
      const node = el("div", { className: "proposal" }, [el("span", { className: "line" }, [part.text]), review]);
      node.dataset.proposal = part.id;
      wrap.appendChild(node);
    }
  }
}

// A proposal from a reopened chat may be decided already, so the queue
// does not hold it: fetch it into the decided list, where its doors are.
async function reviewProposal(id) {
  if (!approvals.waiting.some((p) => p.id === id)) {
    const r = await proposals("/" + encodeURIComponent(id));
    if (r.ok && r.body && r.body.id) recordDecided(r.body);
  }
  openApprovals(id);
}
// </chats-dom>

// <approvals-dom>
// Thin: what a card shows and which doors it gets come from the page-logic
// block; this builds elements from it and talks to /api/proposals. Every
// server string and every argument is text.
const approvals = { waiting: [], decided: [], complete: true, armed: null, open: false, highlight: null, notes: {}, failed: false };
let approvalsTimer = null;

// Every proposals request, through the shell's client: { ok, status, body, detail }.
function proposals(path, method = "GET") {
  return method === "POST" ? api.post("/api/proposals" + path) : api.get("/api/proposals" + path);
}

async function pollApprovals() {
  const r = await proposals("");
  if (r.ok && r.body) { approvals.waiting = r.body.proposals; approvals.complete = r.body.complete; approvals.failed = false; }
  else approvals.failed = true;
  renderApprovals();
}

function startApprovals() {
  $("approvals").hidden = false;
  pollApprovals();
  if (!approvalsTimer) approvalsTimer = setInterval(pollApprovals, 5000);
}

function openApprovals(highlightId) {
  approvals.highlight = highlightId || null;
  approvals.scrollTo = approvals.highlight;  // once: a poll must not yank the panel back
  setOverlays("open-approvals");
  pollApprovals();
}

// Narrow screens (F2): which overlay is open comes from overlayAfter; this
// applies it to the body class, the panel and the backdrop.
function setOverlays(action) {
  const next = overlayAfter({ chats: document.body.classList.contains("chats-open"), approvals: approvals.open }, action);
  document.body.classList.toggle("chats-open", next.chats);
  if (!next.approvals) approvals.highlight = null;
  approvals.open = next.approvals;
  $("scrim").hidden = !(next.chats || next.approvals);
  renderApprovals();
}

function recordDecided(p) {
  approvals.decided = [p, ...approvals.decided.filter((d) => d.id !== p.id)];
  refreshProposalLines(p);
}

// STATE.md #20: a reopened turn's line for this proposal follows what the
// panel learned, so it never says "Waiting" after a door was used.
function refreshProposalLines(p) {
  const now = Date.now();
  for (const node of $("transcript").querySelectorAll(".proposal[data-proposal]")) {
    if (node.dataset.proposal === p.id) node.querySelector(".line").textContent = proposalLine(p, now);
  }
}

async function useDoor(id, door) {
  approvals.armed = null;
  approvals.notes[id] = { text: "…", ok: true };
  renderApprovals();
  const r = await proposals("/" + encodeURIComponent(id) + "/" + door, "POST");
  if (r.ok) {
    const refused = r.body.refused && r.body.refused.detail;
    const did = r.body.outcome && r.body.outcome.did;
    approvals.notes[id] = refused ? { text: refused, ok: false } : did ? { text: did, ok: true } : null;
  } else {
    approvals.notes[id] = { text: r.detail, ok: false };
  }
  // The server's row is the truth after any answer, success or not.
  const fresh = r.ok && r.body.proposal ? r.body.proposal : (await proposals("/" + encodeURIComponent(id))).body;
  if (fresh && fresh.id) recordDecided(fresh);
  await pollApprovals();
}

function doorButtons(p) {
  const now = Date.now();
  const nodes = [];
  for (const d of doorsFor(p, me.workspace.role)) {
    const armed = d.confirm && confirmable(approvals.armed, p.id, d.door, now);
    const b = el("button", { className: armed ? "confirm " + p.risk : d.confirm && d.door === "approve" ? "" : "ghost" },
      [armed ? "Confirm " + d.label.toLowerCase() : d.label]);
    b.addEventListener("click", () => {
      if (d.confirm && !confirmable(approvals.armed, p.id, d.door, Date.now())) {
        approvals.armed = armDoor(p.id, d.door, Date.now());
        renderApprovals();
        setTimeout(renderApprovals, CONFIRM_MS + 50);
      } else {
        useDoor(p.id, d.door);
      }
    });
    nodes.push(b);
  }
  return nodes;
}

function cardFor(p) {
  const card = p.card || {};
  const writes = (card.systems || []).filter((x) => x.writes).map((x) => x.system);
  const armed = approvals.armed && approvals.armed.id === p.id && confirmable(approvals.armed, p.id, approvals.armed.door, Date.now())
    ? doorsFor(p, me.workspace.role).find((d) => d.door === approvals.armed.door) : null;
  const note = approvals.notes[p.id];
  const parts = [
    el("div", { className: "top" }, [
      el("span", { className: "action" }, [String(p.action)]),
      el("span", { className: "risk " + p.risk }, [String(p.risk)]),
      el("span", { className: "id" }, [String(p.id).slice(0, 8)]),
    ]),
    el("div", { className: "status" }, [statusText(p, Date.now())]),
  ];
  if (card.summary) parts.push(el("div", { className: "summary" }, [String(card.summary)]));
  if (writes.length) parts.push(el("div", { className: "meta" }, ["Writes: " + writes.join(", ")]));
  const undoLine = undoLineFor(p);
  if (undoLine) parts.push(el("div", { className: "meta" }, [undoLine]));
  const asked = askedText(p);
  if (asked) parts.push(el("div", { className: "meta" }, [asked]));
  if (armed && armed.consequence) parts.push(el("div", { className: "consequence" }, [armed.consequence]));
  const doors = doorButtons(p);
  if (doors.length) parts.push(el("div", { className: "doors" }, doors));
  if (note) parts.push(el("div", { className: note.ok ? "note ok" : "note" }, [note.text]));
  const node = el("div", { className: p.id === approvals.highlight ? "card hl" : "card" }, parts);
  node.dataset.id = p.id;
  return node;
}

function renderApprovals() {
  const n = waitingCount(approvals.waiting);
  $("approvals").textContent = n ? `Approvals · ${n}${approvals.complete ? "" : "+"}` : "Approvals";
  const panel = $("approvals-panel");
  panel.hidden = !approvals.open;
  document.body.classList.toggle("panel-open", approvals.open);
  if (!approvals.open) return;
  const { waiting, decided } = mergeQueue(approvals.waiting, approvals.decided);
  $("approvals-note").textContent = approvals.failed
    ? "Couldn't refresh the queue; retrying."
    : !mayChange(me.workspace.role) ? "Deciding needs the analyst or admin role."
    : n ? "" : "Nothing is waiting on you.";
  const nodes = waiting.map(cardFor);
  if (decided.length) nodes.push(el("div", { className: "divider" }, ["Decided"]), ...decided.map(cardFor));
  $("approvals-list").replaceChildren(...nodes);
  const hl = approvals.scrollTo && $("approvals-list").querySelector(".card.hl");
  if (hl) { hl.scrollIntoView({ block: "nearest" }); approvals.scrollTo = null; }
}

$("approvals").addEventListener("click", () => { approvals.open ? setOverlays("close-approvals") : openApprovals(); });
$("approvals-close").addEventListener("click", () => setOverlays("close-approvals"));
// </approvals-dom>

$("send").addEventListener("click", send);
$("prompt").addEventListener("keydown", (e) => { if (e.key === "Enter") send(); });
$("new-chat").addEventListener("click", () => newChat());
$("chats-toggle").addEventListener("click", () => setOverlays("toggle-chats"));
$("chats-close").addEventListener("click", () => setOverlays("close-chats"));
// The backdrop and Esc close whichever overlay is open (F2 narrow pass).
$("scrim").addEventListener("click", () => setOverlays("dismiss"));
document.addEventListener("keydown", (e) => { if (e.key === "Escape") setOverlays("dismiss"); });
// A hash pasted into this tab's address bar opens that chat without a reload;
// one whose entry names another workspace or person does not (D-070).
window.addEventListener("hashchange", () => {
  const id = chatIdFromHash(location.hash);
  if (id && id !== sessionId && me && hashBelongsHere(history.state, me)) openChat(id);
});
startShell({ page: "chat", ready, signedOut });
