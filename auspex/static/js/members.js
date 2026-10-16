// The Members page (F4): who may enter the active workspace, read-only. It is
// an admin's page and the server is the guard: GET /api/workspace/members
// refuses anyone else, and the page shows that refusal in the server's own
// words. F5 adds its doors. Every string is text (dom.js's el).
import { $, el } from "./dom.js";
import { startShell } from "./shell.js";
import { isolateName } from "./shell-logic.js";

function memberCard(m) {
  return el("div", { className: "member" }, [
    el("div", { className: "name" }, [m.display_name || m.email]),
    el("div", { className: "meta" }, [
      el("span", { className: "email" }, [m.email]),
      el("span", {}, [m.home_organization]),
      el("span", {}, [m.role]),
      m.provider_wide ? el("span", { className: "wide" }, ["provider-wide"]) : null,
    ]),
  ]);
}

function show(...nodes) { $("main").replaceChildren(...nodes); }

async function ready({ me, api }) {
  const title = el("h1", {}, ["Members of " + isolateName(me.workspace.name)]);
  show(title, el("p", { className: "members-note" }, ["Loading…"]));
  const r = await api.get("/api/workspace/members");
  if (!r.ok) { show(title, el("p", { className: "members-error" }, [r.detail])); return; }
  const rows = r.body.members;
  show(title, ...(rows.length ? rows.map(memberCard) : [el("p", { className: "members-note" }, ["No members."])]));
}

function signedOut() {
  show(el("p", { className: "members-note" }, ["Sign in to see this workspace's members."]));
}

startShell({ page: "members", ready, signedOut });
