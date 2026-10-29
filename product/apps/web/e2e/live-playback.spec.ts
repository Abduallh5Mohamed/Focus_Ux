import { expect, test } from '@playwright/test';
import { installAudioProbe, markerWav, probe } from './audioProbe';

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
