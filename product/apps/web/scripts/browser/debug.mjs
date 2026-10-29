import puppeteer from 'puppeteer-core';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const APP_ROOT = path.resolve(__dirname, '../..');
const FIXTURE = path.join(__dirname, 'fixtures', 'sample.mp4');
const OUT = path.resolve(APP_ROOT, '../../tests/web/browser/artifacts');
fs.mkdirSync(OUT, { recursive: true });
const BASE = process.argv[2] || 'http://localhost:5174';
const CHROME = 'C:/Program Files/Google/Chrome/Application/chrome.exe';

const consoleMsgs = [];
const pageErrors = [];

const browser = await puppeteer.launch({
  executablePath: CHROME,
  headless: 'new',
  args: ['--no-sandbox', '--disable-setuid-sandbox', '--disable-gpu', '--disable-dev-shm-usage'],
});
const page = await browser.newPage();
await page.setViewport({ width: 1280, height: 900 });
page.on('console', (m) => consoleMsgs.push({ type: m.type(), text: m.text().slice(0, 300) }));
page.on('pageerror', (e) => pageErrors.push(String(e.message || e).slice(0, 300)));

const clickByText = async (sel, text, t = 10000) => {
  const h = await page.waitForFunction(
    (s, x) => Array.from(document.querySelectorAll(s)).find((e) => e.textContent && e.textContent.includes(x)) || null,
    { timeout: t, polling: 200 }, sel, text,
  );
  await h.evaluate((el) => el.click());
};
const waitUrl = (frag, t = 25000) => page.waitForFunction((f) => location.href.includes(f), { timeout: t, polling: 200 }, frag);

await page.goto(BASE + '/', { waitUntil: 'networkidle2' });
await clickByText('button', 'ابدأ برفع فيديو');
await waitUrl('/upload');
await page.waitForSelector('.drop');
await (await page.$('input[type=file]')).uploadFile(FIXTURE);
await page.waitForFunction(() => {
  const b = Array.from(document.querySelectorAll('button')).find((x) => x.textContent && x.textContent.includes('ارفع وابدأ'));
  return b && !b.disabled;
}, { timeout: 8000, polling: 150 });
await clickByText('button', 'ارفع وابدأ');
await waitUrl('/select/');
await page.waitForFunction(() => document.querySelectorAll('input[type=radio][name="face-candidate"]').length > 0, { timeout: 12000, polling: 250 });
await page.evaluate(() => document.querySelectorAll('input[type=radio][name="face-candidate"]')[0].click());
await clickByText('button', 'ابدأ عزل الصوت');
await waitUrl('/job/');
await waitUrl('/result', 25000);
await new Promise((r) => setTimeout(r, 3000));

const state = await page.evaluate(() => {
  const buttons = Array.from(document.querySelectorAll('button[role=radio], input[type=radio]'));
  const radios = buttons.map((b) => ({ tag: b.tagName, text: (b.textContent || b.value || '').trim().slice(0, 30), disabled: b.disabled }));
  const notices = Array.from(document.querySelectorAll('.notice, .notice__title')).map((n) => n.textContent.trim().slice(0, 80));
  const audioEl = document.querySelector('audio');
  return {
    url: location.href,
    radios,
    notices: notices.slice(0, 8),
    audioSrc: audioEl ? (audioEl.src || '').slice(0, 40) : 'NO_AUDIO_EL',
    audioError: audioEl ? audioEl.error : null,
    hasIsolatedBtn: !!Array.from(document.querySelectorAll('button')).find((b) => b.textContent.includes('تنزيل WAV')),
    bodyText: document.body.innerText.slice(0, 400),
  };
});

await page.screenshot({ path: path.join(OUT, 'debug-result.png') });
console.log('CONSOLE', JSON.stringify(consoleMsgs.slice(0, 20), null, 2));
console.log('PAGEERRORS', JSON.stringify(pageErrors.slice(0, 10), null, 2));
console.log('STATE', JSON.stringify(state, null, 2));
await browser.close();
