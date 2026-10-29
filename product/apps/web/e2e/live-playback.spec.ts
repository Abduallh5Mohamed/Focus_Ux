import { expect, test } from '@playwright/test';
import { createServer } from 'node:http';
import { installAudioProbe, markerWav, probe } from './audioProbe';
import type { LiveMetrics, LiveSessionView, PlaybackReport } from '../src/lib/live/types';
import { startupServer } from './startupServer';

/** Keep the real capture tracks so removing srcObject alone cannot pass cleanup checks. */
async function trackCapture(page: import('@playwright/test').Page) {
  await page.addInitScript(() => {
    const getUserMedia = navigator.mediaDevices.getUserMedia.bind(navigator.mediaDevices);
    const tracks: MediaStreamTrack[] = [];
    Object.assign(window, { captureTracks: tracks });
    navigator.mediaDevices.getUserMedia = async (constraints) => {
      const stream = await getUserMedia(constraints);
      tracks.push(...stream.getTracks());
      return stream;
    };
  });
}

/** Observe native resources; optionally leave the permission promise unresolved.
 * No synthetic pagehide dispatch or intercepted Stop fetch is used by these tests. */
async function observeStartup(page: import('@playwright/test').Page, pendingPermission = false) {
  await trackCapture(page);
  await installAudioProbe(page);
  await page.addInitScript((pending) => {
    const counts = { captureRequests: 0, recorderStarts: 0, audioContexts: 0 };
    Object.assign(window, { startupCounts: counts });
    const getUserMedia = navigator.mediaDevices.getUserMedia.bind(navigator.mediaDevices);
    navigator.mediaDevices.getUserMedia = async (constraints) => {
      counts.captureRequests++;
      if (pending) await new Promise<void>(() => {}); // Deterministic permission-pending startup.
      return getUserMedia(constraints);
    };
    window.AudioContext = new Proxy(AudioContext, {
      construct(target, args) {
        counts.audioContexts++;
        return Reflect.construct(target, args);
      },
    });
    const start = MediaRecorder.prototype.start;
    MediaRecorder.prototype.start = function (timeslice) {
      counts.recorderStarts++;
      start.call(this, timeslice);
    };
    window.addEventListener('pagehide', (event) => {
      navigator.sendBeacon('/__lifecycle', JSON.stringify({ event: 'pagehide', trusted: event.isTrusted }));
    });
    const nativeFetch = window.fetch;
    window.fetch = (input, init) => {
      if (String(input).endsWith('/stop')) {
        navigator.sendBeacon('/__lifecycle', JSON.stringify({ event: 'stop', keepalive: init?.keepalive === true }));
      }
      return nativeFetch(input, init);
    };
  }, pendingPermission);
}

async function startupCounts(page: import('@playwright/test').Page) {
  return page.evaluate(() => (window as unknown as {
    startupCounts: { captureRequests: number; recorderStarts: number; audioContexts: number };
  }).startupCounts);
}

async function setOwner(page: import('@playwright/test').Page, token: string) {
  await page.evaluate((token) => {
    localStorage.setItem('focus.session.v1', JSON.stringify({ token, videoId: null, jobId: null }));
  }, token);
}

