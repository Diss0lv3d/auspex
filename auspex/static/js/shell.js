// The shell every page shares (F4, docs/superpowers/specs/2026-10-16-f4-shell-design.md):
// the header, the tab's one sign-in (D-056), the workspace switcher, and
// D-070's rules. A switch reloads the page without its hash, so nothing of
// the previous client survives it; GET /api/auth/me is the page's only judge
// of access. Every server string is text (dom.js's el).
import { $, el } from "./dom.js";
import { createApi } from "./api.js";
import {
  navEntries, switchOptions, activeWorkspace, workspaceLabel, roleChanged, afterSwitchUrl,
  switchReady, EXPIRED, STORAGE_BLOCKED,
} from "./shell-logic.js";

// D-056: the sign-in survives a reload in this tab, and dies with the tab. The
// notice carries one sentence across the reload that ends a sign-in. Storage
// that is blocked or missing leaves the page working for this load only.
const TOKEN_KEY = "auspex.token";
const NOTICE_KEY = "auspex.notice";
function stored(key) { try { return sessionStorage.getItem(key); } catch (e) { return null; } }
function store(key, value) { try { sessionStorage.setItem(key, value); } catch (e) { /* kept in memory only */ } }
function forget(key) { try { sessionStorage.removeItem(key); } catch (e) { /* nothing was kept */ } }

const browserFetch = (...args) => window.fetch(...args);

