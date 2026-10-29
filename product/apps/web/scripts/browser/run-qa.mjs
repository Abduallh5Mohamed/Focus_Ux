// Real-browser QA harness for the FOCUS web app.
// Drives the system Chrome headless against the running dev server and captures
// screenshots + console/page/network diagnostics at desktop, 390px and 320px.
//
// This is a QA tool and is NOT part of the app bundle. It resolves puppeteer-core
// from the app's node_modules (installed with --no-save).
//
// Usage: node scripts/browser/run-qa.mjs [baseUrl]
//   baseUrl defaults to http://localhost:5174

import puppeteer from 'puppeteer-core';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(__dirname, '../..');
const APP_ROOT = ROOT;
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

function log(...args) {
  console.log('[qa]', ...args);
}

async function findByText(page, selector, text, timeoutMs = 8000) {
  const handle = await page.waitForFunction(
    (sel, txt) => {
      const els = Array.from(document.querySelectorAll(sel));
      return els.find((e) => e.textContent && e.textContent.includes(txt)) || null;
    },
    { timeout: timeoutMs, polling: 200 },
    selector,
    text,
  );
  return handle;
}

async function clickByText(page, selector, text, timeoutMs = 8000) {
  const handle = await findByText(page, selector, text, timeoutMs);
  await handle.evaluate((el) => el.click());
}

async function waitForUrl(page, fragment, timeoutMs = 20000) {
  await page.waitForFunction(
    (frag) => location.href.includes(frag),
    { timeout: timeoutMs, polling: 200 },
    fragment,
  );
}

async function overflowInfo(page) {
  return page.evaluate(() => {
    const doc = document.documentElement;
    const body = document.body;
    const scrollW = Math.max(doc.scrollWidth, body.scrollWidth);
    const clientW = doc.clientWidth;
    // Find elements wider than the viewport to localise overflow.
    const offenders = [];
    const all = document.querySelectorAll('*');
    for (const el of all) {
      const r = el.getBoundingClientRect();
      if (r.right > clientW + 1 && r.width > 0) {
        offenders.push({
          tag: el.tagName.toLowerCase(),
          cls: (el.className || '').toString().slice(0, 60),
          right: Math.round(r.right),
          width: Math.round(r.width),
        });
        if (offenders.length >= 8) break;
      }
    }
    return { scrollWidth: scrollW, clientWidth: clientW, overflow: scrollW > clientW + 1, offenders };
  });
}

