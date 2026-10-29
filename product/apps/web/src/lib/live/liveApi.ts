import { ApiError, apiErrorFromStatus } from '../api/errors';
import { joinUrl } from '../api/client';
import type { LiveCreateResponse, LiveMetrics, LiveSessionView, PlaybackReport } from './types';

export interface ChunkUpload {
  seq: number;
  captureStartMs: number;
  durationMs: number;
  blob: Blob;
}

export interface LiveApi {
  create(): Promise<LiveCreateResponse>;
  putChunk(liveId: string, chunk: ChunkUpload, signal?: AbortSignal): Promise<{ state: string; duplicate: boolean }>;
  get(liveId: string, signal?: AbortSignal): Promise<LiveSessionView>;
  setTarget(liveId: string, faceId: string): Promise<LiveSessionView>;
  chunkAudio(liveId: string, seq: number, signal?: AbortSignal): Promise<ArrayBuffer>;
  postPlayback(liveId: string, report: PlaybackReport): Promise<void>;
  stop(liveId: string): Promise<LiveSessionView>;
  metrics(liveId: string): Promise<LiveMetrics>;
}

export function createLiveApi(options: {
  baseUrl: string;
  getToken: () => string | null;
  fetchImpl?: typeof fetch;
}): LiveApi {
  const doFetch: typeof fetch = options.fetchImpl ?? ((...args) => fetch(...args));

  async function call(path: string, init: RequestInit = {}): Promise<Response> {
    const token = options.getToken();
    const headers: Record<string, string> = { ...(init.headers as Record<string, string> | undefined) };
    if (token) headers.Authorization = `Bearer ${token}`;
    let response: Response;
    try {
      response = await doFetch(joinUrl(options.baseUrl, path), { ...init, headers });
    } catch (error) {
      if (init.signal?.aborted) throw new ApiError({ code: 'ABORTED', message: 'تم إلغاء الطلب.', status: 0 });
      throw new ApiError({
        code: 'NETWORK', message: 'تعذّر الوصول للخادم.', status: 0, retryable: true, cause: error,
      });
    }
    if (!response.ok) {
      const body = await response.json().catch(() => undefined);
      throw apiErrorFromStatus(response.status, body);
    }
    return response;
  }

  const json = async <T>(path: string, init?: RequestInit) => (await call(path, init)).json() as Promise<T>;
  const post = (_path: string, body?: unknown) =>
    ({
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
      body: body === undefined ? undefined : JSON.stringify(body),
    }) as RequestInit;
  const id = encodeURIComponent;

  return {
    create: () => json<LiveCreateResponse>('/live/sessions', { method: 'POST', headers: { Accept: 'application/json' } }),
    putChunk: (liveId, chunk, signal) =>
      json(
        `/live/sessions/${id(liveId)}/chunks/${chunk.seq}?capture_start_ms=${Math.round(
          chunk.captureStartMs,
        )}&duration_ms=${Math.round(chunk.durationMs)}`,
        { method: 'PUT', body: chunk.blob, headers: { 'Content-Type': 'application/octet-stream' }, signal },
      ),
    get: (liveId, signal) => json<LiveSessionView>(`/live/sessions/${id(liveId)}`, { signal }),
    setTarget: (liveId, faceId) =>
      json<LiveSessionView>(`/live/sessions/${id(liveId)}/target`, post('', { face_id: faceId })),
    chunkAudio: async (liveId, seq, signal) =>
      (await call(`/live/sessions/${id(liveId)}/chunks/${seq}/audio`, { signal })).arrayBuffer(),
    postPlayback: async (liveId, report) => {
      await call(`/live/sessions/${id(liveId)}/playback`, post('', report));
    },
    stop: (liveId) => json<LiveSessionView>(`/live/sessions/${id(liveId)}/stop`, post('')),
    metrics: (liveId) => json<LiveMetrics>(`/live/sessions/${id(liveId)}/metrics`),
  };
}
