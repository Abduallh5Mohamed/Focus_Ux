import { useCallback, useEffect, useRef, useState } from 'react';

import { startCapture, type Capture, type CapturedChunk } from '../../lib/live/capture';
import type { LiveApi } from '../../lib/live/liveApi';
import { LivePlayer } from '../../lib/live/LivePlayer';
import type { LiveMetrics, LiveSessionView, PlaybackReport } from '../../lib/live/types';
import { ApiError, describeError } from '../../lib/api/errors';
import { saveSession } from '../../lib/session';

export type LivePhase = 'idle' | 'starting' | 'recording' | 'stopping' | 'finishing' | 'done' | 'error';

export interface LiveSessionState {
  phase: LivePhase;
  view: LiveSessionView | null;
  stream: MediaStream | null;
  metrics: LiveMetrics | null;
  /** Chunks the browser could not upload after retries (explicit, never silent). */
  uploadFailures: number[];
  rebuffers: number;
  error: string | null;
}

const POLL_MS = 500;
const UPLOAD_TRIES = 3;
const AUDIO_TIMEOUT_MS = 10_000;
const REPORT_TIMEOUT_MS = 10_000;
const UPLOAD_TIMEOUT_MS = 10_000;
const STOP_TIMEOUT_MS = 10_000;
const STOP_TIMEOUT_MESSAGE = 'الخادم ما ردّش على طلب إنهاء التسجيل في الوقت المحدد. ممكن يكون لسه بيخلص؛ مش هنبعت طلب الإنهاء تاني تلقائيًا.';
const sleep = (ms: number, signal: AbortSignal) => new Promise<void>((resolve) => {
  const done = () => {
    clearTimeout(timer);
    signal.removeEventListener('abort', done);
    resolve();
  };
  const timer = setTimeout(done, ms);
  signal.addEventListener('abort', done, { once: true });
  if (signal.aborted) done();
});

/** Bound the entire upload, including reading its response body. */
async function putChunk(api: LiveApi, id: string, chunk: CapturedChunk, signal: AbortSignal) {
  const request = new AbortController();
  const cancel = () => request.abort();
  signal.addEventListener('abort', cancel, { once: true });
  if (signal.aborted) cancel();
  let timedOut = false;
  const timer = setTimeout(() => {
    timedOut = true;
    request.abort();
  }, UPLOAD_TIMEOUT_MS);
  try {
    await api.putChunk(id, chunk, request.signal);
  } catch (caught) {
    // The transport reports ABORTED as non-retryable; our own deadline is retryable.
    if (timedOut && !signal.aborted) {
      throw new ApiError({
        code: 'TIMEOUT', message: 'انتهت مهلة رفع المقطع.', retryable: true,
      });
    }
    throw caught;
  } finally {
    clearTimeout(timer);
    signal.removeEventListener('abort', cancel);
  }
}

/** Telemetry must not keep a completed recording in the finishing screen. */
async function savePlayback(api: LiveApi, id: string, report: PlaybackReport, signal: AbortSignal) {
  const controller = new AbortController();
  let cancel!: () => void;
  let timer!: ReturnType<typeof setTimeout>;
  const expired = new Promise<never>((_, reject) => {
    cancel = () => {
      controller.abort();
      reject(new Error('Playback report cancelled'));
    };
    signal.addEventListener('abort', cancel, { once: true });
    timer = setTimeout(() => {
      controller.abort();
      reject(new Error('Playback report timed out'));
    }, REPORT_TIMEOUT_MS);
    if (signal.aborted) cancel();
  });
  try {
    await Promise.race([api.postPlayback(id, report, controller.signal), expired]);
  } finally {
    clearTimeout(timer);
    signal.removeEventListener('abort', cancel);
  }
}

/**
 * Orchestrates camera capture, ordered chunk upload, status polling and continuous
 * playback. The camera is released on stop, on error and when the screen unmounts.
 */
