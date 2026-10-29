// Real-API UI smoke: drives the mock-OFF app against the running API and verifies the
// upload actually reaches POST /videos, then surfaces the real faces-unavailable state.
// This does NOT fake a successful job: the ML provider is unavailable, so the honest
// outcome is a failed face-detection state.
//
// Usage: node scripts/browser/run-real-api.mjs [uiBaseUrl]

import puppeteer from 'puppeteer-core';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const APP_ROOT = path.resolve(__dirname, '../..');
const OUT = path.resolve(APP_ROOT, '../../tests/web/browser/artifacts');
fs.mkdirSync(OUT, { recursive: true });
const UI = process.argv[2] || 'http://localhost:5175';
const CLIP = 'A:/focus/verify2/t8_1280x720.mp4';
const CHROME = 'C:/Program Files/Google/Chrome/Application/chrome.exe';

const consoleErrors = [];
const pageErrors = [];
const apiCalls = [];

const browser = await puppeteer.launch({
  executablePath: CHROME, headless: 'new',
  args: ['--no-sandbox', '--disable-setuid-sandbox', '--disable-gpu', '--disable-dev-shm-usage'],
});
const page = await browser.newPage();
await page.setViewport({ width: 1280, height: 900 });
page.on('console', (m) => { if (m.type() === 'error') consoleErrors.push(m.text().slice(0, 240)); });
page.on('pageerror', (e) => pageErrors.push(String(e.message || e).slice(0, 240)));
page.on('response', (r) => {
  const u = r.url();
  if (u.includes('/videos') || u.includes('/jobs')) apiCalls.push({ method: r.request().method(), url: u.replace(UI, ''), status: r.status() });
});

const clickByText = async (sel, text, t = 10000) => {
  const h = await page.waitForFunction(
    (s, x) => Array.from(document.querySelectorAll(s)).find((e) => e.textContent && e.textContent.includes(x)) || null,
    { timeout: t, polling: 200 }, sel, text,
  );
  await h.evaluate((el) => el.click());
};
const until = async (fn, t = 15000) => { try { await page.waitForFunction(fn, { timeout: t, polling: 250 }); return true; } catch { return false; } };

const result = { ui: UI, steps: {}, apiCalls, consoleErrors, pageErrors };

await page.goto(UI + '/', { waitUntil: 'networkidle2', timeout: 20000 });
result.steps.mockPillVisible = await page.evaluate(() => document.body.innerText.includes('وضع تجريبي'));
await clickByText('button', 'ابدأ برفع فيديو');
await until(() => location.href.includes('/upload'), 8000);
await page.waitForSelector('.drop', { timeout: 8000 });
await (await page.$('input[type=file]')).uploadFile(CLIP);
result.steps.uploadEnabled = await until(() => {
  const b = Array.from(document.querySelectorAll('button')).find((x) => x.textContent && x.textContent.includes('ارفع وابدأ'));
  return b && !b.disabled;
}, 8000);
await clickByText('button', 'ارفع وابدأ');
result.steps.navigatedToSelect = await until(() => location.href.includes('/select/'), 25000);
result.steps.url = page.url();
// Real API has no ML provider -> faces come back failed. Wait for that state.
result.steps.facesFailedShown = await until(() => document.body.innerText.includes('معرفناش نكشف الوجوه') || document.body.innerText.includes('PROCESSING_FAILED'), 25000);
await new Promise((r) => setTimeout(r, 500));
await page.screenshot({ path: path.join(OUT, 'real-api-01-faces-unavailable.png'), fullPage: false });
result.steps.bodySnippet = await page.evaluate(() => document.body.innerText.slice(0, 260));

console.log(JSON.stringify(result, null, 2));
await browser.close();
