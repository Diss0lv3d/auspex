// The timeline page's DOM wiring (S16). Its pure logic is ./timeline-logic.js;
// the header, the sign-in and every request's auth are the shell's
// (./shell.js, F4). Feed text (observable values, sources, claims, checker
// names) is always text, never HTML: the page runs under D-057's policy (TD-051).
import { pct, conf, claimStatusClass, standingClass, digestBanner } from "./timeline-logic.js";
import { $, el } from "./dom.js";
import { startShell } from "./shell.js";

let api = null;  // the shell's client, once /me has accepted this tab's token
const when = (iso) => new Date(iso).toLocaleString();

const span = (className, text = "") => el("span", { className }, [String(text ?? "")]);
const pill = (cls, text) => span(`pill ${cls ?? ""}`, text);
const spacer = () => span("spacer");

// A decay bar: its width through the CSSOM, which the policy allows.
function bar(className, width) {
  const b = el("div", { className });
  b.style.width = `${width}%`;
  return b;
}

// An observable that opens its own timeline. The id travels in the closure,
// never through markup, so no character in it can break out.
function obsLink(o) {
  const a = el("a", { className: "mono", href: "#" }, [o.value]);
  a.addEventListener("click", (e) => { e.preventDefault(); open_(o.obs_id); });
  return a;
}

function setStatus(msg, err) { $("status").textContent = msg; $("status").className = err ? "err" : ""; }

// One read through the shell's client; a refusal throws the server's sentence.
async function load(path) {
  const r = await api.get(path);
  if (!r.ok) throw new Error(r.detail);
  return r.body;
}

// A verdict card: the label, both confidences, and the gap between them.
function verdictCard(v, inTrail) {
  const band = v.staleness;
  return el("div", { className: `card${inTrail && v.current ? " current" : ""}` }, [
    el("div", { className: "row" }, [
      pill(v.label, v.label), pill(band, band),
      span("small muted", v.current ? "current" : "superseded"),
      spacer(), span("small muted", when(v.created_at)),
    ]),
    el("div", { className: "decay" }, [
      el("div", { className: "track" }, [
        bar("written", pct(v.confidence_at_write)),
        bar(`now ${band}-f`, pct(v.confidence_now)),
      ]),
      el("div", { className: "legend" }, [
        el("span", {}, ["asserted ", span("mono", conf(v.confidence_at_write))]),
        el("span", {}, ["still stands ", span("mono", conf(v.confidence_now))]),
        span("", `${v.half_lives_elapsed} half-lives (${v.half_life_days}d)`),
      ]),
    ]),
    el("div", { className: "small muted mono mt8" }, [v.source]),
  ]);
}

function claimCard(c) {
  return el("div", { className: "card" }, [
    el("div", { className: "row" }, [
      pill(claimStatusClass(c.status), c.status),
      c.standing ? pill(standingClass(c.standing), c.standing) : null,
      span("mono small muted", c.kind),
      spacer(),
      span("small muted", c.satisfied_at ? "contradicted " + when(c.satisfied_at) : "registered " + when(c.created_at)),
    ]),
    el("div", { className: "mt6" }, [c.claim]),
    c.satisfied_by ? el("div", { className: "small muted mono mt6" }, [`by ${c.satisfied_by}`]) : null,
  ]);
}

function section(title, items, render, cut) {
  const out = [el("h2", {}, [title])];
  if (items.length) out.push(...items.map(render));
  else out.push(el("div", { className: "card empty" }, ["nothing"]));
  // `cut` is the server saying this list had more rows than the page asked for
  // (S17 Step 0). Rendering the page size as though it were the total is the
  // same dishonesty as rendering an unexplained empty list, which the banner
  // above already refuses.
  if (cut) out.push(el("div", { className: "card empty" }, [`showing the first ${items.length} — there are more`]));
  return out;
}

