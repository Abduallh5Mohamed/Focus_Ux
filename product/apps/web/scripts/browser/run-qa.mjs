// Real-browser QA harness for the FOCUS web app.
// Drives the system Chrome headless against the running dev server and captures
// screenshots + console/page/network diagnostics at desktop, 390px and 320px.
//
// This is a QA tool and is NOT part of the app bundle. It resolves puppeteer-core
// from the app's node_modules (installed with --no-save).
//
// Usage: node scripts/browser/run-qa.mjs [baseUrl]

import puppeteer from 'puppeteer-core';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const APP_ROOT = path.resolve(__dirname, '../..');
const FIXTURE = path.join(__dirname, 'fixtures', 'sample.mp4');
const OUT_DIR = path.resolve(APP_ROOT, '../../tests/web/browser/artifacts');
fs.mkdirSync(OUT_DIR, { recursive: true });

const BASE_URL = process.argv[2] || 'http://localhost:5174';
const CHROME = 'C:/Program Files/Google/Chrome/Application/chrome.exe';
const VIEWPORTS = [
  { name: 'desktop', width: 1280, height: 900 },
  { name: 'mobile-390', width: 390, height: 844 },
  { name: 'mobile-320', width: 320, height: 720 },
];

const summary = { baseUrl: BASE_URL, runs: [], launched: false, launchError: null };
const log = (...a) => console.log('[qa]', ...a);

async function findByText(page, selector, text, timeoutMs = 10000) {
  return page.waitForFunction(
    (sel, txt) => Array.from(document.querySelectorAll(sel)).find((e) => e.textContent && e.textContent.includes(txt)) || null,
    { timeout: timeoutMs, polling: 200 },
    selector, text,
  );
}
async function clickByText(page, selector, text, timeoutMs = 10000) {
  const h = await findByText(page, selector, text, timeoutMs);
  await h.evaluate((el) => el.click());
}
async function waitUrl(page, fragment, timeoutMs = 25000) {
  await page.waitForFunction((f) => location.href.includes(f), { timeout: timeoutMs, polling: 200 }, fragment);
}
// Non-throwing predicate wait: returns true if satisfied, false on timeout.
async function until(page, predicateFn, timeoutMs = 15000, poll = 250) {
  try {
    await page.waitForFunction(predicateFn, { timeout: timeoutMs, polling: poll });
    return true;
  } catch {
    return false;
  }
}
const isRadioEnabled = (page, text) =>
  page.evaluate((txt) => {
    const els = Array.from(document.querySelectorAll('button[role=radio], input[type=radio]'));
    const el = els.find((r) => r.textContent && r.textContent.includes(txt));
    return el ? !el.disabled : false;
  }, text);

async function overflowInfo(page) {
  return page.evaluate(() => {
    const doc = document.documentElement;
    const body = document.body;
    const scrollW = Math.max(doc.scrollWidth, body.scrollWidth);
    const clientW = doc.clientWidth;
    const offenders = [];
    for (const el of document.querySelectorAll('*')) {
      const r = el.getBoundingClientRect();
      if (r.right > clientW + 1 && r.width > 0) {
        offenders.push({ tag: el.tagName.toLowerCase(), cls: (el.className || '').toString().slice(0, 50), right: Math.round(r.right), width: Math.round(r.width) });
        if (offenders.length >= 8) break;
      }
    }
    return { scrollWidth: scrollW, clientWidth: clientW, overflow: scrollW > clientW + 1, offenders };
  });
}

