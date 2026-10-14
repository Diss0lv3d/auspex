// F3 Step 0 item 3: walk F2's chat page in headless Chromium against the
// running container, without sending a turn (no engine calls, no spend).
// Usage: EMAIL=<dev user with chats> node probe_chat.mjs <out-dir>
import { chromium } from "playwright";

const OUT = process.argv[2];
const EMAIL = process.env.EMAIL;
const BASE = "http://localhost:8000";
const log = (...a) => console.log(...a);
const wait = (ms) => new Promise((r) => setTimeout(r, ms));

const browser = await chromium.launch();
const ctx = await browser.newContext({ viewport: { width: 1280, height: 900 } });
const page = await ctx.newPage();
const errors = [];
page.on("console", (m) => { if (m.type() === "error") errors.push(m.text()); });
page.on("pageerror", (e) => errors.push("pageerror: " + e.message));
await page.addInitScript(() => {
  window.__csp = [];
  document.addEventListener("securitypolicyviolation", (e) => window.__csp.push(`${e.violatedDirective} ${e.blockedURI}`));
});

await page.goto(BASE + "/");
await page.fill("#email", EMAIL);
await page.click("#signin");
await page.waitForFunction(() => !document.getElementById("signout").hidden, null, { timeout: 10000 });
await wait(800);
log("1 signed in, status:", await page.textContent("#status"));
const items = await page.$$eval(".chat-item", (b) => b.map((x) => x.textContent));
log("2 sidebar chats:", items.length, JSON.stringify(items.slice(0, 3)));
await page.screenshot({ path: `${OUT}/chat-signed-in.png` });

// Reopen the chat that has the most to show: try each until one has a proposal.
let opened = null;
for (let i = 0; i < Math.min(items.length, 15); i++) {
  await (await page.$$(".chat-item"))[i].click();
  await wait(900);
  const proposals = await page.$$eval(".proposal", (p) => p.length);
  if (i === 0 || proposals) opened = { i, proposals };
  if (proposals) break;
}
if (opened) {
  await (await page.$$(".chat-item"))[opened.i].click();
  await wait(900);
  log("3 reopened chat #" + opened.i, "hash:", await page.evaluate(() => location.hash));
  log("  divider:", await page.$$eval(".reopened", (d) => d.map((x) => x.textContent)));
  log("  answers:", await page.$$eval(".msg.assistant .bubble", (b) => b.length),
      " spend lines:", JSON.stringify(await page.$$eval(".spend", (s) => s.slice(0, 3).map((x) => x.textContent))));
  log("  proposal lines:", JSON.stringify(await page.$$eval(".proposal", (p) => p.slice(0, 3).map((x) => x.textContent))));
  log("  chat total:", await page.textContent("#chat-spend"));
  await page.screenshot({ path: `${OUT}/chat-reopened.png` });

  // Review brings back the card, with its doors.
  const review = await page.$(".proposal .review");
  if (review) {
    await review.click();
    await wait(1200);
    log("4 Review → panel open:", !(await page.$eval("#approvals-panel", (p) => p.hidden)));
    log("  card:", JSON.stringify(await page.$$eval("#approvals-list .status, #approvals-list .meta, #approvals-list .doors button",
      (n) => n.slice(0, 8).map((x) => x.textContent))));
    await page.screenshot({ path: `${OUT}/chat-review.png` });
    await page.keyboard.press("Escape");
    await wait(300);
    log("  Esc closes the panel:", await page.$eval("#approvals-panel", (p) => p.hidden));
  } else {
    log("4 no proposal line in any reopened chat — Review/Undo not reachable without a new turn");
  }

  // A reload keeps the sign-in (D-056) and the open chat (the hash).
  const before = await page.evaluate(() => location.hash);
  await page.reload();
  await wait(1500);
  log("5 after reload: signed in:", !(await page.$eval("#signout", (b) => b.hidden)),
      " same chat:", (await page.evaluate(() => location.hash)) === before,
      " divider:", await page.$$eval(".reopened", (d) => d.length));
}

// + New chat.
await page.click("#new-chat");
await wait(500);
log("6 + New chat → hash:", JSON.stringify(await page.evaluate(() => location.hash)),
    " messages:", await page.$$eval("#transcript .msg", (m) => m.length));

// Phone width: the Chats button, the backdrop, Esc.
await page.setViewportSize({ width: 390, height: 844 });
await wait(300);
log("7 phone: header height", await page.$eval("header", (h) => Math.round(h.getBoundingClientRect().height)),
    " wider than screen?", await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth));
await page.click("#chats-toggle");
await wait(300);
log("  Chats opens: scrim shown", !(await page.$eval("#scrim", (s) => s.hidden)));
await page.screenshot({ path: `${OUT}/chat-phone-sidebar.png` });
await page.click("#scrim", { position: { x: 370, y: 400 } });
await wait(300);
log("  tap backdrop closes:", await page.$eval("#scrim", (s) => s.hidden));
await page.click("#chats-toggle");
await wait(200);
await page.keyboard.press("Escape");
await wait(300);
log("  Esc closes:", await page.$eval("#scrim", (s) => s.hidden));
await page.setViewportSize({ width: 1280, height: 900 });

// Sign out ends the tab's sign-in; a reload stays signed out.
await page.click("#signout");
await wait(500);
log("8 Sign out → status:", await page.textContent("#status"), " stored token:",
    await page.evaluate(() => sessionStorage.getItem("auspex.token")));
await page.reload();
await wait(800);
log("  after reload still signed out:", await page.$eval("#signout", (b) => b.hidden));

// The sign-in dies with the tab: a new tab is signed out.
const other = await ctx.newPage();
await other.goto(BASE + "/");
await wait(800);
log("9 a new tab is signed out:", await other.$eval("#signout", (b) => b.hidden));

log("CSP violations:", JSON.stringify(await page.evaluate(() => window.__csp)));
log("console errors:", JSON.stringify(errors));
await browser.close();
