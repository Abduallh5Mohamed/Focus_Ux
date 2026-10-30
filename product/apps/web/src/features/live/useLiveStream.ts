import { useCallback, useEffect, useRef, useState } from 'react';

import { describeError } from '../../lib/api/errors';
import { saveSession } from '../../lib/session';
import { startStreamCapture, type StreamCapture } from '../../lib/live/streamCapture';
import { StreamPlayer } from '../../lib/live/StreamPlayer';
import type { StreamApi } from '../../lib/live/streamApi';
import type { StreamMetrics, StreamView } from '../../lib/live/streamTypes';
import type { StreamRecord } from '../../lib/live/streamProto';

export type StreamUiPhase = 'idle' | 'starting' | 'recording' | 'stopping' | 'finishing' | 'done' | 'error';

export interface LiveStreamState {
  phase: StreamUiPhase;
  view: StreamView | null;
  stream: MediaStream | null;
  metrics: StreamMetrics | null;
  rebuffers: number;
  partStates: Record<string, number>;
  sendFailures: number;
  error: string | null;
}

const VIEW_POLL_MS = 500;
const SEND_TRIES = 3;

/** Continuous live session: ordered batch upload, long-polled parts, gapless playback. */
export function useLiveStream(api: StreamApi) {
  const [state, setState] = useState<LiveStreamState>({
    phase: 'idle', view: null, stream: null, metrics: null, rebuffers: 0, partStates: {}, sendFailures: 0, error: null,
  });
  const live = useRef({
    id: null as string | null, token: undefined as string | undefined,
    capture: null as StreamCapture | null, player: null as StreamPlayer | null,
    sends: Promise.resolve(), seq: 0, closed: false, stopping: false, after: -1,
    abort: new AbortController(), timer: null as number | null, outLoop: null as Promise<void> | null,
  });
  const patch = useCallback((p: Partial<LiveStreamState>) => setState((s) => ({ ...s, ...p })), []);

  const release = useCallback(async (cur = live.current) => {
    cur.closed = true;
    cur.abort.abort();
    if (cur.timer !== null) window.clearTimeout(cur.timer);
    cur.timer = null;
    cur.player?.close();
    await cur.capture?.stop();
    cur.capture = null;
  }, []);

  const fail = useCallback(async (message: string) => {
    const cur = live.current;
    if (cur.closed) return;
    const id = cur.id;
    const token = cur.token;
    await release(cur);
    if (id) void api.stop(id, { sessionToken: token, keepalive: true }).catch(() => undefined);
    patch({ phase: 'error', error: message, stream: null });
  }, [api, patch, release]);

  const send = useCallback((records: StreamRecord[]) => {
    const cur = live.current;
    const seq = cur.seq++;
    cur.sends = cur.sends.then(async () => {
      if (!cur.id || cur.abort.signal.aborted) return;
      for (let attempt = 0; attempt < SEND_TRIES; attempt += 1) {
        try {
          await api.sendBatch(cur.id, seq, records, cur.abort.signal);
          return;
        } catch (caught) {
          if (cur.abort.signal.aborted) return;
          if ((caught as { retryable?: boolean }).retryable === false) break;
        }
      }
      setState((s) => ({ ...s, sendFailures: s.sendFailures + 1 }));
    });
  }, [api]);

  const pollView = useCallback(async () => {
    const cur = live.current;
    if (cur.closed || !cur.id) return;
    try {
      const view = await api.view(cur.id, cur.abort.signal);
      if (cur.closed) return;
      patch({ view, rebuffers: cur.player?.rebuffers ?? 0 });
      if (view.phase === 'failed') {
        await fail(view.error?.message ?? 'الجلسة فشلت.');
        return;
      }
      if (view.phase === 'done') {
        await cur.outLoop;
        await finish(cur);
        return;
      }
    } catch (caught) {
      if (cur.closed) return;
      patch({ error: describeError(caught).title });
    }
    if (!cur.closed) cur.timer = window.setTimeout(() => void pollView(), VIEW_POLL_MS);
    // eslint-disable-next-line @typescript-eslint/no-use-before-define
  }, [api, fail, patch]);

  const finish = useCallback(async (cur: typeof live.current) => {
    let metrics: StreamMetrics | null = null;
    let reportError: string | null = null;
    try {
      if (cur.player && cur.id) await api.postPlayback(cur.id, cur.player.report());
      if (cur.id) metrics = await api.metrics(cur.id);
    } catch {
      reportError = 'تعذّر حفظ قياسات تشغيل الصوت. الجلسة انتهت لكن القياسات ناقصة.';
    }
    if (cur.closed) return;
    cur.player?.close();
    cur.closed = true;
    patch({ phase: 'done', metrics, ...(reportError ? { error: reportError } : {}) });
  }, [api, patch]);

  const runOut = useCallback(async (cur: typeof live.current) => {
    while (!cur.closed && cur.id) {
      try {
        const got = await api.out(cur.id, cur.after, cur.abort.signal);
        if (!got) continue;
        for (const part of got.parts) {
          cur.after = Math.max(cur.after, part.idx);
          cur.player?.enqueue(part);
          setState((s) => ({ ...s, partStates: { ...s.partStates, [part.state]: (s.partStates[part.state] ?? 0) + 1 } }));
        }
        if (got.phase === 'done' || got.phase === 'failed') return;
      } catch {
        if (cur.closed) return;
        await new Promise((r) => setTimeout(r, 300));
      }
    }
  }, [api]);

  const start = useCallback(async () => {
    void release(live.current);
    const cur: typeof live.current = {
      ...live.current, id: null, token: undefined, capture: null, player: null, sends: Promise.resolve(),
      seq: 0, closed: false, stopping: false, after: -1, abort: new AbortController(), timer: null, outLoop: null,
    };
    live.current = cur;
    patch({ phase: 'starting', error: null, view: null, metrics: null, rebuffers: 0, partStates: {}, sendFailures: 0 });
    try {
      const created = await api.create();
      cur.id = created.live_session_id;
      cur.token = created.session_token;
      if (created.session_token) saveSession({ token: created.session_token });
      let origin = Date.now();
      const player = new StreamPlayer(() => origin);
      cur.player = player;
      await player.unlock();
      const capture = await startStreamCapture({
        onBatch: send, onError: (m) => void fail(m), signal: cur.abort.signal,
      });
      origin = capture.wallOrigin();
      if (cur.closed) {
        await capture.stop();
        return;
      }
      cur.capture = capture;
      patch({ phase: 'recording', stream: capture.stream });
      cur.outLoop = runOut(cur);
      void pollView();
    } catch (caught) {
      await fail(caught instanceof Error && !('code' in caught) ? caught.message : describeError(caught).detail);
    }
  }, [api, fail, patch, pollView, release, runOut, send]);

  const stop = useCallback(async () => {
    const cur = live.current;
    if (!cur.id || cur.stopping) return;
    cur.stopping = true;
    patch({ phase: 'stopping' });
    await cur.capture?.stop();
    cur.capture = null;
    patch({ stream: null });
    await cur.sends;
    if (cur.closed) return;
    try {
      await api.stop(cur.id, { signal: cur.abort.signal });
      patch({ phase: 'finishing' });
    } catch (caught) {
      await fail(describeError(caught).title);
    }
  }, [api, fail, patch]);

  const selectTarget = useCallback(async (bbox: number[]) => {
    const cur = live.current;
    if (!cur.id) return;
    patch({ view: await api.setTarget(cur.id, bbox) });
  }, [api, patch]);

  useEffect(() => {
    const onHide = () => {
      const cur = live.current;
      if (cur.id && !cur.closed) void api.stop(cur.id, { sessionToken: cur.token, keepalive: true }).catch(() => undefined);
      void release(cur);
    };
    window.addEventListener('pagehide', onHide);
    return () => {
      window.removeEventListener('pagehide', onHide);
      onHide();
    };
  }, [api, release]);

  return { state, start, stop, selectTarget };
}