export function useLiveSession(api: LiveApi) {
  const [state, setState] = useState<LiveSessionState>({
    phase: 'idle', view: null, stream: null, metrics: null, uploadFailures: [], rebuffers: 0, error: null,
  });
  const live = useRef<{
    id: string | null;
    capture: Capture | null;
    player: LivePlayer | null;
    uploads: Promise<void>;
    downloads: Set<Promise<void>>;
    fetched: Set<number>;
    poll: number | null;
    closed: boolean;
    stopping: boolean;
    cancellation: AbortController;
    starting: boolean;
    sessionToken?: string;
    cleanupRequested: boolean;
  }>({ id: null, capture: null, player: null, uploads: Promise.resolve(), downloads: new Set(), fetched: new Set(), poll: null, closed: false, stopping: false, cancellation: new AbortController(), starting: false, cleanupRequested: false });

  const patch = useCallback((next: Partial<LiveSessionState>) => setState((prev) => ({ ...prev, ...next })), []);

  const cleanupStartup = useCallback((current: typeof live.current) => {
    if (!current.starting || !current.id || current.cleanupRequested) return;
    current.cleanupRequested = true;
    // Do not abort Create: its response is needed to identify and authenticate cleanup.
    // Stop is idempotent; finalizing an empty session releases the server's active slot.
    void api.stop(current.id, { sessionToken: current.sessionToken, keepalive: true })
      .catch((error) => console.warn('Could not stop interrupted live startup', error));
  }, [api]);

  const release = useCallback(async (current = live.current) => {
    current.closed = true;
    current.cancellation.abort();
    if (current.poll !== null) window.clearTimeout(current.poll);
    current.poll = null;
    current.player?.close();
    cleanupStartup(current);
    await current.capture?.stop();
    current.capture = null;
  }, [cleanupStartup]);

  const fail = useCallback(
    async (message: string, current = live.current) => {
      if (current.closed || current !== live.current) return;
      await release(current);
      if (current !== live.current) return;
      patch({ phase: 'error', error: message, stream: null });
    },
    [patch, release],
  );

  const uploadChunk = useCallback(
    (chunk: CapturedChunk, current = live.current) => {
      current.uploads = current.uploads.then(async () => {
        const signal = current.cancellation.signal;
        if (!current.id || signal.aborted) return;
        let timedOut = false;
        for (let attempt = 0; attempt < UPLOAD_TRIES; attempt += 1) {
          try {
            await putChunk(api, current.id, chunk, signal);
            return;
          } catch (caught) {
            if (signal.aborted) return;
            timedOut = (caught as { code?: string }).code === 'TIMEOUT';
            const retryable = (caught as { retryable?: boolean }).retryable !== false;
            if (!retryable || attempt === UPLOAD_TRIES - 1) break;
            await sleep(300 * 2 ** attempt, signal);
            if (signal.aborted) return;
          }
        }
        setState((prev) => ({
          ...prev,
          uploadFailures: [...prev.uploadFailures, chunk.seq],
          ...(timedOut ? { error: `فشل رفع المقطع ${chunk.seq} بعد ٣ محاولات: الخادم ما ردّش في الوقت المحدد. المقطع هيظهر ناقص.` } : {}),
        }));
      });
    },
    [api],
  );

  const pump = useCallback(async () => {
    const current = live.current;
    if (current.closed || !current.id) return;
    try {
      const view = await api.get(current.id, current.cancellation.signal);
      if (current.closed) return;
      patch({ view, rebuffers: current.player?.rebuffers ?? 0 });
      if (view.phase === 'failed' && !view.final.status) {
        await fail(view.error?.message ?? 'الجلسة فشلت.');
        return;
      }
      const player = current.player;
      player?.updateChunks(view.chunks);
      if (view.target_face_id && player) {
        for (const chunk of view.chunks) {
          if (chunk.state === 'ready' && !current.fetched.has(chunk.seq)) {
            current.fetched.add(chunk.seq);
            const controller = new AbortController();
            const signal = current.cancellation.signal;
            let cancel!: () => void;
            let timeout!: number;
            // Bound the entire fetch/body/decode operation, not just response headers.
            const expired = new Promise<never>((_, reject) => {
              cancel = () => {
                controller.abort();
                reject(new Error('Live audio cancelled'));
              };
              signal.addEventListener('abort', cancel, { once: true });
              timeout = window.setTimeout(() => {
                controller.abort();
                reject(new Error('Live audio timed out'));
              }, AUDIO_TIMEOUT_MS);
              if (signal.aborted) cancel();
            });
            const download = Promise.race([
              api.chunkAudio(current.id, chunk.seq, controller.signal)
                .then((wav) => player.enqueue(chunk.seq, chunk.capture_start_ms, chunk.duration_ms, wav, controller.signal)),
              expired,
            ])
              .catch(() => {
                current.fetched.delete(chunk.seq);
              })
              .finally(() => {
                window.clearTimeout(timeout);
                signal.removeEventListener('abort', cancel);
                current.downloads.delete(download);
              });
            current.downloads.add(download);
          }
        }
      }
      if (view.final.status === 'ready' || view.final.status === 'failed') {
        // Terminal server state does not imply that browser audio is ready.
        await Promise.all(current.downloads);
        if (current.closed) return;
        let metrics: LiveMetrics | null = null;
        let reportError: string | null = null;
        try {
          if (player) {
            player.finish();
            await savePlayback(api, current.id, player.report(), current.cancellation.signal);
          }
          if (current.closed) return;
          metrics = await api.metrics(current.id).catch(() => null);
        } catch {
          // Still expose the final result, but never fetch stale/partial playback metrics.
          reportError = 'تعذّر حفظ قياسات تشغيل الصوت. انتهت الجلسة، لكن قياسات التشغيل لم تُحفظ.';
        }
        if (current.closed) return;
        if (view.final.status === 'ready' && view.final.job_id && view.final.video_id) {
          saveSession({ videoId: view.final.video_id, jobId: view.final.job_id });
        }
        patch({ phase: 'done', metrics, ...(reportError ? { error: reportError } : {}) });
        return;
      }
    } catch (caught) {
      if (current.closed) return;
      patch({ error: describeError(caught).title });
    }
    if (!current.closed) current.poll = window.setTimeout(() => void pump(), POLL_MS);
  }, [api, fail, patch]);

  const start = useCallback(async () => {
    void release(live.current);
    const current: typeof live.current = {
      ...live.current, id: null, capture: null, player: null, poll: null,
      closed: false, stopping: false, fetched: new Set<number>(),
      uploads: Promise.resolve(), cancellation: new AbortController(),
      starting: true, sessionToken: undefined, cleanupRequested: false,
    };
    live.current = current;
    current.downloads = new Set();
    patch({ phase: 'starting', error: null, view: null, metrics: null, uploadFailures: [], rebuffers: 0 });
    try {
      const created = await api.create();
      current.id = created.live_session_id;
      current.sessionToken = created.session_token;
      if (current.closed) {
        cleanupStartup(current);
        return;
      }
      if (created.session_token) saveSession({ token: created.session_token });
      // Capture's object is cleared on stop; late audio still needs its original clock.
      let captureWallOrigin = Date.now();
      const player = new LivePlayer(() => captureWallOrigin);
      current.player = player;
      await player.unlock();
      if (current.closed) {
        player.close();
        return;
      }
      const capture = await startCapture({
        chunkMs: created.chunk_ms, onChunk: (chunk) => uploadChunk(chunk, current),
        onError: (m) => void fail(m, current), signal: current.cancellation.signal,
      });
      captureWallOrigin = capture.startedWallMs;
      if (current.closed) {
        // Left the screen while the camera permission was pending: release it at once.
        await capture.stop();
        player.close();
        return;
      }
      current.capture = capture;
      current.starting = false;
      patch({ phase: 'recording', stream: current.capture.stream });
      void pump();
    } catch (caught) {
      await fail(caught instanceof Error && !('code' in caught) ? caught.message : describeError(caught).detail, current);
    }
  }, [api, cleanupStartup, fail, patch, pump, release, uploadChunk]);

  const stop = useCallback(async () => {
    const current = live.current;
    if (!current.id || current.stopping) return;
    current.stopping = true;
    patch({ phase: 'stopping' });
    await current.capture?.stop(); // final chunk delivered, camera and mic released
    current.capture = null;
    patch({ stream: null });
    await current.uploads;
    if (current.closed) return;
    const request = new AbortController();
    const cancel = () => request.abort();
    const signal = current.cancellation.signal;
    signal.addEventListener('abort', cancel, { once: true });
    if (signal.aborted) cancel();
    let timedOut = false;
    // One attempt only: aborting the response does not undo server finalization.
    // Keep the deadline active through response-body parsing, not just headers.
    const timer = setTimeout(() => {
      timedOut = true;
      request.abort();
    }, STOP_TIMEOUT_MS);
    try {
      await api.stop(current.id, { signal: request.signal });
      if (current.closed) return;
      patch({ phase: 'finishing' });
    } catch (caught) {
      if (!current.closed) await fail(timedOut ? STOP_TIMEOUT_MESSAGE : describeError(caught).title);
    } finally {
      clearTimeout(timer);
      signal.removeEventListener('abort', cancel);
    }
  }, [api, fail, patch]);

  const selectTarget = useCallback(
    async (faceId: string) => {
      const current = live.current;
      if (!current.id) return;
      const view = await api.setTarget(current.id, faceId);
      patch({ view });
    },
    [api, patch],
  );

  // Leaving the screen must never leave the camera or audio running.
  useEffect(() => {
    const onHide = () => {
      void release(live.current);
    };
    window.addEventListener('pagehide', onHide);
    return () => {
      window.removeEventListener('pagehide', onHide);
      onHide();
    };
  }, [release]);

  return { state, start, stop, selectTarget, liveId: live.current.id };
}
