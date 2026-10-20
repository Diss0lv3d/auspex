// The shell's pure logic (F4), run under Node's built-in test runner: no
// dependencies, no browser. It imports the module the pages import.
// tests/test_shell_modules.py runs this file inside the pytest gate.
//
//   node --test tests/js/shell_logic.test.mjs
import assert from "node:assert/strict";
import { test } from "node:test";
import {
  navEntries, workspaceLabel, activeWorkspace, switchOptions, mayChange, isAdmin, roleChanged,
  errorText, NETWORK, INVALID, EXPIRED, CONNECTION_LOST, STORAGE_BLOCKED, viewerNote, afterSwitchUrl,
  isolateName, switchReady, switchPending, pendingNote,
} from "../../auspex/static/js/shell-logic.js";

// A name as a longer line shows it: isolated (U+2068 ... U+2069), so it cannot
// reorder the words around it (F4 review).
const iso = (name) => `\u2068${name}\u2069`;

// GET /api/auth/me as probed at F4 Step 0 (docs/probes/2026-10-16-f4-s30-routes.md):
// the active workspace names its organization as a bare string; the entries
// carry it as an object with its kind.
const entry = (name, kind, role, extra = {}) => ({
  id: `id-${name}`, name, region: "global", role, via: "membership",
  organization: { id: `org-${name}`, name, kind }, ...extra,
});
const me = (role = "analyst", active = "bank", workspaces = null) => {
  const list = workspaces || [
    entry("mssp", "provider", role),
    entry("bank", "client", role, { via: "provider_wide" }),
    entry("telco", "client", role, { region: "ksa", via: "provider_wide" }),
  ];
  const a = list.find((w) => w.name === active);
  return {
    user: { id: "u", email: "a@example.org", display_name: "" },
    organization: { id: "org-mssp", name: "mssp", kind: "provider" },
    workspace: { id: a.id, name: a.name, region: a.region, role: a.role, organization: a.organization.name },
    workspaces: list,
  };
};

test("an admin's navigation has Members; an analyst's and a viewer's do not", () => {
  assert.deepEqual(navEntries(me("admin"), "chat").map((n) => n.label), ["Chat", "Timeline", "Members"]);
  for (const role of ["analyst", "viewer"]) {
    assert.deepEqual(navEntries(me(role), "chat").map((n) => n.label), ["Chat", "Timeline"], role);
  }
});

test("signed out, the navigation has the pages anyone may open, never Members", () => {
  assert.deepEqual(navEntries(null, "timeline").map((n) => n.label), ["Chat", "Timeline"]);
});

test("the current page is marked, and only it", () => {
  const nav = navEntries(me("admin"), "timeline");
  assert.deepEqual(nav.map((n) => n.href), ["/", "/timeline", "/members"]);
  assert.deepEqual(nav.filter((n) => n.current).map((n) => n.href), ["/timeline"]);
});

test("a workspace is named by its organization, its kind and the role there", () => {
  assert.equal(workspaceLabel(entry("bank", "client", "analyst")), `${iso("bank")} · client · analyst`);
});

test("the region is named only when it is not global", () => {
  assert.equal(workspaceLabel(entry("telco", "client", "viewer", { region: "ksa" })),
    `${iso("telco")} · client · viewer · ksa`);
});

test("a workspace named apart from its organization shows both", () => {
  const ws = entry("soc", "client", "admin", { organization: { id: "o", name: "Acme Bank", kind: "client" } });
  assert.equal(workspaceLabel(ws), `${iso("Acme Bank")} / ${iso("soc")} · client · admin`);
});

// F4 live check: a client named with U+202E reversed the role and kind after
// it ("tsylana · tneilc"). Isolation alone is escaped by a name that closes it
// (U+2069) first, so a name's own direction controls go before it is isolated.
const CONTROL = /[\u202A-\u202E\u2066-\u2069]/u;
const ISOLATED = /^\u2068[^\u202A-\u202E\u2066-\u2069]*\u2069$/u;
const nameIn = (label, after) => {
  assert.ok(label.endsWith(after), JSON.stringify(label));
  const head = label.slice(0, label.length - after.length);
  assert.match(head, ISOLATED);  // one opening U+2068, one closing U+2069, no control between
  return head.slice(1, -1);
};

test("a name carrying a right-to-left override cannot reverse the role and kind after it", () => {
  const hostile = '<img src=x onerror="alert(1)">\u202Ebank';
  const name = nameIn(workspaceLabel(entry(hostile, "client", "analyst")), " · client · analyst");
  assert.equal(name, '<img src=x onerror="alert(1)">bank');  // markup stays characters, for the DOM to make text
});

test("a name that closes the isolation itself, then overrides, cannot escape it", () => {
  const hostile = "bank\u2069\u202E\u2066\u202A";
  const name = nameIn(workspaceLabel(entry(hostile, "client", "analyst")), " · client · analyst");
  assert.equal(name, "bank");
  assert.ok(!CONTROL.test(name));
});

test("an organization and a workspace are isolated one by one, and only the direction controls go", () => {
  const ws = entry("soc\u202E", "client", "admin", { organization: { id: "o", name: "Acme\u2069 Bank", kind: "client" } });
  assert.equal(workspaceLabel(ws), `${iso("Acme Bank")} / ${iso("soc")} · client · admin`);
  assert.equal(isolateName("بنك الرياض"), iso("بنك الرياض"));  // a right-to-left name is kept as written
  assert.equal(isolateName(undefined), iso(""));
});

