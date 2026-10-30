import { describe, expect, it, vi } from 'vitest';

import { createHttpApi, joinUrl, normalizeBBox } from '../client';
import { ApiError, apiErrorFromStatus, describeError, isApiError } from '../errors';

function fakeResponse(
  status: number,
  body?: unknown,
  overrides: { blob?: Blob; ok?: boolean } = {},
): Response {
  const text = body === undefined ? '' : JSON.stringify(body);
  return {
    ok: overrides.ok ?? (status >= 200 && status < 300),
    status,
    text: async () => text,
    blob: async () => overrides.blob ?? new Blob([text], { type: 'application/json' }),
  } as unknown as Response;
}

describe('joinUrl', () => {
  it('leaves the path alone when no base url is configured', () => {
    expect(joinUrl('', '/videos')).toBe('/videos');
  });

  it('does not double the slash', () => {
    expect(joinUrl('https://api.test/', '/videos')).toBe('https://api.test/videos');
    expect(joinUrl('https://api.test', 'videos')).toBe('https://api.test/videos');
  });
});

describe('normalizeBBox', () => {
  it('accepts {x,y,width,height}', () => {
    expect(normalizeBBox({ x: 1, y: 2, width: 3, height: 4 })).toEqual({
      x: 1,
      y: 2,
      width: 3,
      height: 4,
    });
  });

  it('accepts {x,y,w,h}', () => {
    expect(normalizeBBox({ x: 10, y: 20, w: 30, h: 40 })).toEqual({
      x: 10,
      y: 20,
      width: 30,
      height: 40,
    });
  });

  it('accepts corner pairs [x1,y1,x2,y2]', () => {
    expect(normalizeBBox([10, 20, 40, 60])).toEqual({ x: 10, y: 20, width: 30, height: 40 });
  });

  it('falls back to zeros for junk', () => {
    expect(normalizeBBox(null)).toEqual({ x: 0, y: 0, width: 0, height: 0 });
  });
});

describe('error mapping', () => {
  it('prefers the structured error payload', () => {
    const error = apiErrorFromStatus(503, {
      error: { code: 'GPU_BUSY', message: 'busy', retryable: true },
    });
    expect(error.code).toBe('GPU_BUSY');
    expect(error.retryable).toBe(true);
    expect(error.status).toBe(503);
  });

  it('maps 401 to a non-retryable session failure', () => {
    const error = apiErrorFromStatus(401);
    expect(error.code).toBe('UNAUTHORIZED');
    expect(error.retryable).toBe(false);
    expect(error.isAuthFailure).toBe(true);
  });

  it('maps 413 to a limit failure', () => {
    expect(apiErrorFromStatus(413).code).toBe('LIMIT_EXCEEDED');
  });

  it('maps 429 to a retryable rate limit', () => {
    const error = apiErrorFromStatus(429);
    expect(error.code).toBe('RATE_LIMITED');
    expect(error.retryable).toBe(true);
  });

  it('describes unknown throwables without leaking internals', () => {
    const described = describeError(new Error('boom'));
    expect(described.title).toBe('حدث خطأ غير متوقع.');
  });

  it('describes an ApiError with its arabic message', () => {
    const described = describeError(new ApiError({ code: 'NETWORK', message: 'x', retryable: true }));
    expect(described.title).toContain('تعذّر الوصول');
    expect(described.code).toBe('NETWORK');
  });

  it('isApiError only accepts ApiError instances', () => {
    expect(isApiError(new Error('x'))).toBe(false);
    expect(isApiError(new ApiError({ code: 'UNKNOWN', message: 'x' }))).toBe(true);
  });
});