for (const returnedOwner of [false, true]) {
  test(`late Create after route navigation cleans only the old startup (${returnedOwner ? 'returned' : 'original'} owner)`, async ({ page }) => {
    const api = await startupServer();
    const errors: string[] = [];
    page.on('pageerror', (error) => errors.push(error.message));
    await observeStartup(page);
    const stops = () => api.requests.filter((request) => request.path.endsWith('/stop'));
    try {
      await page.goto(`${api.origin}/live`);
      await setOwner(page, 'old-request-owner');
      await page.getByRole('button', { name: 'ابدأ التسجيل', exact: true }).click();
      await expect.poll(() => api.creates.length).toBe(1);
      expect(api.requests[0].authorization).toBe('Bearer old-request-owner');
      await expect(page.getByText('بنبدأ…', { exact: true })).toBeVisible();
      await page.getByRole('link', { name: 'ارفع فيديو', exact: true }).click();
      await expect(page).toHaveURL(`${api.origin}/upload`);
      expect(await startupCounts(page)).toEqual({ captureRequests: 0, recorderStarts: 0, audioContexts: 0 });
      expect((await probe(page)).starts).toEqual([]);
      expect(stops()).toEqual([]);

      // Start the replacement before the abandoned Create resolves.
      await setOwner(page, 'replacement-owner');
      await page.goBack();
      await page.getByRole('button', { name: 'ابدأ التسجيل', exact: true }).click();
      await expect.poll(() => api.creates.length).toBe(2);
      api.releaseCreate(1, 'replacement', 'replacement-owner');
      await expect(page.getByRole('button', { name: 'إيقاف التسجيل', exact: true })).toBeVisible();
      await expect.poll(async () => (await probe(page)).runs.some((run) => run.marker === 2)).toBe(true);
      const before = await startupCounts(page);
      expect(before).toEqual({ captureRequests: 1, recorderStarts: 1, audioContexts: 1 });

      api.releaseCreate(0, 'abandoned', returnedOwner ? 'old-returned-owner' : undefined);
      await expect.poll(() => stops().length).toBe(1);
      expect(stops()[0]).toMatchObject({
        method: 'POST', path: '/api/live/sessions/abandoned/stop', bytes: 0,
        authorization: `Bearer ${returnedOwner ? 'old-returned-owner' : 'old-request-owner'}`,
      });
      expect(api.evidence.filter((event) => event.event === 'stop')).toEqual([{ event: 'stop', keepalive: true }]);
      expect(api.evidence.some((event) => event.event === 'pagehide')).toBe(false); // SPA unmount, not document exit.
      expect(await startupCounts(page)).toEqual(before);
      expect(await page.evaluate(() => JSON.parse(localStorage.getItem('focus.session.v1')!).token))
        .toBe('replacement-owner');

      // A new poll/upload after old cleanup proves the replacement was not cancelled.
      const replacementRequests = () => api.requests.filter((request) =>
        request.path.startsWith('/api/live/sessions/replacement'));
      const afterCleanup = replacementRequests().length;
      await expect.poll(() => replacementRequests().length).toBeGreaterThan(afterCleanup);
      await page.getByRole('button', { name: 'إيقاف التسجيل', exact: true }).click();
      await expect(page.getByText('بنخلص', { exact: true })).toBeVisible();
      await expect.poll(() => page.evaluate(() => {
        const tracks = (window as unknown as { captureTracks: MediaStreamTrack[] }).captureTracks;
        return tracks.length === 2 && tracks.every((track) => track.readyState === 'ended');
      })).toBe(true);
      expect(stops().map((request) => request.path)).toEqual([
        '/api/live/sessions/abandoned/stop', '/api/live/sessions/replacement/stop',
      ]);
      expect(replacementRequests().every((request) => request.authorization === 'Bearer replacement-owner')).toBe(true);
      expect(api.requests.filter((request) => request.path.includes('/abandoned/'))).toEqual([stops()[0]]);
      expect(replacementRequests().some((request) => request.method === 'PUT' && request.bytes > 0)).toBe(true);
      expect((await probe(page)).starts.map((start) => start.marker)).toEqual([2]);
      expect(await startupCounts(page)).toEqual(before);
      expect(errors).toEqual([]);
    } finally {
      await page.close();
      await api.close();
    }
  });
}

for (const exit of ['navigation', 'close'] as const) {
  test(`native ${exit} delivers authenticated keepalive Stop for a known startup ID`, async ({ page }) => {
    const api = await startupServer();
    const errors: string[] = [];
    page.on('pageerror', (error) => errors.push(error.message));
    await observeStartup(page, true);
    try {
      await page.goto(`${api.origin}/live`);
      await setOwner(page, 'known-startup-owner');
      await page.getByRole('button', { name: 'ابدأ التسجيل', exact: true }).click();
      await expect.poll(() => api.creates.length).toBe(1);
      api.releaseCreate(0, 'known-startup');
      await expect.poll(() => startupCounts(page)).toEqual({
        captureRequests: 1, recorderStarts: 0, audioContexts: 1,
      });
      expect((await probe(page)).starts).toEqual([]);
      // The cleanup must retain its original identity even if browser storage changes.
      await setOwner(page, 'unrelated-new-owner');
      api.holdStops(); // Do not let a fast reply hide cancellation during document teardown.
      if (exit === 'navigation') {
        await page.goto(`${api.origin}/upload`); // Native document navigation, not router unmount.
        await expect(page).toHaveURL(`${api.origin}/upload`);
      } else {
        await page.close({ runBeforeUnload: true });
        await expect.poll(() => page.isClosed()).toBe(true);
      }
      await expect.poll(() => api.evidence.filter((event) => event.event === 'pagehide'))
        .toEqual([{ event: 'pagehide', trusted: true }]);
      await expect.poll(() => api.requests.filter((request) => request.path.endsWith('/stop')).length).toBe(1);
      expect(api.requests.filter((request) => request.path.includes('/known-startup/'))).toEqual([{
        path: '/api/live/sessions/known-startup/stop', method: 'POST',
        authorization: 'Bearer known-startup-owner', bytes: 0,
      }]);
      expect(api.evidence.filter((event) => event.event === 'stop')).toEqual([{ event: 'stop', keepalive: true }]);
      api.releaseStops();
      expect(errors).toEqual([]);
    } finally {
      if (!page.isClosed()) await page.close();
      await api.close();
    }
  });
}

