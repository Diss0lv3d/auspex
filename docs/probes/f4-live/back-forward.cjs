// F4 C1 live: Back after a switch, and after Sign out, with the browser's
// back/forward cache ON (Playwright disables it by default).
const { chromium } = require('playwright-core');
const BASE = 'http://localhost:8000';
(async () => {
  // CHROMIUM overrides the browser on another machine (B3 ran it on Hunaiza's).
  const executablePath = process.env.CHROMIUM || '/home/burhan/.cache/ms-playwright/chromium-1208/chrome-linux64/chrome';
  const browser = await chromium.launch({ executablePath, ignoreDefaultArgs: ['--disable-back-forward-cache'] });
  const page = await browser.newPage({ viewport: { width: 1280, height: 800 } });
  const out = {};
  await page.addInitScript(() => { window.__born = Math.random(); });
  const label = () => page.locator('#workspace').evaluate((e) => e.tagName === 'SELECT' ? e.selectedOptions[0].textContent : e.textContent).catch(() => null);
  const signin = async (email) => {
    await page.goto(BASE + '/'); await page.evaluate(() => sessionStorage.clear()); await page.reload();
    await page.fill('#email', email); await page.click('#signin');
    await page.waitForSelector('#signout', { timeout: 10000 }); await page.waitForTimeout(600);
  };
  const switchTo = async (match) => {
    const v = await page.evaluate((m) => [...document.querySelectorAll('#workspace option')].find((o) => o.textContent.includes(m)).value, match);
    // B-024 (B3): choosing only selects; the Switch button switches.
    await page.selectOption('#workspace', v);
    await Promise.all([page.waitForNavigation(), page.click('#switch')]);
    await page.waitForSelector('#signout', { timeout: 10000 }); await page.waitForTimeout(600);
  };
  // 1. Back after a switch made on another page.
  await signin('m-wide@f4-live.auspex.dev');
  await switchTo('f4-live-bank');
  const chatBorn = await page.evaluate(() => window.__born);
  out.chatBefore = await label();
  await Promise.all([page.waitForNavigation(), page.click('nav.pages a[href="/timeline"]')]);
  await page.waitForSelector('#signout'); await page.waitForTimeout(600);
  await switchTo('f4-live-telco');
  out.timelineAfterSwitch = await label();
  await page.goBack({ waitUntil: 'commit' }); await page.waitForTimeout(2500);
  out.afterBack = {
    url: page.url(), label: await label(),
    restoredFromCache: (await page.evaluate(() => window.__born)) === chatBorn,
    navType: await page.evaluate(() => performance.getEntriesByType('navigation')[0].type),
  };
  // 2. Back after Sign out made on another page.
  await Promise.all([page.waitForNavigation(), page.click('nav.pages a[href="/timeline"]')]);
  await page.waitForSelector('#signout'); await page.waitForTimeout(600);
  const born2 = await page.goBack({ waitUntil: 'commit' }).then(() => null);
  await page.waitForTimeout(800);
  const chatBorn2 = await page.evaluate(() => window.__born);
  await page.goForward({ waitUntil: 'commit' }); await page.waitForTimeout(800);
  await Promise.all([page.waitForNavigation(), page.click('#signout')]);
  await page.waitForTimeout(800);
  out.timelineAfterSignOut = { signin: await page.locator('#signin').count() };
  await page.goBack({ waitUntil: 'commit' }); await page.waitForTimeout(2500);
  out.afterBackFromSignOut = {
    url: page.url(), signout: await page.locator('#signout').count(), signin: await page.locator('#signin').count(),
    label: await label(), restoredFromCache: (await page.evaluate(() => window.__born)) === chatBorn2,
    storedToken: await page.evaluate(() => sessionStorage.getItem('auspex.token') !== null),
  };
  console.log(JSON.stringify(out, null, 2));
  await browser.close();
})().catch((e) => { console.error(e); process.exit(1); });
