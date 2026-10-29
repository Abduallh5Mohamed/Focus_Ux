// Real-browser checks for the result actions the main harness does not click:
//   - transcript-unavailable path (audio still usable)
//   - WAV download actually produces a file
//   - delete -> two-step confirm -> returns home and clears the job
//
// Uses the dev mock with `focus-mock-transcript-fail=1` so the ASR-failure path is
// exercisable without a real provider. Usage: node scripts/browser/run-result-actions.mjs [uiBase]

import puppeteer from 'puppeteer-core';
import fs from 'node:fs';
import path from 'node:path';
import os from 'node:os';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const APP_ROOT = path.resolve(__dirname, '../..');
const OUT = path.resolve(APP_ROOT, '../../tests/web/browser/artifacts');
fs.mkdirSync(OUT, { recursive: true });
const UI = process.argv[2] || 'http://localhost:5174';
const CHROME = 'C:/Program Files/Google/Chrome/Application/chrome.exe';
const DL = path.join(os.tmpdir(), 'focus-dl-' + Date.now());
fs.mkdirSync(DL, { recursive: true });

const consoleErrors = [], pageErrors = [];
const browser = await puppeteer.launch({
  executablePath: CHROME, headless: 'new',
  args: ['--no-sandbox', '--disable-setuid-sandbox', '--disable-gpu', '--disable-dev-shm-usage'],
});
const page = await browser.newPage();
await page.setViewport({ width: 1280, height: 900 });
page.on('console', (m) => { if (m.type() === 'error') consoleErrors.push(m.text().slice(0, 200)); });
page.on('pageerror', (e) => pageErrors.push(String(e.message || e).slice(0, 200)));

const cdp = await page.createCDPSession();
await cdp.send('Browser.setDownloadBehavior', { behavior: 'allow', downloadPath: DL, eventsEnabled: true });

const clickByText = async (sel, text, t = 12000) => {
  const h = await page.waitForFunction(
    (s, x) => Array.from(document.querySelectorAll(s)).find((e) => e.textContent && e.textContent.includes(x)) || null,
    { timeout: t, polling: 200 }, sel, text,
  );
  await h.evaluate((el) => el.click());
};
const until = async (fn, t = 15000) => { try { await page.waitForFunction(fn, { timeout: t, polling: 250 }); return true; } catch { return false; } };
const btnDisabled = (text) => page.evaluate((txt) => {
  const b = Array.from(document.querySelectorAll('button')).find((x) => x.textContent && x.textContent.includes(txt));
  return b ? b.disabled : null;
}, text);

const r = { ui: UI, steps: {}, download: {}, delete: {}, consoleErrors, pageErrors };

await page.goto(UI + '/', { waitUntil: 'networkidle2', timeout: 20000 });
await page.evaluate(() => localStorage.setItem('focus-mock-transcript-fail', '1'));

await clickByText('button', 'ابدأ برفع فيديو');
await until(() => location.href.includes('/upload'), 8000);
await page.waitForSelector('.drop', { timeout: 8000 });
await (await page.$('input[type=file]')).uploadFile(path.join(__dirname, 'fixtures', 'sample.mp4'));
await until(() => {
  const b = Array.from(document.querySelectorAll('button')).find((x) => x.textContent && x.textContent.includes('ارفع وابدأ'));
  return b && !b.disabled;
}, 8000);
await clickByText('button', 'ارفع وابدأ');
await until(() => location.href.includes('/select/'), 20000);
await until(() => document.querySelectorAll('input[type=radio][name="face-candidate"]').length > 0, 12000);
await page.evaluate(() => document.querySelectorAll('input[type=radio][name="face-candidate"]')[0].click());
await clickByText('button', 'ابدأ عزل الصوت');
await until(() => location.href.includes('/result'), 25000);

r.steps.audioUsable = await until(() => {
  const els = Array.from(document.querySelectorAll('button[role=radio]'));
  return els.some((x) => x.textContent && x.textContent.includes('المعزول') && !x.disabled);
}, 15000);
r.steps.transcriptFailedShown = await until(() => document.body.innerText.includes('التفريغ النصي فشل'), 15000);
r.steps.wavDownloadEnabled = !(await btnDisabled('تنزيل WAV'));
r.steps.transcriptDownloadDisabled = await btnDisabled('تنزيل النص');
await page.screenshot({ path: path.join(OUT, 'result-actions-01-transcript-failed.png') });

// Download
await clickByText('button', 'تنزيل WAV');
let file = null;
for (let i = 0; i < 40; i++) {
  const files = fs.readdirSync(DL).filter((f) => !f.endsWith('.crdownload'));
  if (files.length) { file = files[0]; break; }
  await new Promise((res) => setTimeout(res, 250));
}
if (file) {
  const st = fs.statSync(path.join(DL, file));
  r.download = { file, bytes: st.size };
} else {
  r.download = { file: null, bytes: 0 };
}

// Delete: two-step confirm, then back home.
await clickByText('button', 'حذف الطلب');
r.delete.confirmVisible = await until(() => document.body.innerText.includes('متأكد إنك عايز تحذف'), 6000);
await clickByText('button', 'أيوه، احذف');
r.delete.returnedHome = await until(() => !location.href.includes('/result') && !location.href.includes('/job'), 12000);
r.delete.finalUrl = page.url();
r.delete.jobCleared = await page.evaluate(() => {
  try { const s = JSON.parse(localStorage.getItem('focus.session.v1') || '{}'); return !s.jobId; } catch { return false; }
});
await page.screenshot({ path: path.join(OUT, 'result-actions-02-after-delete.png') });

console.log(JSON.stringify(r, null, 2));
await browser.close();
fs.rmSync(DL, { recursive: true, force: true });