test('a never-responding upload times out in order and stop finishes with an explicit gap', async ({ page }) => {
  await trackCapture(page);
  await page.clock.install();
  const uploads: number[] = [];
  const aborted: number[] = [];
  const received: number[] = [];
  let stopped = false;
  page.on('requestfailed', (request) => {
    const match = new URL(request.url()).pathname.match(/chunks\/(\d+)$/);
    if (match) aborted.push(Number(match[1]));
  });
  await page.route('**/api/live/sessions**', async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    const upload = path.match(/chunks\/(\d+)$/);
    if (upload) {
      const seq = Number(upload[1]);
      uploads.push(seq);
      if (seq === 0) return; // Never resolve, reject or release this request, including retries.
      received.push(seq);
      await route.fulfill({ json: { state: 'received', duplicate: false } });
    } else if (request.method() === 'POST' && path.endsWith('/sessions')) {
      await route.fulfill({ json: { live_session_id: 'timeout', chunk_ms: 300, max_chunks: 100 } });
    } else {
      if (path.endsWith('/stop')) {
        expect(uploads.filter((seq) => seq === 0)).toHaveLength(3);
        stopped = true;
      }
      await route.fulfill({ json: {
        live_session_id: 'timeout', phase: stopped ? 'finalizing' : 'live',
        mode: 'live', target_face_id: null, chunks: [], final: { status: null }, error: null,
      } });
    }
  });
  const errors: string[] = [];
  page.on('pageerror', (error) => errors.push(error.message));
  await page.goto('/live');
  await page.getByRole('button', { name: 'ابدأ التسجيل', exact: true }).click();
  await expect.poll(() => uploads).toEqual([0]);
  // Accumulate later chunks behind the stalled first upload, then stop capture.
  await page.waitForTimeout(650);
  await page.getByRole('button', { name: 'إيقاف التسجيل', exact: true }).click();
  await expect(page.getByText('بنوقف…', { exact: true })).toBeVisible();
  await expect.poll(() => page.evaluate(() => {
    const tracks = (window as unknown as { captureTracks: MediaStreamTrack[] }).captureTracks;
    return tracks.length >= 2 && tracks.every((track) => track.readyState === 'ended');
  })).toBe(true);
  expect(stopped).toBe(false);
  expect(uploads).toEqual([0]);
  for (const [attempt, backoff] of [[1, 300], [2, 600], [3, 0]]) {
    await page.clock.fastForward(10_000);
    await expect.poll(() => aborted.length).toBe(attempt);
    if (backoff) {
      await page.clock.fastForward(backoff);
      await expect.poll(() => uploads.length).toBe(attempt + 1);
      expect(uploads).toEqual(Array(attempt + 1).fill(0));
    }
  }
  await expect(page.getByText('مقاطع ما اترفعتش', { exact: true })).toBeVisible();
  await expect(page.getByText(/فشل رفع المقطع 0 بعد ٣ محاولات: الخادم ما ردّش/)).toBeVisible();
  await expect.poll(() => stopped).toBe(true);
  await expect(page.getByText('بنخلص', { exact: true })).toBeVisible();
  expect(received.length).toBeGreaterThan(0);
  expect(uploads).toEqual([0, 0, 0, ...received]);
  expect(received).toEqual(Array.from({ length: received.length }, (_, i) => i + 1));
  expect(errors).toEqual([]);
});

for (const outcome of ['timeout', 'unmount', 'pagehide'] as const) {
  test(`${outcome} cancels a never-responding stop without duplicate finalization or camera tracks`, async ({ page }) => {
    await trackCapture(page);
    await page.clock.install();
    let stops = 0;
    let aborted = 0;
    let polls = 0;
    const errors: string[] = [];
    page.on('pageerror', (error) => errors.push(error.message));
    page.on('requestfailed', (request) => {
      if (new URL(request.url()).pathname.endsWith('/stop')) aborted++;
    });
    await page.route('**/api/live/sessions**', async (route) => {
      const request = route.request();
      const path = new URL(request.url()).pathname;
      if (path.endsWith('/stop')) {
        stops++;
        return; // Leave finalization pending until the browser cancels the request.
      }
      if (/\/chunks\/\d+$/.test(path)) {
        await route.fulfill({ json: { state: 'received', duplicate: false } });
      } else if (request.method() === 'POST' && path.endsWith('/sessions')) {
        await route.fulfill({ json: { live_session_id: 'stop-timeout', chunk_ms: 300, max_chunks: 100 } });
      } else {
        polls++;
        await route.fulfill({ json: {
          phase: 'live', target_face_id: null, chunks: [], final: { status: null }, error: null,
        } });
      }
    });
    await page.goto('/live');
    await page.getByRole('button', { name: 'ابدأ التسجيل', exact: true }).click();
    await page.getByRole('button', { name: 'إيقاف التسجيل', exact: true }).click();
    await expect.poll(() => stops).toBe(1);
    await expect(page.getByText('بنوقف…', { exact: true })).toBeVisible();
    await expect.poll(() => page.evaluate(() => {
      const tracks = (window as unknown as { captureTracks: MediaStreamTrack[] }).captureTracks;
      return tracks.length >= 2 && tracks.every((track) => track.readyState === 'ended');
    })).toBe(true);
    if (outcome === 'timeout') {
      await page.clock.fastForward(10_000);
      await expect(page.getByText(/الخادم ما ردّش على طلب إنهاء التسجيل في الوقت المحدد/)).toBeVisible();
      await expect(page.getByText('بنوقف…', { exact: true })).not.toBeVisible();
    } else if (outcome === 'unmount') {
      await page.getByRole('link', { name: 'ارفع فيديو', exact: true }).click();
    } else {
      await page.evaluate(() => window.dispatchEvent(new PageTransitionEvent('pagehide')));
    }
    await expect.poll(() => aborted).toBe(1);
    // Drain a status request already in flight before checking that polling stays stopped.
    await page.waitForTimeout(100);
    const pollsAfterCancellation = polls;
    await page.clock.fastForward(60_000);
    expect(stops).toBe(1);
    expect(polls).toBe(pollsAfterCancellation);
    expect(errors).toEqual([]);
  });
}

