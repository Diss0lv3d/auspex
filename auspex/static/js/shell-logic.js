// The shell's pure logic (F4, docs/superpowers/specs/2026-10-16-f4-shell-design.md):
// no DOM, no fetch. js/shell.js and the pages import it, and
// tests/js/shell_logic.test.mjs imports it under Node, so what is tested is
// what the browser runs. The server decides who may enter what, and as which
// role (D-061); this module only words and orders what GET /api/auth/me
// returned. It never filters it and never adds to it (D-070).

export const PAGES = [
  { page: "chat", href: "/", label: "Chat" },
  { page: "timeline", href: "/timeline", label: "Timeline" },
  { page: "members", href: "/members", label: "Members", admin: true },
];

export function isAdmin(role) { return role === "admin"; }
export function mayChange(role) { return role === "analyst" || role === "admin"; }

// The header's page links. Signed out (`me` null), only the pages anyone may
// open; an admin entry only for an admin of the ACTIVE workspace.
export function navEntries(me, page) {
  const role = me && me.workspace ? me.workspace.role : null;
  return PAGES.filter((p) => !p.admin || isAdmin(role))
    .map((p) => ({ href: p.href, label: p.label, current: p.page === page }));
}

// One workspace as the header names it. The organization leads: which client
// you are in is the thing that must never be in doubt. Names are returned as
// written; the DOM makes them text.
export function workspaceLabel(ws) {
  const org = ws.organization || {};
  const name = org.name && org.name !== ws.name ? `${org.name} / ${ws.name}` : ws.name;
  const parts = [name, org.kind, ws.role];
  if (ws.region && ws.region !== "global") parts.push(ws.region);
  return parts.filter(Boolean).join(" · ");
}

// The active workspace's own entry (its organization carries a kind there).
// Missing from the list (a membership vanishing mid-request), it is rebuilt
// from `me.workspace`, which names its organization only.
export function activeWorkspace(me) {
  const found = (me.workspaces || []).find((w) => w.id === me.workspace.id);
  return found || { ...me.workspace, organization: { name: me.workspace.organization } };
}

export function switchOptions(me) {
  return (me.workspaces || []).map((w) => ({
    id: w.id, text: workspaceLabel(w), selected: w.id === me.workspace.id,
  }));
}

// A /me read later says this tab is somewhere else, or something else, than
// the page was built for: every door must re-derive, so the page reloads.
export function roleChanged(before, after) {
  return before.workspace.id !== after.workspace.id || before.workspace.role !== after.workspace.role;
}

// -- The one error copy. The server's own sentence when it sent one; never a
// non-string detail (a 422's list repeats the input back).
export const NETWORK = "Couldn't reach the server.";
export const INVALID = "The request was not valid.";
export const EXPIRED = "Your sign-in expired. Sign in again.";
export const CONNECTION_LOST =
  "The connection dropped before this turn finished. Reopen the chat to see what was kept.";
export const STORAGE_BLOCKED =
  "This tab cannot keep a sign-in across a reload, so the switch was not made here; you are still in the same workspace.";

export function errorText(status, body) {
  if (status === 0) return NETWORK;
  const detail = body && typeof body === "object" ? body.detail : undefined;
  if (typeof detail === "string" && detail.trim()) return detail;
  if (detail && typeof detail === "object") return INVALID;
  return `The request failed (${status}).`;
}

export function viewerNote(me) {
  return `You are a viewer in ${me.workspace.name}: you can read here; `
    + "asking the co-analyst and deciding proposals need the analyst or admin role.";
}

// D-070: a switch reloads the page without its hash, so no `#chat=` id of the
// previous client is ever sent with the next client's token.
export function afterSwitchUrl(loc) {
  return `${loc.pathname}${loc.search}`;
}
