import { useCallback, useEffect, useRef, useState } from 'react';

import { startCapture, type Capture, type CapturedChunk } from '../../lib/live/capture';
import type { LiveApi } from '../../lib/live/liveApi';
import { LivePlayer } from '../../lib/live/LivePlayer';
import type { LiveMetrics, LiveSessionView } from '../../lib/live/types';
import { describeError } from '../../lib/api/errors';
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
const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

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
    fetched: Set<number>;
    poll: number | null;
    closed: boolean;
    stopping: boolean;
  }>({ id: null, capture: null, player: null, uploads: Promise.resolve(), fetched: new Set(), poll: null, closed: false, stopping: false });

  const patch = useCallback((next: Partial<LiveSessionState>) => setState((prev) => ({ ...prev, ...next })), []);

  const release = useCallback(async () => {
    const current = live.current;
    if (current.poll !== null) window.clearTimeout(current.poll);
    current.poll = null;
    await current.capture?.stop();
    current.capture = null;
  }, []);

  const fail = useCallback(
    async (message: string) => {
      await release();
      live.current.player?.close();
      patch({ phase: 'error', error: message, stream: null });
    },
    [patch, release],
  );

  const uploadChunk = useCallback(
    (chunk: CapturedChunk) => {
      const current = live.current;
      current.uploads = current.uploads.then(async () => {
        if (!current.id) return;
        for (let attempt = 0; attempt < UPLOAD_TRIES; attempt += 1) {
          try {
            await api.putChunk(current.id, {
              seq: chunk.seq, captureStartMs: chunk.captureStartMs, durationMs: chunk.durationMs, blob: chunk.blob,
            });
            return;
          } catch (caught) {
            const retryable = (caught as { retryable?: boolean }).retryable !== false;
            if (!retryable || attempt === UPLOAD_TRIES - 1) break;
            await sleep(300 * 2 ** attempt);
          }
        }
        setState((prev) => ({ ...prev, uploadFailures: [...prev.uploadFailures, chunk.seq] }));
      });
    },
    [api],
  );

  const pump = useCallback(async () => {
    const current = live.current;
    if (current.closed || !current.id) return;
    try {
      const view = await api.get(current.id);
      patch({ view, rebuffers: current.player?.rebuffers ?? 0 });
      if (view.phase === 'failed' && !view.final.status) {
        await fail(view.error?.message ?? 'الجلسة فشلت.');
        return;
      }
      if (view.target_face_id && current.player) {
        for (const chunk of view.chunks) {
          if (chunk.state === 'ready' && !current.fetched.has(chunk.seq)) {
            current.fetched.add(chunk.seq);
            void api
              .chunkAudio(current.id, chunk.seq)
              .then((wav) => current.player?.enqueue(chunk.seq, chunk.capture_start_ms, chunk.duration_ms, wav))
              .catch(() => {
                current.fetched.delete(chunk.seq);
              });
          }
        }
      }
      if (view.final.status === 'ready' || view.final.status === 'failed') {
        if (current.player) await api.postPlayback(current.id, current.player.report()).catch(() => undefined);
        const metrics = await api.metrics(current.id).catch(() => null);
        if (view.final.status === 'ready' && view.final.job_id && view.final.video_id) {
          saveSession({ videoId: view.final.video_id, jobId: view.final.job_id });
        }
        patch({ phase: 'done', metrics });
        return;
      }
    } catch (caught) {
      patch({ error: describeError(caught).title });
    }
    current.poll = window.setTimeout(() => void pump(), POLL_MS);
  }, [api, fail, patch]);

  const start = useCallback(async () => {
    const current = live.current;
    current.closed = false;
    current.stopping = false;
    current.fetched = new Set();
    current.uploads = Promise.resolve();
    patch({ phase: 'starting', error: null, view: null, metrics: null, uploadFailures: [], rebuffers: 0 });
    try {
      const created = await api.create();
      if (current.closed) return;
      if (created.session_token) saveSession({ token: created.session_token });
      current.id = created.live_session_id;
      const player = new LivePlayer(() => current.capture?.startedWallMs ?? Date.now());
      await player.unlock();
      if (current.closed) {
        player.close();
        return;
      }
      current.player = player;
      const capture = await startCapture({
        chunkMs: created.chunk_ms, onChunk: uploadChunk, onError: (m) => void fail(m),
      });
      if (current.closed) {
        // Left the screen while the camera permission was pending: release it at once.
        await capture.stop();
        player.close();
        return;
      }
      current.capture = capture;
      patch({ phase: 'recording', stream: current.capture.stream });
      void pump();
    } catch (caught) {
      await fail(caught instanceof Error && !('code' in caught) ? caught.message : describeError(caught).detail);
    }
  }, [api, fail, patch, pump, uploadChunk]);

  const stop = useCallback(async () => {
    const current = live.current;
    if (!current.id || current.stopping) return;
    current.stopping = true;
    patch({ phase: 'stopping' });
    await current.capture?.stop(); // final chunk delivered, camera and mic released
    current.capture = null;
    patch({ stream: null });
    await current.uploads;
    try {
      await api.stop(current.id);
      patch({ phase: 'finishing' });
    } catch (caught) {
      patch({ error: describeError(caught).title });
    }
  }, [api, patch]);

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
    const current = live.current;
    const onHide = () => void current.capture?.stop();
    window.addEventListener('pagehide', onHide);
    return () => {
      window.removeEventListener('pagehide', onHide);
      current.closed = true;
      if (current.poll !== null) window.clearTimeout(current.poll);
      void current.capture?.stop();
      current.player?.close();
    };
  }, []);

  return { state, start, stop, selectTarget, liveId: live.current.id };
}