for (const failure of [
  { name: '401 unauthorized', status: 401, error: 'انتهت الجلسة. ابدأ برفع الفيديو من جديد.' },
  { name: '403 forbidden', status: 403, error: 'انتهت الجلسة. ابدأ برفع الفيديو من جديد.' },
  { name: '500 retryable server error', status: 500, error: 'حصل خطأ في الخادم. جرّب تاني.' },
  { name: '503 retryable unavailable error', status: 503, error: 'المعالجة مشغولة حاليًا. جرّب بعد شوية.' },
  { name: 'immediate connection failure', status: null, error: 'تعذّر الوصول للخادم. اتأكد من الاتصال وجرّب تاني.' },
]) {
  test(`${failure.name} rejects stop without retrying, polling or keeping capture tracks`, async ({ page }) => {
    await trackCapture(page);
    await page.clock.install();
    let stops = 0;
    let polls = 0;
    let uploads = 0;
    const errors: string[] = [];
    page.on('pageerror', (error) => errors.push(error.message));
    await page.route('**/api/live/sessions**', async (route) => {
      const request = route.request();
      const path = new URL(request.url()).pathname;
      if (path.endsWith('/stop')) {
        stops++;
        expect(request.method()).toBe('POST');
        if (failure.status === null) await route.abort('connectionfailed');
        // Empty payload exercises production status mapping, including retryable 5xx.
        else await route.fulfill({ status: failure.status, json: {} });
      } else if (/\/chunks\/\d+$/.test(path)) {
        uploads++;
        await route.fulfill({ json: { state: 'received', duplicate: false } });
      } else if (request.method() === 'POST' && path.endsWith('/sessions')) {
        await route.fulfill({ json: { live_session_id: 'stop-rejected', chunk_ms: 300, max_chunks: 100 } });
      } else {
        expect(request.method()).toBe('GET');
        polls++;
        await route.fulfill({ json: {
          phase: 'live', target_face_id: null, chunks: [], final: { status: null }, error: null,
        } });
      }
    });
    await page.goto('/live');
    await page.getByRole('button', { name: 'ابدأ التسجيل', exact: true }).click();
    await expect.poll(() => polls).toBeGreaterThan(0);
    // Establish that recurring polling is active before finalization fails.
    await page.clock.runFor(600);
    await expect.poll(() => polls).toBeGreaterThan(1);
    await page.getByRole('button', { name: 'إيقاف التسجيل', exact: true }).click();
    const error = page.getByRole('alert').filter({ hasText: failure.error });
    await expect(error).toBeVisible();
    await expect(page.getByText('بنوقف…', { exact: true })).not.toBeVisible();
    await expect(page.getByText('بنخلص', { exact: true })).not.toBeVisible();
    await expect(page.getByRole('button', { name: 'ابدأ التسجيل', exact: true })).toBeVisible();
    await expect(page.getByRole('button', { name: 'إيقاف التسجيل', exact: true })).not.toBeVisible();
    await expect.poll(() => page.evaluate(() => {
      const tracks = (window as unknown as { captureTracks: MediaStreamTrack[] }).captureTracks;
      return ['audio', 'video'].every((kind) => tracks.some((track) => track.kind === kind))
        && tracks.every((track) => track.readyState === 'ended');
    })).toBe(true);
    await expect(page.locator('video').evaluate((video: HTMLVideoElement) => video.srcObject === null))
      .resolves.toBe(true);
    expect(stops).toBe(1);
    // Settle any in-flight status response, then pass the deadline and retry windows.
    await page.waitForTimeout(100);
    const pollsAfterFailure = polls;
    const uploadsAfterFailure = uploads;
    await page.clock.fastForward(60_000);
    await page.clock.runFor(1_000);
    expect(stops).toBe(1);
    expect(polls).toBe(pollsAfterFailure);
    expect(uploads).toBe(uploadsAfterFailure);
    await expect(error).toBeVisible();
    expect(errors).toEqual([]);
  });
}

