/**
 * Typed FOCUS API client.
 *
 * Only the endpoints in docs/02_CONTRACTS.md are used:
 *   POST   /videos
 *   GET    /videos/{id}/faces
 *   POST   /jobs
 *   GET    /jobs/{id}
 *   GET    /jobs/{id}/audio
 *   GET    /jobs/{id}/transcript
 *   DELETE /videos/{id}
 *
 * The session token travels in `Authorization: Bearer ...` and never in a URL.
 */

import { ApiError, apiErrorFromStatus, isApiError } from './errors';
import type {
  BBox,
  CreateJobRequest,
  CreateJobResponse,
  DeleteVideoResponse,
  FaceCandidate,
  FacesResponse,
  JobState,
  TranscriptResponse,
  UploadVideoResponse,
  VideoId,
} from './types';

export interface UploadOptions {
  onProgress?: (fraction: number) => void;
  signal?: AbortSignal;
}

export interface FocusApi {
  readonly baseUrl: string;
  uploadVideo(file: File, options?: UploadOptions): Promise<UploadVideoResponse>;
  getFaces(videoId: VideoId, signal?: AbortSignal): Promise<FacesResponse>;
  createJob(input: CreateJobRequest): Promise<CreateJobResponse>;
  getJob(jobId: string, signal?: AbortSignal): Promise<JobState>;
  fetchAudio(jobId: string, signal?: AbortSignal): Promise<Blob>;
  getTranscript(jobId: string, signal?: AbortSignal): Promise<TranscriptResponse>;
  /** Fetches a protected media URL (e.g. a face thumbnail) with the session token. */
  fetchMedia(url: string, signal?: AbortSignal): Promise<Blob>;
  /**
   * Fetches the original (canonical, timeline-equivalent) video for an honest A/B compare
   * after a refresh, when the in-memory upload is gone. Approved endpoint:
   * GET /videos/{id}/original — owner session Bearer token required.
   */
  fetchOriginal(videoId: VideoId, signal?: AbortSignal): Promise<Blob>;
  deleteVideo(videoId: VideoId): Promise<DeleteVideoResponse>;
}

export interface HttpApiOptions {
  baseUrl: string;
  getToken: () => string | null;
  fetchImpl?: typeof fetch;
  timeoutMs?: number;
}

export function joinUrl(baseUrl: string, path: string): string {
  if (!baseUrl) return path;
  return `${baseUrl.replace(/\/+$/, '')}${path.startsWith('/') ? path : `/${path}`}`;
}