async function runFlow(page, viewport, runRecord) {
  const shots = {};
  const shot = async (name) => {
    const file = path.join(OUT_DIR, `${viewport.name}-${name}.png`);
    await page.screenshot({ path: file, fullPage: false });
    shots[name] = path.relative(APP_ROOT, file);
  };

  // 1) Home
  await page.goto(BASE_URL + '/', { waitUntil: 'networkidle2', timeout: 20000 });
  await page.waitForSelector('h1, .card__title', { timeout: 8000 });
  await shot('01-home');

  // Keyboard focus: tab from top, record active element sequence.
  const focusSeq = [];
  for (let i = 0; i < 6; i++) {
    await page.keyboard.press('Tab');
    const active = await page.evaluate(() => {
      const el = document.activeElement;
      if (!el) return null;
      return { tag: el.tagName.toLowerCase(), text: (el.textContent || '').trim().slice(0, 40), cls: (el.className || '').toString().slice(0, 40) };
    });
    focusSeq.push(active);
  }

  // 2) Upload page
  await clickByText(page, 'button', 'ابدأ برفع فيديو');
  await waitForUrl(page, '/upload');
  await page.waitForSelector('.drop', { timeout: 8000 });
  await shot('02-upload-empty');

  // 3) Select file
  const input = await page.$('input[type=file]');
  await input.uploadFile(FIXTURE);
  // Wait until the upload button is enabled (pre-checks pass / duration unknown allowed).
  await page.waitForFunction(
    () => {
      const btns = Array.from(document.querySelectorAll('button'));
      const b = btns.find((x) => x.textContent && x.textContent.includes('ارفع وابدأ'));
      return b && !b.disabled;
    },
    { timeout: 8000, polling: 150 },
  );
  await shot('03-upload-filled');

  // 4) Upload -> select faces
  await clickByText(page, 'button', 'ارفع وابدأ');
  await waitForUrl(page, '/select/');
  await page.waitForFunction(
    () => {
      const radios = document.querySelectorAll('input[type=radio][name="face-candidate"]');
      return radios.length > 0;
    },
    { timeout: 12000, polling: 250 },
  );
  await shot('04-select-faces');

  // 5) Choose first face + start
  await page.evaluate(() => {
    const radios = document.querySelectorAll('input[type=radio][name="face-candidate"]');
    radios[0].click();
  });
  await clickByText(page, 'button', 'ابدأ عزل الصوت');
  await waitForUrl(page, '/job/');

  // 6) Processing -> result (mock becomes ready within ~8s)
  await waitForUrl(page, '/result', 25000);
  await page.waitForFunction(
    () => {
      const els = Array.from(document.querySelectorAll('button[role=radio], input[type=radio]'));
      return els.some((r) => r.textContent && r.textContent.includes('المعزول') && !r.disabled);
    },
    { timeout: 15000, polling: 250 },
  );
  await new Promise((r) => setTimeout(r, 800));
  await shot('05-result-isolated');

  // Transcript present?
  const hasTranscript = await page.evaluate(() =>
    Array.from(document.querySelectorAll('.transcript__row, .transcript')).some((e) => e.textContent && e.textContent.length > 0),
  );

  const isRadioEnabled = (page, text) =>
    page.evaluate((txt) => {
      const els = Array.from(document.querySelectorAll('button[role=radio], input[type=radio]'));
      const el = els.find((r) => r.textContent && r.textContent.includes(txt));
      return el ? !el.disabled : false;
    }, text);

  // Original available before refresh? (in-memory file)
  const originalBeforeRefresh = await isRadioEnabled(page, 'الأصل');

  await shot('06-result-full');

  // 7) Reload to test post-refresh restoration
  await page.reload({ waitUntil: 'networkidle2', timeout: 20000 });
  await page.waitForFunction(
    () => location.href.includes('/result'),
    { timeout: 20000, polling: 200 },
  );
  await page.waitForFunction(
    () => {
      const els = Array.from(document.querySelectorAll('button[role=radio], input[type=radio]'));
      return els.some((r) => r.textContent && r.textContent.includes('المعزول'));
    },
    { timeout: 15000, polling: 250 },
  );
  await new Promise((r) => setTimeout(r, 800));
  await shot('07-after-refresh');

  const originalAfterRefresh = await isRadioEnabled(page, 'الأصل');

  const ov = await overflowInfo(page);

  return {
    viewport: viewport.name,
    screenshots: shots,
    focusSequence: focusSeq,
    hasTranscript,
    originalBeforeRefresh,
    originalAfterRefresh,
    overflow: ov,
  };
}

async function main() {
  const browser = await puppeteer.launch({
    executablePath: CHROME,
    headless: 'new',
    args: ['--no-sandbox', '--disable-setuid-sandbox', '--disable-gpu', '--disable-dev-shm-usage'],
  });
  summary.launched = true;

  for (const vp of VIEWPORTS) {
    log(`viewport ${vp.name} (${vp.width}x${vp.height})`);
    const page = await browser.newPage();
    await page.setViewport({ width: vp.width, height: vp.height });
    const consoleMsgs = [];
    const pageErrors = [];
    const failedRequests = [];
    page.on('console', (msg) => {
      consoleMsgs.push({ type: msg.type(), text: msg.text().slice(0, 300) });
    });
    page.on('pageerror', (err) => pageErrors.push(String(err.message || err).slice(0, 300)));
    page.on('requestfailed', (req) => {
      const failure = req.failure();
      failedRequests.push({ url: req.url().slice(0, 200), failure: failure ? failure.errorText : 'unknown' });
    });

    try {
      const run = await runFlow(page, vp, summary);
      const errors = consoleMsgs.filter((m) => m.type === 'error');
      run.consoleErrors = errors.length;
      run.consoleWarnings = consoleMsgs.filter((m) => m.type === 'warning').length;
      run.pageErrors = pageErrors.length;
      run.failedRequests = failedRequests.length;
      run.errorSamples = errors.slice(0, 6);
      run.pageErrorSamples = pageErrors.slice(0, 6);
      run.requestFailureSamples = failedRequests.slice(0, 6);
      summary.runs.push(run);
      log(`  console.errors=${run.consoleErrors} pageErrors=${run.pageErrors} failedReq=${run.failedRequests} overflow=${run.overflow.overflow}`);
    } catch (e) {
      log(`  FLOW FAILED: ${e.message}`);
      summary.runs.push({ viewport: vp.name, error: e.message });
    } finally {
      await page.close();
    }
  }

  await browser.close();
  fs.writeFileSync(path.join(OUT_DIR, 'summary.json'), JSON.stringify(summary, null, 2));
  log('done; summary ->', path.join(OUT_DIR, 'summary.json'));
}

main().catch((e) => {
  summary.launchError = e.message;
  fs.writeFileSync(path.join(OUT_DIR, 'summary.json'), JSON.stringify(summary, null, 2));
  console.error('HARNESS_ERROR', e);
  process.exit(1);
});