test('finalization deadline cancels a JSON body stalled after headers without retrying or retaining camera tracks', async ({ page }) => {
  let stops = 0;
  let bodyConnectionClosed = false;
  // route.fulfill buffers bodies, so use a real streaming response for this regression.
  const server = createServer((request, response) => {
    response.setHeader('Access-Control-Allow-Origin', '*');
    response.setHeader('Access-Control-Allow-Headers', 'Authorization, Content-Type');
    if (request.method === 'OPTIONS') {
      response.writeHead(204);
      response.end();
      return;
    }
    stops++;
    response.writeHead(200, { 'Content-Type': 'application/json' });
    response.flushHeaders();
    response.write('{"phase":');
    response.on('close', () => { bodyConnectionClosed = true; });
    // Deliberately never end the body, even though headers have been delivered.
  });
  await new Promise<void>((resolve) => server.listen(0, '127.0.0.1', resolve));
  const address = server.address();
  if (!address || typeof address === 'string') throw new Error('Streaming server did not bind a port');
  try {
    await trackCapture(page);
    await page.clock.install();
    await page.addInitScript(() => {
      const json = Response.prototype.json;
      const bodyRead = { started: false, aborted: false, completed: false };
      Object.assign(window, { stopBodyRead: bodyRead });
      Response.prototype.json = async function () {
        if (!new URL(this.url).pathname.endsWith('/stop')) return json.call(this);
        bodyRead.started = true;
        try {
          const value = await json.call(this);
          bodyRead.completed = true;
          return value;
        } catch (error) {
          bodyRead.aborted = error instanceof DOMException && error.name === 'AbortError';
          throw error;
        }
      };
    });
    let polls = 0;
    const errors: string[] = [];
    page.on('pageerror', (error) => errors.push(error.message));
    await page.route('**/api/live/sessions**', async (route) => {
      const request = route.request();
      const path = new URL(request.url()).pathname;
      if (path.endsWith('/stop')) {
        await route.continue({ url: `http://127.0.0.1:${address.port}/stop` });
      } else if (/\/chunks\/\d+$/.test(path)) {
        await route.fulfill({ json: { state: 'received', duplicate: false } });
      } else if (request.method() === 'POST' && path.endsWith('/sessions')) {
        await route.fulfill({ json: { live_session_id: 'body-timeout', chunk_ms: 300, max_chunks: 100 } });
      } else {
        polls++;
        await route.fulfill({ json: {
          phase: 'live', target_face_id: null, chunks: [], final: { status: null }, error: null,
        } });
      }
    });
    await page.goto('/live');
    await page.getByRole('button', { name: 'ابدأ التسجيل', exact: true }).click();
    await page.getByRole('button', { name: 'إيقاف التسجيل', exact: true }).click();
    const bodyRead = () => page.evaluate(() =>
      (window as unknown as { stopBodyRead: { started: boolean; aborted: boolean; completed: boolean } }).stopBodyRead);
    const tracksReleased = () => page.evaluate(() => {
      const tracks = (window as unknown as { captureTracks: MediaStreamTrack[] }).captureTracks;
      return tracks.length >= 2 && tracks.every((track) => track.readyState === 'ended');
    });
    await expect.poll(bodyRead).toEqual({ started: true, aborted: false, completed: false });
    expect(stops).toBe(1);
    expect(bodyConnectionClosed).toBe(false);
    await expect(page.getByText('بنوقف…', { exact: true })).toBeVisible();
    await expect.poll(tracksReleased).toBe(true);
    await page.clock.fastForward(9_000);
    expect((await bodyRead()).aborted).toBe(false);
    await expect(page.getByText('بنوقف…', { exact: true })).toBeVisible();
    await page.clock.fastForward(1_000);
    await expect(page.getByText(
      'الخادم ما ردّش على طلب إنهاء التسجيل في الوقت المحدد. ممكن يكون لسه بيخلص؛ مش هنبعت طلب الإنهاء تاني تلقائيًا.',
      { exact: true },
    )).toBeVisible();
    await expect(page.getByText('بنوقف…', { exact: true })).not.toBeVisible();
    await expect.poll(bodyRead).toEqual({ started: true, aborted: true, completed: false });
    await expect.poll(() => bodyConnectionClosed).toBe(true);
    await page.waitForTimeout(100); // Let any already-in-flight status response settle.
    const pollsAfterTimeout = polls;
    await page.clock.fastForward(60_000);
    expect(stops).toBe(1);
    expect(polls).toBe(pollsAfterTimeout);
    expect(await tracksReleased()).toBe(true);
    expect(errors).toEqual([]);
  } finally {
    server.closeAllConnections();
    await new Promise<void>((resolve, reject) => server.close((error) => error ? reject(error) : resolve()));
  }
});

for (const teardown of ['unmount', 'pagehide'] as const) {
  test(`${teardown} cancels a pending upload without retrying or keeping camera tracks`, async ({ page }) => {
    await trackCapture(page);
    await page.clock.install();
    let uploads = 0;
    let aborted = 0;
    let stops = 0;
    page.on('requestfailed', (request) => {
      if (/\/chunks\/\d+\?/.test(request.url())) aborted++;
    });
    await page.route('**/api/live/sessions**', async (route) => {
      const path = new URL(route.request().url()).pathname;
      if (/\/chunks\/\d+$/.test(path)) {
        uploads++;
        return;
      }
      if (path.endsWith('/stop')) stops++;
      if (route.request().method() === 'POST' && path.endsWith('/sessions')) {
        await route.fulfill({ json: { live_session_id: 'teardown', chunk_ms: 300, max_chunks: 100 } });
      } else {
        await route.fulfill({ json: {
          phase: 'live', target_face_id: null, chunks: [], final: { status: null }, error: null,
        } });
      }
    });
    await page.goto('/live');
    await page.getByRole('button', { name: 'ابدأ التسجيل', exact: true }).click();
    await expect.poll(() => uploads).toBe(1);
    if (teardown === 'unmount') await page.getByRole('link', { name: 'ارفع فيديو', exact: true }).click();
    else await page.evaluate(() => window.dispatchEvent(new PageTransitionEvent('pagehide')));
    await expect.poll(() => aborted).toBe(1);
    await expect.poll(() => page.evaluate(() => {
      const tracks = (window as unknown as { captureTracks: MediaStreamTrack[] }).captureTracks;
      return tracks.length >= 2 && tracks.every((track) => track.readyState === 'ended');
    })).toBe(true);
    await page.clock.fastForward(60_000);
    expect(uploads).toBe(1);
    expect(stops).toBe(0);
  });
}

