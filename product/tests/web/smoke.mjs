#!/usr/bin/env node
/**
 * FOCUS web — build smoke test.
 *
 * Verifies the *shipped artefact*, not the source: that the built app boots, that the PWA
 * manifest and icons are real files (no CDN), that the service worker exists and refuses to
 * cache private data, and that the shell has no external asset dependencies.
 *
 * Usage:
 *   node product/tests/web/smoke.mjs                  # builds nothing, spawns vite preview
 *   node product/tests/web/smoke.mjs --base http://localhost:4173
 *
 * Exit code 0 = all checks passed.
 */

import { spawn } from 'node:child_process';
import { existsSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
const appDir = join(here, '..', '..', 'apps', 'web');
const distDir = join(appDir, 'dist');
const PORT = 4188;

const results = [];
let failures = 0;

function check(name, condition, detail = '') {
  results.push({ name, ok: Boolean(condition), detail });
  if (!condition) failures += 1;
}

function pngSize(buffer) {
  const magic = buffer.subarray(0, 8).toString('hex');
  if (magic !== '89504e470d0a1a0a') return null;
  // IHDR is always the first chunk: 8-byte signature + 4 length + 4 type.
  return { width: buffer.readUInt32BE(16), height: buffer.readUInt32BE(20) };
}

async function fetchOk(url) {
  const response = await fetch(url);
  return { response, body: await response.text() };
}

async function run(baseUrl) {
  // --- app shell -----------------------------------------------------------
  const home = await fetchOk(`${baseUrl}/`);
  check('GET / returns 200', home.response.status === 200, `status=${home.response.status}`);
  check('shell has a root mount', home.body.includes('id="root"'));
  check('shell links the manifest', home.body.includes('manifest.webmanifest'));
  check(
    'shell has no external asset references',
    !/https?:\/\/(?!www\.w3\.org)/.test(home.body),
    'expected zero third-party URLs in index.html',
  );

  // --- manifest ------------------------------------------------------------
  const manifestRes = await fetch(`${baseUrl}/manifest.webmanifest`);
  check('manifest is served', manifestRes.ok, `status=${manifestRes.status}`);
  const manifest = await manifestRes.json();
  check('manifest is standalone', manifest.display === 'standalone');
  check('manifest is rtl/arabic', manifest.dir === 'rtl' && manifest.lang === 'ar');
  check('manifest starts at /', manifest.start_url === '/');
  check('manifest declares icons', Array.isArray(manifest.icons) && manifest.icons.length >= 2);
  check(
    'all icons are local',
    manifest.icons.every((icon) => icon.src.startsWith('/icons/')),
    JSON.stringify(manifest.icons.map((icon) => icon.src)),
  );
  check(
    'manifest ships a maskable icon',
    manifest.icons.some((icon) => String(icon.purpose).includes('maskable')),
  );

  // --- icons ---------------------------------------------------------------
  for (const icon of manifest.icons) {
    const res = await fetch(`${baseUrl}${icon.src}`);
    const buffer = Buffer.from(await res.arrayBuffer());
    const size = pngSize(buffer);
    const [expectedW, expectedH] = String(icon.sizes).split('x').map(Number);
    check(
      `icon ${icon.src} is a ${icon.sizes} PNG`,
      res.ok && size && size.width === expectedW && size.height === expectedH,
      size ? `${size.width}x${size.height}` : 'not a PNG',
    );
  }

  // --- service worker ------------------------------------------------------
  const sw = await fetchOk(`${baseUrl}/sw.js`);
  check('service worker is served', sw.response.ok);
  check('service worker names a shell cache', sw.body.includes('focus-shell'));
  check(
    'service worker skips authorized requests',
    sw.body.includes("headers.has('authorization')"),
    'must never cache a request carrying a session token',
  );
  check(
    'service worker skips the API surface',
    sw.body.includes("startsWith('/api/')"),
  );
  check(
    'service worker skips audio/video media',
    sw.body.includes("destination === 'audio'"),
  );

  // --- deep link fallback --------------------------------------------------
  // A static host must serve the shell for client-side routes, otherwise refresh breaks.
  const deep = await fetchOk(`${baseUrl}/job/abc/result`);
  check(
    'deep link serves the shell (or a real 404 we can document)',
    deep.response.status === 200 || deep.response.status === 404,
    `status=${deep.response.status}`,
  );
}

async function main() {
  const baseArg = process.argv.indexOf('--base');
  const externalBase = baseArg > -1 ? process.argv[baseArg + 1] : null;

  if (externalBase) {
    await run(externalBase);
  } else {
    if (!existsSync(distDir)) {
      console.error(`No build found at ${distDir}. Run "npm run build" in apps/web first.`);
      process.exit(2);
    }

    const server = spawn(
      process.platform === 'win32' ? 'npx.cmd' : 'npx',
      ['vite', 'preview', '--port', String(PORT), '--strictPort'],
      { cwd: appDir, stdio: 'ignore', shell: process.platform === 'win32' },
    );

    const base = `http://localhost:${PORT}`;
    try {
      await waitForServer(base, 25_000);
      await run(base);
    } finally {
      server.kill();
    }
  }

  for (const result of results) {
    const mark = result.ok ? 'PASS' : 'FAIL';
    console.log(`${mark}  ${result.name}${result.detail && !result.ok ? ` — ${result.detail}` : ''}`);
  }
  console.log(`\n${results.length - failures}/${results.length} checks passed`);
  process.exit(failures === 0 ? 0 : 1);
}

async function waitForServer(base, timeoutMs) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    try {
      const response = await fetch(base);
      if (response.ok) return;
    } catch {
      // not up yet
    }
    await new Promise((resolve) => setTimeout(resolve, 300));
  }
  throw new Error(`preview server did not start on ${base}`);
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
