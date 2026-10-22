// B3 / B-024: arrow keys on the closed workspace switcher, in Chromium on
// Linux, against the running container. Seed with seed.sh first.
//
//   node probe_keyboard.mjs <out-dir>      (Playwright resolvable from cwd)
//
// It signs in as the provider-wide analyst (four workspaces), focuses the
// closed <select id="workspace">, presses keys one at a time, and records each
// POST /api/auth/switch and each reload that follows.
import { chromium } from "playwright";

const OUT = process.argv[2];
const BASE = "http://localhost:8000";
const EMAIL = "m-wide@b3-live.auspex.dev";
const log = (...a) => console.log(...a);
const wait = (ms) => new Promise((r) => setTimeout(r, ms));

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
const switches = [];
let reloads = 0;
page.on("request", (r) => {
  if (r.url().endsWith("/api/auth/switch") && r.method() === "POST") switches.push(r.postData());
});
page.on("framenavigated", (f) => { if (f === page.mainFrame()) reloads += 1; });
const violations = [];
await page.addInitScript(() => {
  document.addEventListener("securitypolicyviolation", (e) => console.log("CSP " + e.violatedDirective));
});
page.on("console", (m) => { if (m.text().startsWith("CSP ")) violations.push(m.text()); });

const active = async () => page.$eval("#workspace", (s) => s.options[s.selectedIndex].text).catch(() => "(none)");
const options = async () => page.$$eval("#workspace option", (o) => o.map((x) => x.text));

await page.goto(BASE + "/");
await page.fill("#email", EMAIL);
await page.click("#signin");
await page.waitForSelector("select#workspace", { timeout: 15000 });
await wait(500);
log("options:", JSON.stringify(await options()));
log("active at start:", await active());

async function press(key) {
  const s0 = switches.length, r0 = reloads;
  await page.focus("select#workspace");
  await page.keyboard.press(key);
  await wait(2500);
  await page.waitForSelector("select#workspace", { timeout: 15000 }).catch(() => {});
  log(`${key}: switch requests +${switches.length - s0}, reloads +${reloads - r0}, active now: ${await active()}`);
}

await press("ArrowDown");
await page.screenshot({ path: `${OUT}/after-one-arrow.png` });
await press("ArrowDown");
await press("ArrowUp");
// After the fix (B-024): the Switch button makes the switch. Arrows only
// select; Tab to the button and Enter switches once, to what was selected.
if (await page.$("button#switch")) {
  log("Switch button disabled while ANOTHER workspace is selected:",
    await page.$eval("button#switch", (b) => b.disabled));
  await page.focus("select#workspace");
  await page.keyboard.press("ArrowDown");
  await page.keyboard.press("ArrowDown");
  await wait(500);
  const chosen = await page.$eval("#workspace", (s) => s.options[s.selectedIndex].text);
  log("chosen with two arrows:", chosen, "| button disabled:", await page.$eval("button#switch", (b) => b.disabled));
  const s0 = switches.length, r0 = reloads;
  await page.keyboard.press("Tab");
  log("focus after Tab:", await page.evaluate(() => document.activeElement.id));
  await page.keyboard.press("Enter");
  await wait(2500);
  await page.waitForSelector("select#workspace", { timeout: 15000 }).catch(() => {});
  log(`Tab + Enter: switch requests +${switches.length - s0}, reloads +${reloads - r0}, active now: ${await active()}`);
  await page.screenshot({ path: `${OUT}/after-switch-button.png` });
  // A pointer still works: choose, then click Switch.
  const s1 = switches.length;
  await page.selectOption("select#workspace", { index: 0 });
  await page.click("button#switch");
  await wait(2500);
  await page.waitForSelector("select#workspace", { timeout: 15000 }).catch(() => {});
  log(`pointer choose + click: switch requests +${switches.length - s1}, active now: ${await active()}`);
}
log("switch request bodies:", JSON.stringify(switches));
log("CSP violations:", JSON.stringify(violations));
await browser.close();