for (const scenario of [
  { final: 'ready', audio: 'delayed', report: 'ok' },
  { final: 'failed', audio: 'delayed', report: 'ok' },
  { final: 'ready', audio: 'http-error', report: 'ok' },
  { final: 'failed', audio: 'bad-wav', report: 'ok' },
  { final: 'ready', audio: 'timeout', report: 'ok' },
  { final: 'ready', audio: 'delayed', report: 'http-error' },
  { final: 'ready', audio: 'delayed', report: 'timeout' },
] as const) {
  test(`final ${scenario.final} waits for ${scenario.audio} audio; playback report ${scenario.report}`, async ({ page }) => {
    await installAudioProbe(page);
    // Keep a native decode pending after the HTTP response has completed, too.
    await page.addInitScript(() => {
      const decode = AudioContext.prototype.decodeAudioData;
      AudioContext.prototype.decodeAudioData = async function (wav) {
        const buffer = await decode.call(this, wav);
        if (Math.round(buffer.getChannelData(0)[0] * 10) === 3) {
          await new Promise<void>((resolve) => Object.assign(window, { releaseFinalDecode: resolve }));
        }
        return buffer;
      };
    });
    const reports: PlaybackReport[] = [];
    const events: string[] = [];
    let stopped = false;
    let terminalPolls = 0;
    let audioRequested = false;
    let reportAborted = false;
    page.on('requestfailed', (request) => {
      if (new URL(request.url()).pathname.endsWith('/playback')) reportAborted = true;
    });
    let releaseAudio!: () => void;
    const heldAudio = new Promise<void>((resolve) => { releaseAudio = resolve; });
    const view = (): LiveSessionView => ({
      live_session_id: 'late-final', experimental: true, phase: stopped ? 'done' : 'live',
      mode: 'live', chunk_ms: 300, target_face_id: 'face', first_video_id: null,
      faces_status: 'ready', queue_depth: 0, expected_seq: 4, overload_at_seq: null,
      error: null, counts: { duplicates: 0, out_of_order: 0, late_rejected: 0 },
      chunks: [0, 1, 2, 3].map((seq) => ({
        seq, state: seq === 1 ? 'missing' : 'ready', capture_start_ms: seq * 300,
        duration_ms: 300, error: null, warnings: [],
      })),
      final: { status: stopped ? scenario.final : null, video_id: null, job_id: null, error: null },
    });
    await page.route('**/api/live/sessions**', async (route) => {
      const request = route.request();
      const path = new URL(request.url()).pathname;
      const audio = path.match(/chunks\/(\d+)\/audio$/);
      if (audio) {
        const seq = Number(audio[1]);
        if (seq === 2) {
          audioRequested = true;
          await heldAudio;
          if (scenario.audio === 'http-error') {
            await route.fulfill({ status: 503, json: { code: 'UNAVAILABLE', message: 'test download failure' } });
            return;
          }
        }
        await route.fulfill({ contentType: 'audio/wav',
          body: seq === 2 && scenario.audio === 'bad-wav' ? Buffer.from('invalid WAV') : markerWav(seq + 1) });
      } else if (/chunks\/\d+$/.test(path)) {
        await route.fulfill({ json: { state: 'received', duplicate: false } });
      } else if (path.endsWith('/playback')) {
        events.push('report');
        reports.push(request.postDataJSON() as PlaybackReport);
        if (scenario.report === 'timeout') return; // The server never answers, including errors.
        if (scenario.report === 'http-error') {
          await route.fulfill({ status: 503, json: { code: 'UNAVAILABLE', message: 'test report failure' } });
          return;
        }
        await route.fulfill({ json: {} });
      } else if (path.endsWith('/metrics')) {
        events.push('metrics');
        const report = reports.at(-1)!;
        const metrics: LiveMetrics = {
          summary: {
            session_s: 1.2, chunks_total: 4, chunks_ready: 3, chunks_missing: 1, chunks_unusable: 0,
            chunks_duplicated: 0, rtf: null, max_queue_depth: 0, overload_at_seq: null,
            capture_to_play_s: { n: report.chunks.filter((c) => c.audible_wall_ms !== null).length,
              median: null, p95: null, max: null },
            playback: { underruns: report.underruns, rebuffers: report.rebuffers, duplicate_plays: 0 },
          },
          gate: { decision: 'internal_only', reasons: ['Synthetic regression, not GPU acceptance evidence'] },
        };
        await route.fulfill({ json: metrics });
      } else if (request.method() === 'POST' && path.endsWith('/sessions')) {
        await route.fulfill({ json: { live_session_id: 'late-final', chunk_ms: 300, max_chunks: 100 } });
      } else {
        if (path.endsWith('/stop')) stopped = true;
        else if (stopped) terminalPolls++;
        await route.fulfill({ json: view() });
      }
    });
    const errors: string[] = [];
    page.on('pageerror', (error) => errors.push(error.message));
    await page.goto('/live');
    await page.getByRole('button', { name: 'ابدأ التسجيل', exact: true }).click();
    try {
      await expect.poll(() => audioRequested).toBe(true);
      await expect.poll(async () => (await probe(page)).starts.map((s) => s.marker)).toEqual([1]);
      await page.getByRole('button', { name: 'إيقاف التسجيل', exact: true }).click();
      await expect.poll(() => terminalPolls).toBe(1);
      // Give the old, fire-and-forget report path time to run and expose the race.
      await page.waitForTimeout(650);
      expect(events).toEqual([]);
      expect(reports).toEqual([]);
      if (scenario.audio !== 'timeout') releaseAudio();
      if (scenario.audio === 'delayed') {
        await expect.poll(() => page.evaluate(() => 'releaseFinalDecode' in window)).toBe(true);
        expect(events).toEqual([]); // a completed HTTP response is not a completed decode
        await page.evaluate(() => (window as unknown as { releaseFinalDecode: () => void }).releaseFinalDecode());
      }
      const expectedEvents = scenario.report === 'ok' ? ['report', 'metrics'] : ['report'];
      await expect.poll(() => events, { timeout: 15_000 }).toEqual(expectedEvents);
      await expect(page.getByText('خلص', { exact: true })).toBeVisible({ timeout: 15_000 });
      if (scenario.report !== 'ok') {
        await expect(page.getByText(/تعذّر حفظ قياسات تشغيل الصوت/)).toBeVisible();
        if (scenario.report === 'timeout') await expect.poll(() => reportAborted).toBe(true);
        // No terminal polling/retry loop, and no stale metrics fetched after report failure.
        await page.waitForTimeout(650);
      }
      expect(reports).toHaveLength(1);
      const report = reports[0];
      expect(report.chunks.map((c) => c.seq)).toEqual([0, 1, 2, 3]);
      for (const chunk of report.chunks) {
        expect(Number.isFinite(chunk.capture_wall_ms)).toBe(true);
        expect(chunk.capture_wall_ms - report.chunks[0].capture_wall_ms).toBe(chunk.seq * 300);
        if (chunk.seq === 1 || (chunk.seq === 2 && scenario.audio !== 'delayed')) {
          expect(chunk.audible_wall_ms).toBeNull();
        } else {
          expect(chunk.audible_wall_ms).toEqual(expect.any(Number));
        }
      }
      expect(report.underruns).toBe(scenario.audio === 'delayed' ? 1 : 2);
      const expectedMarkers = scenario.audio === 'delayed' ? [1, 3, 4] : [1, 4];
      expect((await probe(page)).starts.map((s) => s.marker)).toEqual(expectedMarkers);
      if (scenario.audio === 'timeout') {
        // Even if a timed-out request eventually returns, it must not change the report or play.
        releaseAudio();
        await page.waitForTimeout(650);
        expect((await probe(page)).starts.map((s) => s.marker)).toEqual(expectedMarkers);
      }
      expect(terminalPolls).toBe(1);
      expect(events).toEqual(expectedEvents);
      expect(errors).toEqual([]);
    } finally {
      releaseAudio();
    }
  });
}

