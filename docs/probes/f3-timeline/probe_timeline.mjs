// F3 live check: /timeline under D-057's policy, in headless Chromium against
// the running container. Usage: node probe_timeline.mjs <out-dir>
import { chromium } from "playwright";

const OUT = process.argv[2];
const BASE = "http://localhost:8000";
const log = (...a) => console.log(...a);

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
const violations = [];
const errors = [];
page.on("console", (m) => {
  if (m.type() === "error") errors.push(m.text());
  if (/Content Security Policy|Content-Security-Policy/i.test(m.text())) violations.push(m.text());
});
page.on("pageerror", (e) => errors.push("pageerror: " + e.message));
await page.addInitScript(() => {
  window.__csp = [];
  document.addEventListener("securitypolicyviolation", (e) =>
    window.__csp.push(`${e.violatedDirective} ${e.blockedURI}`));
});

const resp = await page.goto(`${BASE}/timeline`);
log("CSP header:", resp.headers()["content-security-policy"]);
await page.waitForFunction(() => /digest|failed/.test(document.getElementById("status").textContent), null, { timeout: 15000 });
log("status after load:", await page.textContent("#status"));
log("banner:", (await page.textContent(".banner").catch(() => "(none)"))?.trim());
log("sections:", await page.$$eval("main h2", (hs) => hs.map((h) => h.textContent)));
log("markup in main (img/script/iframe):", await page.$$eval("main img, main script, main iframe", (n) => n.length));
await page.screenshot({ path: `${OUT}/timeline-digest.png`, fullPage: true });

// Open one observable: from a digest link if there is one, else from the input.
const links = await page.$$("main a.mono");
log("observable links on the digest:", links.length);
if (links.length) {
  await links[0].click();
} else {
  const id = process.env.OBS_ID || "";
  if (id) { await page.fill("#obs", id); await page.click("#go"); }
}
await page.waitForTimeout(1500);
log("status after open:", await page.textContent("#status"));
log("bar widths:", await page.$$eval(".track > div", (b) => b.slice(0, 6).map((x) => `${x.className}=${x.style.width}`)));
log("markup in main after open:", await page.$$eval("main img, main script, main iframe", (n) => n.length));
await page.screenshot({ path: `${OUT}/timeline-open.png`, fullPage: true });

// Digest goes back; Sign in works.
await page.click("#back");
await page.waitForTimeout(1000);
log("status after Digest:", await page.textContent("#status"));
await page.click("#login");
await page.waitForTimeout(1000);
log("status after Sign in:", await page.textContent("#status"));

// Phone width.
await page.setViewportSize({ width: 390, height: 844 });
await page.waitForTimeout(300);
log("page wider than phone?", await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth));
await page.screenshot({ path: `${OUT}/timeline-phone.png`, fullPage: true });

log("securitypolicyviolation events:", JSON.stringify(await page.evaluate(() => window.__csp)));
log("console CSP violations:", violations.length, JSON.stringify(violations));
log("console errors:", JSON.stringify(errors));
await browser.close();