export function createHttpApi(options: HttpApiOptions): FocusApi {
  const { baseUrl, getToken } = options;
  const doFetch: typeof fetch = options.fetchImpl ?? ((...args) => fetch(...args));
  const timeoutMs = options.timeoutMs ?? 20_000;

  function authHeaders(extra?: Record<string, string>): Record<string, string> {
    const token = getToken();
    return token ? { ...extra, Authorization: `Bearer ${token}` } : { ...extra };
  }

  async function request<T>(path: string, init: RequestInit = {}, signal?: AbortSignal): Promise<T> {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), timeoutMs);
    const linked = linkSignals(signal, controller.signal);

    let response: Response;
    try {
      response = await doFetch(joinUrl(baseUrl, path), {
        ...init,
        headers: authHeaders({
          Accept: 'application/json',
          ...((init.headers as Record<string, string> | undefined) ?? {}),
        }),
        signal: linked.signal,
      });
    } catch (error) {
      if (isAbortError(error) && signal?.aborted) {
        throw new ApiError({ code: 'ABORTED', message: 'تم إلغاء الطلب.', status: 0 });
      }
      if (isAbortError(error)) {
        throw new ApiError({ code: 'TIMEOUT', message: 'انتهت مهلة الطلب.', status: 0, retryable: true });
      }
      throw new ApiError({
        code: 'NETWORK',
        message: 'تعذّر الوصول للخادم.',
        status: 0,
        retryable: true,
        cause: error,
      });
    } finally {
      clearTimeout(timer);
      linked.cleanup();
    }

    if (response.status === 204) return undefined as T;

    const body = await readJson(response);

    if (!response.ok) {
      throw apiErrorFromStatus(response.status, body);
    }

    if (body === undefined) {
      throw new ApiError({
        code: 'BAD_RESPONSE',
        message: 'رد الخادم غير قابل للقراءة.',
        status: response.status,
        retryable: true,
      });
    }

    return body as T;
  }

  async function requestBlob(path: string, signal?: AbortSignal): Promise<Blob> {
    // An absolute URL is used as-is (same-origin media the API may return as a full link);
    // a relative path is joined onto the API base. Either way the session token is attached.
    const finalUrl = /^https?:/i.test(path) ? path : joinUrl(baseUrl, path);
    let response: Response;
    try {
      response = await doFetch(finalUrl, {
        method: 'GET',
        headers: authHeaders(),
        signal,
      });
    } catch (error) {
      if (isAbortError(error)) {
        throw new ApiError({ code: 'ABORTED', message: 'تم إلغاء الطلب.', status: 0 });
      }
      throw new ApiError({
        code: 'NETWORK',
        message: 'تعذّر الوصول للخادم.',
        status: 0,
        retryable: true,
        cause: error,
      });
    }

    if (!response.ok) {
      const body = await readJson(response).catch(() => undefined);
      throw apiErrorFromStatus(response.status, body);
    }

    return response.blob();
  }

  return {
    baseUrl,

    uploadVideo(file, uploadOptions = {}) {
      const url = joinUrl(baseUrl, '/videos');
      return new Promise<UploadVideoResponse>((resolve, reject) => {
        const xhr = new XMLHttpRequest();
        xhr.open('POST', url, true);
        xhr.responseType = 'text';
        const token = getToken();
        if (token) xhr.setRequestHeader('Authorization', `Bearer ${token}`);
        xhr.setRequestHeader('Accept', 'application/json');

        const onAbort = () => xhr.abort();
        uploadOptions.signal?.addEventListener('abort', onAbort);

        const cleanup = () => {
          uploadOptions.signal?.removeEventListener('abort', onAbort);
        };

        xhr.upload.onprogress = (event) => {
          if (!event.lengthComputable) return;
          uploadOptions.onProgress?.(event.loaded / event.total);
        };

        xhr.onerror = () => {
          cleanup();
          reject(new ApiError({ code: 'NETWORK', message: 'فشل الرفع.', status: 0, retryable: true }));
        };

        xhr.onabort = () => {
          cleanup();
          reject(new ApiError({ code: 'ABORTED', message: 'تم إلغاء الرفع.', status: 0 }));
        };

        xhr.onload = () => {
          cleanup();
          const parsed = safeParse(xhr.responseText);
          if (xhr.status >= 200 && xhr.status < 300) {
            resolve(parsed as UploadVideoResponse);
            return;
          }
          reject(apiErrorFromStatus(xhr.status, parsed));
        };

        const form = new FormData();
        form.append('file', file, file.name);
        xhr.send(form);
      });
    },

    getFaces(videoId, signal) {
      return request<FacesResponse>(`/videos/${encodeURIComponent(videoId)}/faces`, {}, signal).then(
        (body) => ({
          ...body,
          faces: (body.faces ?? []).map(normalizeFace),
        }),
      );
    },

    createJob(input) {
      return request<CreateJobResponse>('/jobs', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(input),
      });
    },

    getJob(jobId, signal) {
      return request<JobState>(`/jobs/${encodeURIComponent(jobId)}`, {}, signal);
    },

    fetchAudio(jobId, signal) {
      return requestBlob(`/jobs/${encodeURIComponent(jobId)}/audio`, signal);
    },

    getTranscript(jobId, signal) {
      return request<TranscriptResponse>(`/jobs/${encodeURIComponent(jobId)}/transcript`, {}, signal);
    },

    fetchMedia(url, signal) {
      // data:/blob: are local/opaque; never carry credentials.
      if (/^(data:|blob:)/i.test(url)) {
        return fetchBlobAbsolute(doFetch, url, () => null, signal);
      }

      // Only attach the session token to media that belongs to the trusted API origin.
      // A foreign-origin URL is fetched anonymously so we never leak the token to a
      // third party. A relative path resolves against the API base (trusted) and is tokened.
      // Resolve a proxy base such as /api (or an empty same-origin base) against
      // the page before deciding whether the media may carry credentials.
      const apiBase = safeUrl(baseUrl || '/', globalThis.location?.href);
      const target = safeUrl(url, apiBase?.href);
      const sameOrigin = Boolean(target && apiBase && target.origin === apiBase.origin);
      if (sameOrigin) {
        // Network-path references need their resolved origin; ordinary API paths
        // still go through requestBlob so the /api proxy prefix is preserved.
        return requestBlob(/^[\/\\]{2}/.test(url.trim()) ? target!.href : url, signal);
      }
      return fetchBlobAbsolute(doFetch, url, () => null, signal);
    },

    fetchOriginal(videoId, signal) {
      return requestBlob(`/videos/${encodeURIComponent(videoId)}/original`, signal);
    },

    deleteVideo(videoId) {
      return request<DeleteVideoResponse>(`/videos/${encodeURIComponent(videoId)}`, {
        method: 'DELETE',
      });
    },
  };
}

