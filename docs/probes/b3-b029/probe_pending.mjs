// PR #41 review, items 4 and 6, live against the running container (seed with
// docs/probes/b3-b024/seed.sh first). Run from a directory where Playwright
// resolves:  node probe_pending.mjs <out-dir>
// 4: pick another client without pressing Switch -> pending (Signal style and
//    a status naming where the page still is); send "hi" (a greeting the
//    platform answers itself, no engine call) -> the picker is back on the
//    active client while the turn runs.
// 6: a switch the server refuses (intercepted 503) -> focus on the picker, and
//    the status is a live region carrying the server's words.
import { chromium } from "playwright";

const OUT = process.argv[2];
const log = (...a) => console.log(...a);
const wait = (ms) => new Promise((r) => setTimeout(r, ms));
const b = await chromium.launch();
const p = await b.newPage({ viewport: { width: 1280, height: 900 } });
const csp = [];
p.on("console", (m) => { if (/Content.Security.Policy/i.test(m.text())) csp.push(m.text()); });
p.on("pageerror", (e) => csp.push("pageerror " + e.message));

const state = () => p.evaluate(() => {
  const s = document.getElementById("workspace"), st = document.getElementById("status");
  return {
    selected: s.options[s.selectedIndex].text, pending: s.classList.contains("pending"),
    color: getComputedStyle(s).color, status: st.textContent, statusClass: st.className,
    statusRole: st.getAttribute("role"), switchDisabled: document.getElementById("switch").disabled,
    focus: document.activeElement && document.activeElement.id,
  };
});

await p.goto("http://localhost:8000/");
await p.fill("#email", "m-wide@b3-live.auspex.dev");
await p.click("#signin");
await p.waitForSelector("select#workspace");
await wait(800);
log("1 signed in:", JSON.stringify(await state()));

await p.selectOption("#workspace", { index: 2 });
await wait(200);
log("2 picked another, not switched:", JSON.stringify(await state()));
await p.screenshot({ path: `${OUT}/pending.png` });

await p.fill("#prompt", "hi");
await p.click("#send");
const during = await state();  // setBusy(true) runs synchronously in send()
log("3 right after Send (turn running):", JSON.stringify(during));
await wait(2500);
log("4 after the turn:", JSON.stringify(await state()));

await p.route("**/api/auth/switch", (r) => r.fulfill({
  status: 503, contentType: "application/json", body: JSON.stringify({ detail: "The switch is unavailable right now." }),
}));
await p.selectOption("#workspace", { index: 3 });
await p.click("#switch");
await wait(1500);
log("5 after a refused switch:", JSON.stringify(await state()));
log("CSP violations / page errors:", JSON.stringify(csp));
await b.close();
