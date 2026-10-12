// The chat page's DOM wiring. Its pure logic is ./page-logic.js; this builds
// elements from it and talks to the API. Model and tool text are always text,
// never HTML (D-053).
import {
  createPacer, indicatorText, markdownNodes, CONFIRM_MS, doorsFor, statusText, undoLineFor,
  askedText, mergeQueue, armDoor, confirmable, spendText, chatSpendText, chatIdFromHash,
  chatListLabel, reopenedTurnPlan, noAnswerNote, overlayAfter,
} from "./page-logic.js";

const $ = (id) => document.getElementById(id);
let token = null;
let sessionId = null;
let busy = false;  // a turn is streaming: the chat cannot be switched under it

// D-056: the sign-in survives a reload in this tab, and dies with the tab.
// Storage that is blocked or missing leaves the page as it was before F2.
const TOKEN_KEY = "auspex.token";
function storedToken() { try { return sessionStorage.getItem(TOKEN_KEY); } catch (e) { return null; } }
function storeToken(t) { try { sessionStorage.setItem(TOKEN_KEY, t); } catch (e) { /* kept in memory only */ } }
function forgetToken() { try { sessionStorage.removeItem(TOKEN_KEY); } catch (e) { /* nothing was kept */ } }

function setStatus(text, cls) { const s = $("status"); s.textContent = text; s.className = cls || ""; }

async function signIn() {
  const email = $("email").value.trim();
  if (!email) { setStatus("enter an email", "err"); return; }
  setStatus("signing in…");
  try {
    const r = await fetch("/api/auth/dev-login", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email }),
    });
    if (!r.ok) { setStatus("sign-in unavailable", "err"); return; }
    token = (await r.json()).access_token;
    storeToken(token);
    signedIn();
  } catch (e) { setStatus("network error", "err"); }
}

// Everything a page does once it holds a token, whether it just signed in
// or brought the sign-in back from this tab's storage.
function signedIn() {
  setStatus("signed in", "ok");
  $("email").style.display = "none"; $("signin").style.display = "none";
  $("signout").hidden = false;
  $("prompt").disabled = false; $("send").disabled = false; $("prompt").focus();
  loadEndpoints();
  startApprovals();
  $("new-chat").disabled = false;
  loadChats();
  const id = chatIdFromHash(location.hash);
  if (id) openChat(id);
}

async function restoreSignIn() {
  const t = storedToken();
  if (!t) return;
  setStatus("signing in…");
  try {
    const r = await fetch("/api/auth/whoami", { headers: { "Authorization": "Bearer " + t } });
    if (r.ok) { token = t; signedIn(); return; }
    if (r.status === 401) forgetToken();  // expired, or signed by a key that changed
    setStatus("not signed in");
  } catch (e) { setStatus("network error", "err"); }
}

function signOut() {
  forgetToken();
  history.replaceState(null, "", location.pathname + location.search);
  location.reload();
}

async function loadEndpoints() {
  // Internal switcher: only appears when the server offers >1 endpoint.
  try {
    const r = await fetch("/api/models", { headers: { "Authorization": "Bearer " + token } });
    if (!r.ok) return;
    const { endpoints } = await r.json();
    const sel = $("endpoint");
    if (!endpoints || endpoints.length < 2) return;
    sel.innerHTML = "";
    for (const e of endpoints) {
      const opt = document.createElement("option");
      opt.value = e.id; opt.textContent = e.label;
      sel.appendChild(opt);
    }
    sel.hidden = false;
  } catch (e) { /* switcher is optional — ignore */ }
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

// D-053's element factory: props are DOM properties (href, rel, …), and a
// string child is appended as a text node. Nothing here parses HTML.
function el(tag, props, children) {
  const e = document.createElement(tag);
  Object.assign(e, props);
  e.append(...children);
  return e;
}

// Each answer bubble's markdown so far; the bubble is rebuilt from it.
const answerText = new WeakMap();

function showError(wrap, text) {
  wrap.appendChild(Object.assign(document.createElement("div"), { className: "err", textContent: text }));
}

// D-054: this chat's total, from the server, so turns that ended badly count.
async function showChatSpend() {
  if (!sessionId || !token) return;
  const asked = sessionId;  // write only if this is still the open chat when the reply lands
  try {
    const r = await fetch("/api/chat/sessions/" + encodeURIComponent(asked) + "/spend",
      { headers: { "Authorization": "Bearer " + token } });
    if (!r.ok) return;
    const text = chatSpendText(await r.json()) || "";
    if (asked === sessionId) $("chat-spend").textContent = text;
  } catch (e) { /* the total is a convenience; the per-answer lines stand */ }
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
  if (!text || !token || busy) return;
  busy = true;
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
    const r = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json", "Authorization": "Bearer " + token },
      body: JSON.stringify({ message: text, session_id: sessionId, endpoint_id: endpointId }),
    });
    if (!r.ok) {
      // HTTP errors carry a JSON detail, not SSE frames — the server's own
      // sentence (the input rail's 400, the usage ceiling's 429), as is.
      let detail = "The request failed (" + r.status + ").";
      try { const d = (await r.json()).detail; if (typeof d === "string" && d) detail = d; } catch (e) {}
      showError(wrap, detail);
      return;
    }
    const reader = r.body.getReader();
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
    showError(wrap, "[connection lost]");
  } finally {
    busy = false;  // first: a throw below must not leave the composer stuck (R7)
    paint(pacer.flush());
    open = false;
    clearInterval(ticker);
    working.remove();
    showChatSpend();
    loadChats();
    $("send").disabled = false; $("prompt").disabled = false; $("prompt").focus();
  }
}