function safeUrl(value: string, base?: string): URL | null {
  try {
    return new URL(value, base && /^https?:/i.test(base) ? base : undefined);
  } catch {
    return null;
  }
}

async function fetchBlobAbsolute(
  doFetch: typeof fetch,
  url: string,
  getToken: () => string | null,
  signal?: AbortSignal,
): Promise<Blob> {
  const token = getToken();
  let response: Response;
  try {
    response = await doFetch(url, {
      headers: token ? { Authorization: `Bearer ${token}` } : undefined,
      signal,
    });
  } catch (error) {
    throw new ApiError({
      code: 'NETWORK',
      message: 'تعذّر تحميل الوسائط.',
      status: 0,
      retryable: true,
      cause: error,
    });
  }
  if (!response.ok) throw apiErrorFromStatus(response.status);
  return response.blob();
}

async function readJson(response: Response): Promise<unknown> {
  const text = await response.text().catch(() => '');
  if (!text) return undefined;
  return safeParse(text);
}

function safeParse(text: string): unknown {
  if (!text) return undefined;
  try {
    return JSON.parse(text);
  } catch {
    return undefined;
  }
}

function isAbortError(error: unknown): boolean {
  return (
    (error instanceof DOMException && error.name === 'AbortError') ||
    (typeof error === 'object' && error !== null && (error as { name?: string }).name === 'AbortError')
  );
}

function linkSignals(external: AbortSignal | undefined, internal: AbortSignal) {
  if (!external) return { signal: internal, cleanup: () => undefined };
  if (external.aborted) {
    // The caller already gave up before we started.
    const controller = new AbortController();
    controller.abort();
    return { signal: controller.signal, cleanup: () => undefined };
  }
  const controller = new AbortController();
  const onAbort = () => controller.abort();
  external.addEventListener('abort', onAbort);
  internal.addEventListener('abort', onAbort);
  return {
    signal: controller.signal,
    cleanup: () => {
      external.removeEventListener('abort', onAbort);
      internal.removeEventListener('abort', onAbort);
    },
  };
}

/**
 * The API returns bboxes in original-frame pixels. Shape is normalised here so the UI
 * never has to guess between `{x,y,w,h}`, `{x,y,width,height}` and `[x1,y1,x2,y2]`.
 */
export function normalizeBBox(raw: unknown): BBox {
  if (Array.isArray(raw) && raw.length >= 4) {
    const [x1, y1, x2, y2] = raw.map((value) => Number(value));
    return { x: x1, y: y1, width: Math.max(0, x2 - x1), height: Math.max(0, y2 - y1) };
  }
  if (raw && typeof raw === 'object') {
    const box = raw as Record<string, number>;
    const x = Number(box.x ?? box.x1 ?? 0);
    const y = Number(box.y ?? box.y1 ?? 0);
    if (box.width !== undefined || box.height !== undefined) {
      return { x, y, width: Number(box.width ?? 0), height: Number(box.height ?? 0) };
    }
    if (box.w !== undefined || box.h !== undefined) {
      return { x, y, width: Number(box.w ?? 0), height: Number(box.h ?? 0) };
    }
    if (box.x2 !== undefined || box.y2 !== undefined) {
      return {
        x,
        y,
        width: Math.max(0, Number(box.x2 ?? 0) - x),
        height: Math.max(0, Number(box.y2 ?? 0) - y),
      };
    }
  }
  return { x: 0, y: 0, width: 0, height: 0 };
}

function normalizeFace(face: FaceCandidate): FaceCandidate {
  return {
    ...face,
    bbox: normalizeBBox(face.bbox),
    frame_size: {
      width: Number(face.frame_size?.width ?? 0),
      height: Number(face.frame_size?.height ?? 0),
    },
    timestamp_ms: Number(face.timestamp_ms ?? 0),
  };
}

/** Small helper for callers that want a typed guard without importing errors.ts. */
export { isApiError };