async function digest() {
  try {
    const d = await load("/api/timeline/digest?days=7");
    const banner = digestBanner(d);
    const checkers = d.checkers.length
      ? d.checkers.map((c) => pill(c.degraded ? "malicious" : "benign", `${c.name}${c.degraded ? " degraded" : ""}`))
      : [pill("slate", "no checkers running")];
    $("main").replaceChildren(
      el("div", { className: `banner ${banner.kind}` }, [banner.text]),
      el("div", { className: "row small muted mb8" }, ["checking: ", ...checkers]),
      ...section("New intel re-opened", d.reopened, (m) => el("div", { className: "card" }, [
        el("div", { className: "row" }, [
          obsLink(m.observable),
          pill(m.verdict_label_at_match || "unknown", m.verdict_label_at_match || "no verdict"),
          spacer(), span("small muted", when(m.created_at)),
        ]),
        m.falsifies ? el("div", { className: "small mt6" }, [
          span("muted", "contradicts a claim this verdict made:"), ` ${m.falsifies}`,
        ]) : null,
      ]), d.truncated.includes("reopened")),
      ...section("Labels that actually changed", d.flipped, (f) => el("div", { className: "card" }, [
        el("div", { className: "row" }, [
          obsLink(f.observable), pill(f.from_label, f.from_label), "→", pill(f.to_label, f.to_label),
          spacer(), span("small muted mono", f.trigger),
        ]),
      ]), d.truncated.includes("flipped")),
      ...section("Claims that stopped being true", d.contradicted, (c) => el("div", { className: "card" }, [
        el("div", { className: "row" }, [obsLink(c.observable), span("mono small muted", c.kind)]),
        el("div", { className: "mt6" }, [c.claim]),
      ]), d.truncated.includes("contradicted")),
      ...section("Went stale on their own", d.decayed, (x) => el("div", { className: "card" }, [
        el("div", { className: "row" }, [
          obsLink(x.observable), pill(x.label, x.label), pill(x.was, x.was), "→", pill(x.now, x.now),
          spacer(), span("small muted", `${conf(x.confidence_at_write)} → ${conf(x.confidence_now)}`),
        ]),
      ]), d.truncated.includes("decayed")),
    );
    setStatus(`digest · ${d.quiet ? "quiet" : "activity"}`);
  } catch (e) { setStatus(e.message, true); }
}

async function open_(obsId) {
  $("obs").value = obsId;
  try {
    const t = await load(`/api/timeline/${encodeURIComponent(obsId)}`);
    $("main").replaceChildren(
      el("div", { className: "row" }, [span("mono big", t.observable.value), pill("slate", t.observable.type)]),
      el("div", { className: "small muted mt6" }, [t.note]),
      el("h2", {}, ["Now"]),
      t.current ? verdictCard(t.current, false) : el("div", { className: "card empty" }, ["never enriched"]),
      ...section("What would prove it wrong", t.claims, claimCard),
      ...section("What re-opened it", t.reopened_by, (m) => el("div", { className: "card" }, [
        el("div", { className: "row" }, [
          span("mono", m.trigger_doc), pill("slate", m.change_kind),
          spacer(), span("small muted", when(m.created_at)),
        ]),
        el("div", { className: "small muted mt6" }, [m.note]),
        m.falsifies ? el("div", { className: "small mt6" }, [`falsifies: ${m.falsifies}`]) : null,
      ])),
      ...section("When the label changed", t.flips, (f) => el("div", { className: "card" }, [
        el("div", { className: "row" }, [
          pill(f.from_label, f.from_label), "→", pill(f.to_label, f.to_label),
          span("mono small muted", f.trigger), spacer(), span("small muted", when(f.created_at)),
        ]),
      ])),
      el("h2", {}, ["The whole trail"]),
      el("div", { className: "trail" }, t.trail.map((v) => verdictCard(v, true))),
    );
    setStatus(`timeline · ${t.trail.length} verdicts`);
  } catch (e) { setStatus(e.message, true); }
}

$("go").addEventListener("click", () => { if (api) open_($("obs").value.trim()); });
$("back").addEventListener("click", () => { if (api) digest(); });
startShell({
  page: "timeline",
  ready: (ctx) => { api = ctx.api; digest(); },
  signedOut: () => $("main").replaceChildren(el("div", { className: "card empty" }, ["Sign in to see the digest."])),
});