// <chats-dom>
// Thin: what an entry and a reopened turn show come from the page-logic
// block; this builds elements from it and talks to /api/chat/sessions.
// Every server string is text (D-053's builder for answers).
const chats = { list: [], complete: true, failed: false };

function setHash(id) {
  history.replaceState(null, "", id ? "#chat=" + id : location.pathname + location.search);
}

function authed(path) { return fetch(path, { headers: { "Authorization": "Bearer " + token } }); }

async function loadChats() {
  try {
    const r = await authed("/api/chat/sessions");
    if (!r.ok) throw new Error(String(r.status));
    const body = await r.json();
    chats.list = body.sessions; chats.complete = body.complete; chats.failed = false;
  } catch (e) { chats.failed = true; }
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
  $("new-chat").disabled = busy || !token;
  $("chats-note").textContent = !token ? "Sign in to see your chats."
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
  if (busy || !token) return;
  const seq = ++openSeq;
  let r;
  try { r = await authed("/api/chat/sessions/" + encodeURIComponent(id) + "/turns"); }
  catch (e) { if (seq === openSeq && !busy) $("chats-note").textContent = "Couldn't open that chat."; return; }
  if (seq !== openSeq || busy) return;
  if (r.status === 404) { newChat("That chat is not available to you."); return; }
  if (!r.ok) { $("chats-note").textContent = "Couldn't open that chat."; return; }
  const { turns } = await r.json();
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
      wrap.appendChild(el("div", { className: "proposal" }, [part.text, review]));
    }
  }
}

// A proposal from a reopened chat may be decided already, so the queue
// does not hold it: fetch it into the decided list, where its doors are.
async function reviewProposal(id) {
  if (!approvals.waiting.some((p) => p.id === id)) {
    try {
      const r = await api("/" + encodeURIComponent(id));
      if (r.ok && r.body && r.body.id) recordDecided(r.body);
    } catch (e) { /* offline: the panel still opens, on the queue it has */ }
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

async function api(path, method = "GET") {
  const r = await fetch("/api/proposals" + path, { method, headers: { "Authorization": "Bearer " + token } });
  let body = null;
  try { body = await r.json(); } catch (e) {}
  return { ok: r.ok, status: r.status, body };
}

async function pollApprovals() {
  try {
    const r = await api("");
    if (!r.ok) throw new Error(String(r.status));
    approvals.waiting = r.body.proposals;
    approvals.complete = r.body.complete;
    approvals.failed = false;
  } catch (e) { approvals.failed = true; }
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
}

async function useDoor(id, door) {
  approvals.armed = null;
  approvals.notes[id] = { text: "…", ok: true };
  renderApprovals();
  let r;
  try { r = await api("/" + encodeURIComponent(id) + "/" + door, "POST"); } catch (e) { r = { ok: false, status: 0, body: null }; }
  const detail = r.body && typeof r.body.detail === "string" ? r.body.detail : null;
  if (r.ok) {
    const refused = r.body.refused && r.body.refused.detail;
    const did = r.body.outcome && r.body.outcome.did;
    approvals.notes[id] = refused ? { text: refused, ok: false } : did ? { text: did, ok: true } : null;
  } else {
    approvals.notes[id] = { text: detail || ("Request failed (" + r.status + ")"), ok: false };
  }
  // The server's row is the truth after any answer, success or not.
  const fresh = r.ok && r.body.proposal ? r.body.proposal : (await api("/" + encodeURIComponent(id))).body;
  if (fresh && fresh.id) recordDecided(fresh);
  await pollApprovals();
}

function doorButtons(p) {
  const now = Date.now();
  const nodes = [];
  for (const d of doorsFor(p)) {
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
    ? doorsFor(p).find((d) => d.door === approvals.armed.door) : null;
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
  const n = approvals.waiting.length;
  $("approvals").textContent = n ? `Approvals · ${n}${approvals.complete ? "" : "+"}` : "Approvals";
  const panel = $("approvals-panel");
  panel.hidden = !approvals.open;
  document.body.classList.toggle("panel-open", approvals.open);
  if (!approvals.open) return;
  const { waiting, decided } = mergeQueue(approvals.waiting, approvals.decided);
  $("approvals-note").textContent = approvals.failed
    ? "Couldn't refresh the queue; retrying."
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

$("signin").addEventListener("click", signIn);
$("email").addEventListener("keydown", (e) => { if (e.key === "Enter") signIn(); });
$("send").addEventListener("click", send);
$("prompt").addEventListener("keydown", (e) => { if (e.key === "Enter") send(); });
$("signout").addEventListener("click", signOut);
$("new-chat").addEventListener("click", () => newChat());
$("chats-toggle").addEventListener("click", () => setOverlays("toggle-chats"));
$("chats-close").addEventListener("click", () => setOverlays("close-chats"));
// The backdrop and Esc close whichever overlay is open (F2 narrow pass).
$("scrim").addEventListener("click", () => setOverlays("dismiss"));
document.addEventListener("keydown", (e) => { if (e.key === "Escape") setOverlays("dismiss"); });
// A hash pasted into this tab's address bar opens that chat without a reload.
window.addEventListener("hashchange", () => {
  const id = chatIdFromHash(location.hash);
  if (id && id !== sessionId) openChat(id);
});
restoreSignIn();