// `page` names the page for the navigation. `ready({ me, api, setBusy })` runs
// once /me accepts this tab's token; `signedOut()` when the tab holds none.
export function startShell({ page, ready, signedOut }) {
  let token = stored(TOKEN_KEY);
  let me = null;
  let busy = false;
  let switching = false;  // a switch request is out: Sign out waits for its answer
  let checking = null;
  let signingIn = false;  // one sign-in at a time
  let picker = null;  // the workspace <select>, when there is more than one
  let switchButton = null;  // its Switch button (B-024): choosing only selects
  let out = null;     // Sign out

  const header = $("shell");
  const nav = el("nav", { className: "pages" });
  nav.setAttribute("aria-label", "Pages");
  const workspace = el("div", { className: "workspace" });
  const session = el("div", { className: "session" });
  const status = el("span", { id: "status" });
  status.setAttribute("role", "status");  // a polite live region: read aloud
  header.replaceChildren(...[
    header.querySelector(".page-lead"),
    el("span", { className: "mark" }, ["Auspex", el("span", { className: "dot" }, ["."])]),
    el("span", { className: "tag" }, ["the flock sees first"]),
    nav,
    header.querySelector(".page-tools"),
    el("span", { className: "spacer" }),
    workspace, session, status,
  ].filter(Boolean));

  const setStatus = (text, cls) => { status.textContent = text || ""; status.className = cls || ""; };

  // `bare` makes the requests that ARE the check, or come before a sign-in
  // (/me, the switch, the dev login): they must not trigger the re-check.
  const bare = createApi({ fetch: browserFetch, token: () => token });
  const api = createApi({
    fetch: browserFetch, token: () => token, onForbidden: recheck, onExpired: () => end(EXPIRED),
  });

  // D-070: this tab's sign-in is over. One sentence (the server's, or EXPIRED)
  // waits for the signed-out page the reload brings.
  function end(sentence) {
    forget(TOKEN_KEY);
    token = null;
    if (sentence) store(NOTICE_KEY, sentence);
    location.replace(afterSwitchUrl(location));
  }

  // Any 403 asks /me whether this tab may still be here. One check at a time:
  // a poll and a door refused together ask once.
  function recheck() {
    if (!checking) {
      checking = (async () => {
        const r = await bare.get("/api/auth/me");
        if (r.status === 401) end(EXPIRED);
        else if (r.status === 403) end(r.detail);
        else if (r.ok && me && roleChanged(me, r.body)) location.reload();
        else if (r.ok) { me = r.body; showSignedIn(); }  // a role refusal: the caller shows the server's words
      })().finally(() => { checking = null; });
    }
    return checking;
  }

  async function enter() {
    setStatus("signing in…");
    const r = await bare.get("/api/auth/me");
    if (r.ok) {
      me = r.body;
      showSignedIn();
      setStatus("signed in", "ok");
      ready({ me, api, setBusy });
      return;
    }
    if (r.status === 401 || r.status === 403) {
      forget(TOKEN_KEY);
      token = null;
      showSignedOut(r.status === 401 ? EXPIRED : r.detail);
      return;
    }
    setStatus(r.detail, "err");  // the network or the server failed: the token is kept
  }

  async function signIn(email) {
    if (signingIn) return;
    if (!email) { setStatus("enter an email", "err"); return; }
    signingIn = true;
    const fields = [$("email"), $("signin")].filter(Boolean);
    fields.forEach((f) => { f.disabled = true; });
    try {
      setStatus("signing in…");
      const r = await bare.post("/api/auth/dev-login", { email });
      if (!r.ok) { setStatus(r.detail, "err"); return; }
      token = r.body.access_token;
      store(TOKEN_KEY, token);
      await enter();
    } finally {
      signingIn = false;
      fields.forEach((f) => { f.disabled = false; });
    }
  }

  // The Switch button follows the choice: ready only for another workspace,
  // and never while the page or a switch holds the controls.
  function syncSwitch() {
    if (!switchButton) return;
    switchButton.disabled = !switchReady(picker && picker.value, me, busy || switching);
  }

  async function switchTo() {
    const target = picker.value;
    if (!switchReady(picker.value, me, busy || switching)) { syncSwitch(); return; }
    switching = true;
    picker.disabled = true;  // one switch at a time
    switchButton.disabled = true;
    if (out) out.disabled = true;  // its answer would override a Sign out
    setStatus("switching…");
    const r = await bare.post("/api/auth/switch", { workspace_id: target });
    if (r.ok) {
      store(TOKEN_KEY, r.body.access_token);
      if (stored(TOKEN_KEY) === r.body.access_token) {
        location.replace(afterSwitchUrl(location));
        return;
      }
      setStatus(STORAGE_BLOCKED, "err");  // a reload would land signed out
    } else if (r.status === 401) {
      end(EXPIRED);
      return;
    } else {
      setStatus(r.detail, "err");
    }
    switching = false;  // the switch was not made: the controls come back
    picker.value = me.workspace.id;
    picker.disabled = busy;
    syncSwitch();
    if (out) out.disabled = busy;
    if (!busy) picker.focus();  // the keyboard user's place, not <body>
    recheck();  // the set may have changed since it was read
  }

  function signOut() {
    if (busy || switching) return;
    forget(TOKEN_KEY);
    location.replace(afterSwitchUrl(location));
  }

  function showNav() {
    nav.replaceChildren(...navEntries(me, page).map((n) => {
      const a = el("a", { href: n.href, className: n.current ? "current" : "" }, [n.label]);
      if (n.current) a.setAttribute("aria-current", "page");
      return a;
    }));
  }

  function showSignedIn() {
    showNav();
    const options = switchOptions(me);
    const label = workspaceLabel(activeWorkspace(me));
    if (options.length > 1) {
      picker = el("select", { id: "workspace", disabled: busy || switching, title: label },
        options.map((o) => el("option", { value: o.id, selected: o.selected }, [o.text])));
      picker.setAttribute("aria-label", "Workspace");
      picker.addEventListener("change", syncSwitch);
      switchButton = el("button", { id: "switch", className: "ghost" }, ["Switch"]);
      switchButton.setAttribute("aria-label", "Switch workspace");
      switchButton.addEventListener("click", switchTo);
      workspace.replaceChildren(picker, switchButton);
      syncSwitch();  // the select may show another workspace (no active entry)
    } else {
      picker = null;
      switchButton = null;
      workspace.replaceChildren(el("span", { id: "workspace", className: "ws-label", title: label }, [label]));
    }
    out = el("button", { id: "signout", className: "ghost", disabled: busy || switching }, ["Sign out"]);
    out.addEventListener("click", signOut);
    session.replaceChildren(out);
  }

  function showSignedOut(notice) {
    me = null;
    picker = null;
    switchButton = null;
    out = null;
    showNav();
    workspace.replaceChildren();
    const email = el("input", { id: "email", type: "email", placeholder: "you@analyst.dev", autocomplete: "off" });
    const go = el("button", { id: "signin", className: "ghost" }, ["Sign in"]);
    go.addEventListener("click", () => signIn(email.value.trim()));
    email.addEventListener("keydown", (e) => { if (e.key === "Enter") signIn(email.value.trim()); });
    session.replaceChildren(email, go);
    setStatus(notice || "not signed in", notice ? "err" : "");
    signedOut();
  }

  // A page in the middle of something (chat's streaming turn) holds the
  // switcher and Sign out still: a reload would cut it. A switch still out
  // keeps holding them when the turn ends.
  function setBusy(on) {
    busy = on;
    if (picker) picker.disabled = on || switching;
    syncSwitch();
    if (out) out.disabled = on || switching;
  }

  // D-070, and Back: a page the browser restores from its back/forward cache
  // still runs on the token it was built under. If this tab's sign-in has
  // moved on since (a switch, Sign out, lost access), it reloads instead.
  window.addEventListener("pageshow", (e) => {
    if (e.persisted && stored(TOKEN_KEY) !== token) location.replace(afterSwitchUrl(location));
  });

  const notice = stored(NOTICE_KEY);
  if (notice) forget(NOTICE_KEY);
  if (token) enter();
  else showSignedOut(notice);
  return { api, setBusy };
}
