import { ApiError, apiErrorFromStatus } from '../api/errors';
import { joinUrl } from '../api/client';
import {
  K_JSON, K_OUT_AUDIO, packBatch, unpackBatch, type StreamRecord,
} from './streamProto';
import type {
  PartState, PlaybackReport, StreamConfig, StreamMetrics, StreamPart, StreamPhase, StreamView,
} from './streamTypes';

export interface StreamCreated {
  live_session_id: string;
  session_token?: string;
  config: StreamConfig;
}

export interface StreamApi {
  create(): Promise<StreamCreated>;
  sendBatch(id: string, seq: number, records: StreamRecord[], signal?: AbortSignal): Promise<void>;
  out(id: string, after: number, signal?: AbortSignal): Promise<{ parts: StreamPart[]; phase: StreamPhase | null } | null>;
  view(id: string, signal?: AbortSignal): Promise<StreamView>;
  setTarget(id: string, bbox: number[]): Promise<StreamView>;
  stop(id: string, options?: { signal?: AbortSignal; sessionToken?: string; keepalive?: boolean }): Promise<StreamView>;
  postPlayback(id: string, report: PlaybackReport, signal?: AbortSignal): Promise<void>;
  metrics(id: string): Promise<StreamMetrics>;
}

export function createStreamApi(options: {
  baseUrl: string;
  getToken: () => string | null;
  fetchImpl?: typeof fetch;
}): StreamApi {
  const doFetch: typeof fetch = options.fetchImpl ?? ((...args) => fetch(...args));
  const id = encodeURIComponent;

  async function call(path: string, init: RequestInit = {}, token = options.getToken()): Promise<Response> {
    const headers: Record<string, string> = { ...(init.headers as Record<string, string> | undefined) };
    if (token && !headers.Authorization) headers.Authorization = `Bearer ${token}`;
    let response: Response;
    try {
      response = await doFetch(joinUrl(options.baseUrl, path), { ...init, headers });
    } catch (error) {
      if (init.signal?.aborted) throw new ApiError({ code: 'ABORTED', message: 'تم إلغاء الطلب.', status: 0 });
      throw new ApiError({ code: 'NETWORK', message: 'تعذّر الوصول للخادم.', status: 0, retryable: true, cause: error });
    }
    if (!response.ok) throw apiErrorFromStatus(response.status, await response.json().catch(() => undefined));
    return response;
  }
  const json = async <T>(path: string, init?: RequestInit, token?: string | null) =>
    (await call(path, init, token)).json() as Promise<T>;
  const post = (body?: unknown): RequestInit => ({
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const base = (live: string) => `/live/stream/sessions/${id(live)}`;

  return {
    create: async () => {
      const token = options.getToken();
      const created = await json<StreamCreated>('/live/stream/sessions', { method: 'POST' });
      return { ...created, session_token: created.session_token ?? token ?? undefined };
    },
    sendBatch: async (live, seq, records, signal) => {
      await call(`${base(live)}/in`, {
        method: 'POST', body: packBatch(seq, records), signal,
        headers: { 'Content-Type': 'application/octet-stream' },
      });
    },
    out: async (live, after, signal) => {
      const response = await call(`${base(live)}/out?after=${after}&wait_ms=800`, { signal });
      if (response.status === 204) return null;
      const { records } = unpackBatch(await response.arrayBuffer());
      const parts: StreamPart[] = [];
      let phase: StreamPhase | null = null;
      for (const r of records) {
        if (r.kind === K_JSON) {
          const m = JSON.parse(new TextDecoder().decode(r.data));
          if ('idx' in m) parts.push({ idx: m.idx, start: m.start, samples: m.samples, state: m.state as PartState, pcm: null });
          else if (m.phase) phase = m.phase;
        } else if (r.kind === K_OUT_AUDIO && parts.length) {
          const last = parts[parts.length - 1];
          const copy = r.data.slice();
          last.pcm = new Int16Array(copy.buffer, 0, copy.length >> 1);
        }
      }
      return { parts, phase };
    },
    view: (live, signal) => json<StreamView>(base(live), { signal }),
    setTarget: (live, bbox) => json<StreamView>(`${base(live)}/target`, post({ bbox })),
    stop: (live, o) =>
      json<StreamView>(`${base(live)}/stop`, {
        method: 'POST', signal: o?.signal, keepalive: o?.keepalive,
        headers: { Accept: 'application/json', ...(o?.sessionToken ? { Authorization: `Bearer ${o.sessionToken}` } : {}) },
      }),
    postPlayback: async (live, report, signal) => {
      await call(`${base(live)}/playback`, { ...post(report), signal });
    },
    metrics: (live) => json<StreamMetrics>(`${base(live)}/metrics`),
  };
}
