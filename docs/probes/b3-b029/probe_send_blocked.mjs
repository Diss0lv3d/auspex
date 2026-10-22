// PR #41 re-review, A, live (seed with docs/probes/b3-b024/seed.sh first):
// pick another client, don't press Switch, press Enter in the prompt, then
// click Send -> no POST /api/chat, the pending note in the status, the choice
// still shown as pending. Back on the active client, "hi" (a greeting the
// platform answers itself, no engine call) sends exactly one.
//   node probe_send_blocked.mjs        (Playwright resolvable from cwd)
import { chromium } from "playwright";

const log = (...a) => console.log(...a);
const wait = (ms) => new Promise((r) => setTimeout(r, ms));
const b = await chromium.launch();
const p = await b.newPage({ viewport: { width: 1280, height: 900 } });
const chats = [], errors = [];
p.on("request", (r) => { if (r.url().endsWith("/api/chat") && r.method() === "POST") chats.push(r.url()); });
p.on("console", (m) => { if (/Content.Security.Policy/i.test(m.text())) errors.push(m.text()); });
p.on("pageerror", (e) => errors.push("pageerror " + e.message));
const state = () => p.evaluate(() => {
  const s = document.getElementById("workspace");
  return {
    selected: s.options[s.selectedIndex].text, pending: s.classList.contains("pending"),
    status: document.getElementById("status").textContent,
    prompt: document.getElementById("prompt").value,
    bubbles: document.querySelectorAll("#transcript .msg.user").length,
  };
});

await p.goto("http://localhost:8000/");
await p.fill("#email", "m-wide@b3-live.auspex.dev");
await p.click("#signin");
await p.waitForSelector("select#workspace");
await wait(800);
await p.selectOption("#workspace", { index: 2 });
await p.fill("#prompt", "hi from the wrong client");
await p.press("#prompt", "Enter");
await wait(1200);
log("1 pending + Enter:", JSON.stringify(await state()), "| POST /api/chat:", chats.length);
await p.click("#send");
await wait(1200);
log("2 pending + Send click:", JSON.stringify(await state()), "| POST /api/chat:", chats.length);
await p.selectOption("#workspace", { index: 0 });
await p.fill("#prompt", "hi");
await p.press("#prompt", "Enter");
await wait(2500);
log("3 back on the active client + Enter:", JSON.stringify(await state()), "| POST /api/chat:", chats.length);
log("CSP violations / page errors:", JSON.stringify(errors));
await b.close();