describe('createHttpApi', () => {
  it('sends the session token in the Authorization header, never in the URL', async () => {
    const fetchImpl = vi.fn(async () => fakeResponse(200, { job_id: 'j1' }));
    const api = createHttpApi({
      baseUrl: 'https://api.test',
      getToken: () => 'secret-token',
      fetchImpl: fetchImpl as unknown as typeof fetch,
    });

    await api.getJob('j1');

    const [url, init] = fetchImpl.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe('https://api.test/jobs/j1');
    expect(url).not.toContain('secret-token');
    expect((init.headers as Record<string, string>).Authorization).toBe('Bearer secret-token');
  });

  it('omits the header when there is no token', async () => {
    const fetchImpl = vi.fn(async () => fakeResponse(200, { job_id: 'j1' }));
    const api = createHttpApi({
      baseUrl: '',
      getToken: () => null,
      fetchImpl: fetchImpl as unknown as typeof fetch,
    });

    await api.getJob('j1');
    const [, init] = fetchImpl.mock.calls[0] as unknown as [string, RequestInit];
    expect((init.headers as Record<string, string>).Authorization).toBeUndefined();
  });

  it('normalises face bboxes and frame sizes from the wire', async () => {
    const fetchImpl = vi.fn(async () =>
      fakeResponse(200, {
        status: 'ready',
        faces: [
          {
            face_id: 'f1',
            thumbnail_url: '/t/1.jpg',
            bbox: [10, 20, 50, 90],
            timestamp_ms: 1200,
            frame_size: { width: 1280, height: 720 },
          },
        ],
      }),
    );
    const api = createHttpApi({
      baseUrl: '',
      getToken: () => null,
      fetchImpl: fetchImpl as unknown as typeof fetch,
    });

    const faces = await api.getFaces('v1');
    expect(faces.status).toBe('ready');
    expect(faces.faces[0].bbox).toEqual({ x: 10, y: 20, width: 40, height: 70 });
    expect(faces.faces[0].frame_size.width).toBe(1280);
  });

  it('turns a transport failure into a retryable NETWORK error', async () => {
    const fetchImpl = vi.fn(async () => {
      throw new TypeError('Failed to fetch');
    });
    const api = createHttpApi({
      baseUrl: '',
      getToken: () => null,
      fetchImpl: fetchImpl as unknown as typeof fetch,
    });

    await expect(api.getJob('j1')).rejects.toMatchObject({
      code: 'NETWORK',
      retryable: true,
      status: 0,
    });
  });

  it('propagates the server error code and retryability', async () => {
    const fetchImpl = vi.fn(async () =>
      fakeResponse(409, { error: { code: 'GPU_BUSY', message: 'busy', retryable: true } }),
    );
    const api = createHttpApi({
      baseUrl: '',
      getToken: () => null,
      fetchImpl: fetchImpl as unknown as typeof fetch,
    });

    await expect(api.createJob({ video_id: 'v', face_id: 'f', client_request_id: 'r' })).rejects.toMatchObject(
      { code: 'GPU_BUSY', retryable: true },
    );
  });

  it('treats 204 as an empty success', async () => {
    const fetchImpl = vi.fn(async () => fakeResponse(204));
    const api = createHttpApi({
      baseUrl: '',
      getToken: () => null,
      fetchImpl: fetchImpl as unknown as typeof fetch,
    });

    await expect(api.deleteVideo('v1')).resolves.toBeUndefined();
  });

  it('returns the audio blob for a ready job', async () => {
    const blob = new Blob([new Uint8Array([82, 73, 70, 70])], { type: 'audio/wav' });
    const fetchImpl = vi.fn(async () => fakeResponse(200, undefined, { blob }));
    const api = createHttpApi({
      baseUrl: '',
      getToken: () => null,
      fetchImpl: fetchImpl as unknown as typeof fetch,
    });

    await expect(api.fetchAudio('j1')).resolves.toBe(blob);
  });

  it('attaches the token to same-origin protected media', async () => {
    const blob = new Blob(['x'], { type: 'image/svg+xml' });
    const fetchImpl = vi.fn(async () => fakeResponse(200, undefined, { blob }));
    const api = createHttpApi({
      baseUrl: 'https://api.test',
      getToken: () => 'secret-token',
      fetchImpl: fetchImpl as unknown as typeof fetch,
    });

    await api.fetchMedia('/videos/v1/faces/f1/thumbnail');
    const [url, init] = fetchImpl.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe('https://api.test/videos/v1/faces/f1/thumbnail');
    expect((init.headers as Record<string, string>).Authorization).toBe('Bearer secret-token');
  });

  it('loads protected thumbnails through a relative API proxy', async () => {
    const blob = new Blob(['jpeg'], { type: 'image/jpeg' });
    const fetchImpl = vi.fn(async () => fakeResponse(200, undefined, { blob }));
    const api = createHttpApi({ baseUrl: '/api', getToken: () => 'session', fetchImpl: fetchImpl as unknown as typeof fetch });
    await expect(api.fetchMedia('/videos/v1/faces/f1/thumbnail')).resolves.toBe(blob);
    const [url, init] = fetchImpl.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe('/api/videos/v1/faces/f1/thumbnail');
    expect((init.headers as Record<string, string>).Authorization).toBe('Bearer session');
  });

  it('never leaks the token to a foreign-origin media URL', async () => {
    const blob = new Blob(['x'], { type: 'image/svg+xml' });
    const fetchImpl = vi.fn(async () => fakeResponse(200, undefined, { blob }));
    const api = createHttpApi({
      baseUrl: 'https://api.test',
      getToken: () => 'secret-token',
      fetchImpl: fetchImpl as unknown as typeof fetch,
    });

    await api.fetchMedia('https://cdn.evil.test/thumb.jpg');
    const [url, init] = fetchImpl.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe('https://cdn.evil.test/thumb.jpg');
    expect((init.headers as Record<string, string> | undefined)?.Authorization).toBeUndefined();
  });

  it.each(['/api', ''])('fetches protected thumbnails through a relative API base %s', async (baseUrl) => {
    const blob = new Blob(['jpeg'], { type: 'image/jpeg' });
    const fetchImpl = vi.fn(async () => fakeResponse(200, undefined, { blob }));
    const api = createHttpApi({ baseUrl, getToken: () => 'secret-token', fetchImpl: fetchImpl as unknown as typeof fetch });
    await expect(api.fetchMedia('/videos/v1/faces/f1/thumbnail')).resolves.toBe(blob);
    const [url, init] = fetchImpl.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe(`${baseUrl}/videos/v1/faces/f1/thumbnail`);
    expect((init.headers as Record<string, string>).Authorization).toBe('Bearer secret-token');
  });

  it.each(['//cdn.evil.test/thumb.jpg', '/\\cdn.evil.test/thumb.jpg'])('never tokens a foreign network-path URL %s', async (url) => {
    const fetchImpl = vi.fn(async () => fakeResponse(200));
    const api = createHttpApi({ baseUrl: '/api', getToken: () => 'secret-token', fetchImpl: fetchImpl as unknown as typeof fetch });
    await api.fetchMedia(url);
    const [, init] = fetchImpl.mock.calls[0] as unknown as [string, RequestInit];
    expect((init.headers as Record<string, string> | undefined)?.Authorization).toBeUndefined();
  });

  it('fetches data: media without a token', async () => {
    const blob = new Blob(['x'], { type: 'image/svg+xml' });
    const fetchImpl = vi.fn(async () => fakeResponse(200, undefined, { blob }));
    const api = createHttpApi({
      baseUrl: 'https://api.test',
      getToken: () => 'secret-token',
      fetchImpl: fetchImpl as unknown as typeof fetch,
    });

    await api.fetchMedia('data:image/svg+xml;base64,AAA');
    const [, init] = fetchImpl.mock.calls[0] as unknown as [string, RequestInit];
    expect((init.headers as Record<string, string> | undefined)?.Authorization).toBeUndefined();
  });
});