test('reordered audio stays ordered and continuous after rebuffer; stalled upload leaves an explicit gap', async ({ page }) => {
  await installAudioProbe(page);
  const uploads: number[] = [];
  const received = new Set<number>();
  const responses: number[] = [];
  let polls = 0;
  let missing = false;
  let stopped = false;
  let releaseUpload!: () => void;
  const stalled = new Promise<void>((resolve) => { releaseUpload = resolve; });
  const view = () => ({
    live_session_id: 'browser', experimental: true, phase: stopped ? 'finalizing' : 'live',
    mode: 'live', chunk_ms: 300, target_face_id: 'face', first_video_id: null,
    faces_status: 'ready', queue_depth: 0, expected_seq: received.size, overload_at_seq: null,
    error: null, counts: { duplicates: 0, out_of_order: 0, late_rejected: 0 },
    // Deliberately unsorted server response; repeat ready rows on every poll.
    chunks: received.has(2) ? [2, 0, 1, ...(missing ? [3] : []), ...(received.has(4) ? [4] : [])].map((seq) => ({
      seq, state: seq === 3 ? 'missing' : 'ready', capture_start_ms: seq * 300,
      duration_ms: 300, error: null, warnings: [],
    })) : [],
    final: { status: null, video_id: null, job_id: null, error: null },
  });
  await page.route('**/api/live/sessions**', async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const audio = url.pathname.match(/chunks\/(\d+)\/audio$/);
    const upload = url.pathname.match(/chunks\/(\d+)$/);
    if (audio) {
      const seq = Number(audio[1]);
      // Chunk 2 completes before 1; 1 misses its original playback slot.
      if (seq === 1) await new Promise((resolve) => setTimeout(resolve, 1600));
      responses.push(seq);
      await route.fulfill({ contentType: 'audio/wav', body: markerWav(seq + 1) });
    } else if (upload) {
      const seq = Number(upload[1]);
      uploads.push(seq);
      expect(request.postDataBuffer()!.length).toBeGreaterThan(0); // real MediaRecorder bytes
      if (seq === 3) {
        await stalled;
        missing = true;
        await route.fulfill({ status: 400, json: { code: 'BAD_CHUNK', message: 'test upload failure' } });
      } else {
        received.add(seq);
        await route.fulfill({ json: { state: 'received', duplicate: false } });
      }
    } else if (request.method() === 'POST' && url.pathname.endsWith('/sessions')) {
      await route.fulfill({ json: { live_session_id: 'browser', chunk_ms: 300, max_chunks: 100 } });
    } else {
      if (url.pathname.endsWith('/stop')) stopped = true;
      else polls++;
      await route.fulfill({ json: view() });
    }
  });
  const errors: string[] = [];
  page.on('pageerror', (error) => errors.push(error.message));
  await page.goto('/live');
  await page.getByRole('button', { name: 'ابدأ التسجيل', exact: true }).click();
  try {
    await expect.poll(async () => (await probe(page)).starts.length).toBe(3);
    expect(responses.slice(0, 3)).toEqual([2, 0, 1]);
    const audio = await probe(page);
    expect(audio.starts.map((s) => s.marker)).toEqual([1, 2, 3]);
    expect(audio.starts[1].at).toBeGreaterThan(audio.starts[0].at + audio.starts[0].duration);
    expect(audio.starts[2].at).toBeCloseTo(audio.starts[1].at + audio.starts[1].duration, 4);
    await expect.poll(async () => (await probe(page)).runs.filter((r) => r.marker > 0).map((r) => r.marker))
      .toEqual([1, 2, 3]);
    const rendered = (await probe(page)).runs;
    const second = rendered.findIndex((r) => r.marker === 2);
    if (rendered[second + 1].marker === 0) {
      // Resampling may round the boundary by a sample; never allow an audible gap.
      expect(rendered[second + 2].marker).toBe(3);
      expect(rendered[second + 2].frame - rendered[second + 1].frame).toBeLessThanOrEqual(128);
    } else {
      expect(rendered[second + 1].marker).toBe(3);
    }
    expect(uploads).toEqual([0, 1, 2, 3]); // no upload overtakes the stalled request
    const before = polls;
    await expect.poll(() => polls).toBeGreaterThan(before);
    await expect(page.getByText('الصوت اتأخر', { exact: true })).toBeVisible();
    await page.getByRole('button', { name: 'إيقاف التسجيل', exact: true }).click();
    await expect(page.getByText('بنوقف…', { exact: true })).toBeVisible();
    expect(stopped).toBe(false); // stop waits for the upload queue, but releases the camera
    await expect.poll(() => page.locator('video').evaluate((video: HTMLVideoElement) => video.srcObject === null))
      .toBe(true);
    releaseUpload();
    await expect(page.getByText('مقاطع ما اترفعتش', { exact: true })).toBeVisible();
    await expect(page.getByText('#3: ناقص', { exact: true })).toBeVisible();
    await expect.poll(() => stopped).toBe(true);
    await expect.poll(async () => (await probe(page)).runs.filter((r) => r.marker > 0).map((r) => r.marker))
      .toEqual([1, 2, 3, 5]);
    const finished = await probe(page);
    expect(finished.starts.map((s) => s.marker)).toEqual([1, 2, 3, 5]); // repeated polls never replay
    expect(errors).toEqual([]);
  } finally {
    releaseUpload();
  }
});