test("the switcher lists exactly what the server returned, in its order, the active one selected", () => {
  const m = me();
  const options = switchOptions(m);
  assert.deepEqual(options.map((o) => o.id), m.workspaces.map((w) => w.id));
  assert.deepEqual(options.filter((o) => o.selected).map((o) => o.id), ["id-bank"]);
  assert.equal(options[2].text, `${iso("telco")} · client · analyst · ksa`);
});

test("the switcher never filters: a restricted client the server listed is listed", () => {
  // An explicit membership reaches a restricted client (probe item 2); the
  // page knows nothing of restriction and must not guess at it.
  const list = [entry("mssp", "provider", "analyst"), entry("gov", "client", "viewer")];
  assert.equal(switchOptions(me("analyst", "mssp", list)).length, 2);
});

test("the active workspace's kind comes from its own entry in the list", () => {
  assert.equal(activeWorkspace(me()).organization.kind, "client");
});

test("an active workspace missing from the list still has a name to show", () => {
  const m = me();
  m.workspaces = m.workspaces.filter((w) => w.name !== "bank");
  const a = activeWorkspace(m);
  assert.equal(a.name, "bank");
  assert.equal(workspaceLabel(a), `${iso("bank")} · analyst`);
});

test("only an analyst or an admin may change anything; only an admin administers", () => {
  assert.equal(mayChange("analyst"), true);
  assert.equal(mayChange("admin"), true);
  assert.equal(mayChange("viewer"), false);
  assert.equal(mayChange(undefined), false);
  assert.equal(isAdmin("admin"), true);
  assert.equal(isAdmin("analyst"), false);
});

test("a role changed under an open page is noticed; a list that grew is not a role change", () => {
  assert.equal(roleChanged(me("admin"), me("analyst")), true);
  const grown = me("analyst");
  grown.workspaces = [...grown.workspaces, entry("new", "client", "analyst")];
  assert.equal(roleChanged(me("analyst"), grown), false);
  assert.equal(roleChanged(me("analyst", "bank"), me("analyst", "telco")), true);
});

test("a refusal is shown in the server's own words", () => {
  assert.equal(errorText(403, { detail: "This needs the admin role in this workspace." }),
    "This needs the admin role in this workspace.");
});

test("a 422's detail list is never echoed: it repeats the input", () => {
  const body = { detail: [{ type: "uuid_parsing", msg: "Input should be a valid UUID",
    input: '<img src=x onerror="alert(1)">' }] };
  assert.equal(errorText(422, body), INVALID);
});

test("no body, or an empty detail, says which status failed", () => {
  assert.equal(errorText(500, null), "The request failed (500).");
  assert.equal(errorText(502, { detail: "  " }), "The request failed (502).");
});

test("no answer at all is the network, not the server", () => {
  assert.equal(errorText(0, null), NETWORK);
});

test("the page's own messages are sentences, never bracketed codes", () => {
  for (const text of [NETWORK, INVALID, EXPIRED, CONNECTION_LOST, STORAGE_BLOCKED]) {
    assert.ok(!text.startsWith("[") && text.endsWith("."), text);
  }
  assert.equal(CONNECTION_LOST,
    "The connection dropped before this turn finished. Reopen the chat to see what was kept.");
});

test("a viewer is told what they can and cannot do here", () => {
  assert.equal(viewerNote(me("viewer")), `You are a viewer in ${iso("bank")}: you can read here; `
    + "asking the co-analyst and deciding proposals need the analyst or admin role.");
});

test("after a switch the page reloads without its hash: no chat id travels to the next client", () => {
  assert.equal(afterSwitchUrl({ pathname: "/", search: "", hash: "#chat=4f0c2a9e-0000-0000-0000-000000000000" }), "/");
  assert.equal(afterSwitchUrl({ pathname: "/timeline", search: "?x=1", hash: "#a" }), "/timeline?x=1");
});

// B-024 (B3): arrow keys on a closed <select> fire `change` at every step on
// Windows and Linux, so the switcher switched into each client a keyboard user
// passed. Choosing only selects now; the Switch button switches, and only when
// the choice is somewhere else and nothing holds the page.
test("the Switch button is ready only for a workspace other than the active one", () => {
  const m = me();
  assert.equal(switchReady("id-telco", m, false), true);
  assert.equal(switchReady("id-bank", m, false), false);
});

test("the Switch button waits while the page is held, or before /me has answered", () => {
  assert.equal(switchReady("id-telco", me(), true), false);
  assert.equal(switchReady("id-telco", null, false), false);
  assert.equal(switchReady("", me(), false), false);
});

// PR #41 review, item 4: the header must never show a client the page is not
// in without saying so. A choice not yet switched to is pending, and says
// where the page still is.
test("a choice other than the active workspace is pending; the active one is not", () => {
  const m = me();
  assert.equal(switchPending("id-telco", m), true);
  assert.equal(switchPending("id-bank", m), false);
  assert.equal(switchPending("id-telco", null), false);
});

test("a pending choice names the workspace the page is still in", () => {
  assert.equal(pendingNote(me()), `still in ${iso("bank")} — Switch to move`);
});