async function runFlow(page, viewport) {
  const shots = {};
  const shot = async (name) => {
    const file = path.join(OUT_DIR, `${viewport.name}-${name}.png`);
    await page.screenshot({ path: file, fullPage: false });
    shots[name] = path.relative(APP_ROOT, file);
  };

  await page.goto(BASE_URL + '/', { waitUntil: 'networkidle2', timeout: 20000 });
  await page.waitForSelector('h1, .card__title', { timeout: 8000 });
  await shot('01-home');

  const focusSeq = [];
  for (let i = 0; i < 6; i++) {
    await page.keyboard.press('Tab');
    focusSeq.push(await page.evaluate(() => {
      const el = document.activeElement;
      if (!el) return null;
      return { tag: el.tagName.toLowerCase(), text: (el.textContent || '').trim().slice(0, 36), cls: (el.className || '').toString().slice(0, 36) };
    }));
  }
  // Drop focus so the skip-link's :focus-visible style does not linger into later shots.
  await page.evaluate(() => {
    if (document.activeElement instanceof HTMLElement) document.activeElement.blur();
  });

  await clickByText(page, 'button', 'ابدأ برفع فيديو');
  await waitUrl(page, '/upload');
  await page.waitForSelector('.drop', { timeout: 8000 });
  await shot('02-upload-empty');

  await (await page.$('input[type=file]')).uploadFile(FIXTURE);
  const uploadReady = await until(page, () => {
    const b = Array.from(document.querySelectorAll('button')).find((x) => x.textContent && x.textContent.includes('ارفع وابدأ'));
    return b && !b.disabled;
  }, 8000);
  await shot('03-upload-filled');

  await clickByText(page, 'button', 'ارفع وابدأ');
  await waitUrl(page, '/select/');
  const facesReady = await until(page, () => document.querySelectorAll('input[type=radio][name="face-candidate"]').length > 0, 12000);
  await shot('04-select-faces');

  await page.evaluate(() => document.querySelectorAll('input[type=radio][name="face-candidate"]')[0].click());
  await clickByText(page, 'button', 'ابدأ عزل الصوت');
  await waitUrl(page, '/job/');
  const reachedResult = await until(page, () => location.href.includes('/result'), 25000);
  const isolatedReady = await until(page, () => {
    const els = Array.from(document.querySelectorAll('button[role=radio], input[type=radio]'));
    return els.some((r) => r.textContent && r.textContent.includes('المعزول') && !r.disabled);
  }, 15000);
  await new Promise((r) => setTimeout(r, 800));
  await shot('05-result-isolated');

  const transcriptReady = await until(page, () => document.querySelectorAll('.transcript__row').length > 0, 12000);
  const hasTranscript = transcriptReady;
  const originalBeforeRefresh = await isRadioEnabled(page, 'الأصل');
  await shot('06-result-full');

  await page.reload({ waitUntil: 'networkidle2', timeout: 20000 });
  const reachedResult2 = await until(page, () => location.href.includes('/result'), 20000);
  const isolatedReady2 = await until(page, () => {
    const els = Array.from(document.querySelectorAll('button[role=radio], input[type=radio]'));
    return els.some((r) => r.textContent && r.textContent.includes('المعزول'));
  }, 15000);
  await new Promise((r) => setTimeout(r, 800));
  const transcriptAfterRefresh = await until(page, () => document.querySelectorAll('.transcript__row').length > 0, 12000);
  // Contradiction check: the "no speech" empty state must not show while still loading.
  const emptyWhileLoading = await page.evaluate(() => {
    const text = document.body.innerText;
    const loadingPill = text.includes('في الانتظار') || text.includes('بيتفّرغ');
    const emptyState = text.includes('مفيش كلام اتعرف عليه');
    return loadingPill && emptyState;
  });
  await shot('07-after-refresh');
  const originalAfterRefresh = await isRadioEnabled(page, 'الأصل');

  const ov = await overflowInfo(page);
  return {
    viewport: viewport.name, screenshots: shots, focusSequence: focusSeq,
    uploadReady, facesReady, reachedResult, isolatedReady, hasTranscript,
    originalBeforeRefresh, reachedResult2, isolatedReady2, transcriptAfterRefresh, emptyWhileLoading,
    originalAfterRefresh, overflow: ov,
  };
}

async function main() {
  const browser = await puppeteer.launch({
    executablePath: CHROME, headless: 'new',
    args: ['--no-sandbox', '--disable-setuid-sandbox', '--disable-gpu', '--disable-dev-shm-usage'],
  });
  summary.launched = true;

  for (const vp of VIEWPORTS) {
    log(`viewport ${vp.name}`);
    const page = await browser.newPage();
    await page.setViewport({ width: vp.width, height: vp.height });
    const consoleMsgs = [], pageErrors = [], failedRequests = [];
    page.on('console', (m) => consoleMsgs.push({ type: m.type(), text: m.text().slice(0, 300) }));
    page.on('pageerror', (e) => pageErrors.push(String(e.message || e).slice(0, 300)));
    page.on('requestfailed', (req) => {
      const f = req.failure();
      failedRequests.push({ url: req.url().slice(0, 160), failure: f ? f.errorText : 'unknown' });
    });

    try {
      const run = await runFlow(page, vp);
      run.consoleErrors = consoleMsgs.filter((m) => m.type === 'error').length;
      run.consoleWarnings = consoleMsgs.filter((m) => m.type === 'warning').length;
      run.pageErrors = pageErrors.length;
      run.failedRequests = failedRequests.length;
      run.errorSamples = consoleMsgs.filter((m) => m.type === 'error').slice(0, 6);
      run.pageErrorSamples = pageErrors.slice(0, 6);
      run.requestFailureSamples = failedRequests.slice(0, 6);
      summary.runs.push(run);
      log(`  errors=${run.consoleErrors} warns=${run.consoleWarnings} pageErr=${run.pageErrors} failedReq=${run.failedRequests} overflow=${run.overflow.overflow}`);
    } catch (e) {
      log(`  FLOW EXCEPTION: ${e.message}`);
      summary.runs.push({ viewport: vp.name, exception: e.message, consoleErrors: consoleMsgs.filter((m) => m.type === 'error').length });
    } finally {
      await page.close();
    }
  }
  await browser.close();
  fs.writeFileSync(path.join(OUT_DIR, 'summary.json'), JSON.stringify(summary, null, 2));
  log('done ->', path.join(OUT_DIR, 'summary.json'));
}
main().catch((e) => {
  summary.launchError = e.message;
  fs.writeFileSync(path.join(OUT_DIR, 'summary.json'), JSON.stringify(summary, null, 2));
  console.error('HARNESS_ERROR', e);
  process.exit(1);
});