describe('audio-only endpoints', () => {
  function api(fetchImpl: ReturnType<typeof vi.fn>) {
    return createHttpApi({
      baseUrl: 'https://api.test',
      getToken: () => 'tok',
      fetchImpl: fetchImpl as unknown as typeof fetch,
    });
  }

  it('posts an enrollment as JSON with the token in the header only', async () => {
    const fetchImpl = vi.fn(async () => fakeResponse(202, { enrollment_id: 'e1', status: 'pending' }));
    await api(fetchImpl).createEnrollment('v1', { face_id: 'f1', source: 'range', start_ms: 0, end_ms: 6000 });
    const [url, init] = fetchImpl.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe('https://api.test/videos/v1/enrollments');
    expect(JSON.parse(init.body as string)).toEqual({ face_id: 'f1', source: 'range', start_ms: 0, end_ms: 6000 });
    expect(url).not.toContain('tok');
  });

  it('uploads a voice file as multipart form data', async () => {
    const fetchImpl = vi.fn(async () => fakeResponse(202, { enrollment_id: 'e1', status: 'pending' }));
    const file = new File(['abc'], 'me.wav', { type: 'audio/wav' });
    await api(fetchImpl).createVoiceFileEnrollment('v1', 'f1', file);
    const [url, init] = fetchImpl.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe('https://api.test/videos/v1/enrollments/upload');
    const form = init.body as FormData;
    expect(form.get('face_id')).toBe('f1');
    expect((form.get('file') as File).name).toBe('me.wav');
    expect((init.headers as Record<string, string>)['Content-Type']).toBeUndefined();
  });

  it('reads config, analysis and suggestions from their routes', async () => {
    const fetchImpl = vi.fn(async () => fakeResponse(200, {}));
    const a = api(fetchImpl);
    await a.getConfig();
    await a.getAnalysis('v1');
    await a.requestSuggestion('v1', 'f1');
    await a.getSuggestion('v1', 'f1');
    expect(fetchImpl.mock.calls.map((c) => (c as unknown as [string])[0])).toEqual([
      'https://api.test/config',
      'https://api.test/videos/v1/analysis',
      'https://api.test/videos/v1/voice-suggestions',
      'https://api.test/videos/v1/voice-suggestions/f1',
    ]);
  });
});