test('native decode completion cannot reorder chunks or restart a closed player', async ({ page }) => {
  await installAudioProbe(page);
  await page.goto('/live');
  const wavs = [markerWav(1), markerWav(2)].map((wav) => [...wav]);
  await page.evaluate(async (bytes) => {
    // Import the production player through Vite; only the decode resolution is delayed.
    const path = '/src/lib/live/LivePlayer.ts';
    const { LivePlayer } = await import(/* @vite-ignore */ path);
    const decode = AudioContext.prototype.decodeAudioData;
    AudioContext.prototype.decodeAudioData = async function (wav) {
      const result = await decode.call(this, wav);
      if (Math.round(result.getChannelData(0)[0] * 10) === 1) {
        await new Promise((resolve) => setTimeout(resolve, 400));
      }
      return result;
    };
    const player = new LivePlayer(() => Date.now());
    await player.unlock();
    await Promise.all([
      player.enqueue(0, 0, 300, new Uint8Array(bytes[0]).buffer),
      player.enqueue(1, 300, 300, new Uint8Array(bytes[1]).buffer),
      player.enqueue(1, 300, 300, new Uint8Array(bytes[1]).buffer),
    ]);
    Object.assign(window, { browserPlayer: player });
  }, wavs);
  expect((await probe(page)).starts.map((s) => s.marker)).toEqual([1, 2]);
  await expect.poll(async () => (await probe(page)).runs.filter((r) => r.marker > 0).map((r) => r.marker))
    .toEqual([1, 2]);
  await page.evaluate(async (bytes) => {
    const path = '/src/lib/live/LivePlayer.ts';
    const { LivePlayer } = await import(/* @vite-ignore */ path);
    const player = new LivePlayer(() => Date.now());
    await player.unlock();
    const pending = player.enqueue(0, 0, 300, new Uint8Array(bytes).buffer);
    player.close();
    await pending;
    // A late callback must not create another AudioContext or source.
    await player.enqueue(1, 300, 300, new Uint8Array(bytes).buffer);
    if (player.report().chunks.length !== 0) throw new Error('Closed player scheduled audio');
  }, wavs[0]);
  expect((await probe(page)).starts.map((s) => s.marker)).toEqual([1, 2]);
});
