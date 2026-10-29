import { act, render, renderHook, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { ApiProvider } from '../lib/api/ApiContext';
import { createMockApi } from '../lib/api/mock';
import { LiveFlow } from '../features/live/LiveFlow';
import type { LiveApi } from '../lib/live/liveApi';
import { newPlan, planSlot } from '../lib/live/playbackPlan';
import type { LiveSessionView } from '../lib/live/types';
import { useLiveSession } from '../features/live/useLiveSession';
import { createLiveApi } from '../lib/live/liveApi';
import { clearSession, readSession } from '../lib/session';

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: Error) => void;
  const promise = new Promise<T>((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}

describe('playback plan', () => {
  it('keeps the capture timeline and never plays a chunk twice', () => {
    const plan = newPlan();
    expect(planSlot(plan, 0, 0, 10)?.startAt).toBeCloseTo(10.25);
    expect(planSlot(plan, 1, 2000, 10.5)?.startAt).toBeCloseTo(12.25);
    expect(planSlot(plan, 1, 2000, 10.6)).toBeNull();
    expect(plan.duplicates).toBe(1);
  });

  it('shifts the timeline and counts a rebuffer when a chunk is late', () => {
    const plan = newPlan();
    planSlot(plan, 0, 0, 0);
    const slot = planSlot(plan, 1, 2000, 5);
    expect(slot?.rebuffered).toBe(true);
    expect(slot!.startAt).toBeGreaterThan(5);
    expect(plan.rebuffers).toBe(1);
    // the next on-time chunk keeps the shifted timeline
    expect(planSlot(plan, 2, 4000, 5.1)?.startAt).toBeCloseTo(slot!.startAt + 2);
  });
});

function view(partial: Partial<LiveSessionView> = {}): LiveSessionView {
  return {
    live_session_id: 'L1', experimental: true, phase: 'awaiting_target', mode: 'live', chunk_ms: 2000,
    target_face_id: null, first_video_id: null, faces_status: 'pending', queue_depth: 0, expected_seq: 0,
    overload_at_seq: null, error: null, counts: { duplicates: 0, out_of_order: 0, late_rejected: 0 },
    chunks: [], final: { status: null, video_id: null, job_id: null, error: null }, ...partial,
  };
}

describe('LiveFlow camera lifecycle', () => {
  const stops: ReturnType<typeof vi.fn>[] = [];
  const recorderStart = vi.fn();
  const audioCreated = vi.fn();
  const audioClosed = vi.fn();
  let onChunk: ((e: { data: Blob }) => void) | null = null;

  beforeEach(() => {
    clearSession();
    recorderStart.mockClear();
    audioCreated.mockClear();
    audioClosed.mockClear();
    stops.length = 0;
    const track = () => {
      const stop = vi.fn();
      stops.push(stop);
      return { stop };
    };
    Object.defineProperty(navigator, 'mediaDevices', {
      configurable: true,
      value: {
        getUserMedia: vi.fn(async () => {
          const tracks = [track(), track()];
          return { getTracks: () => tracks };
        }),
      },
    });
    class FakeRecorder {
      static isTypeSupported = () => true;
      state = 'inactive';
      onstop: (() => void) | null = null;
      onerror: (() => void) | null = null;
      set ondataavailable(fn: (e: { data: Blob }) => void) {
        onChunk = fn;
      }
      start() {
        recorderStart();
        this.state = 'recording';
      }
      stop() {
        this.state = 'inactive';
        onChunk?.({ data: new Blob(['tail']) });
        this.onstop?.();
      }
    }
    (globalThis as unknown as { MediaRecorder: unknown }).MediaRecorder = FakeRecorder;
    class FakeAudioContext {
      constructor() { audioCreated(); }
      state = 'running';
      currentTime = 0;
      resume = async () => undefined;
      close = async () => { audioClosed(); };
    }
    (globalThis as unknown as { AudioContext: unknown }).AudioContext = FakeAudioContext;
  });

  function fakeApi(): LiveApi {
    return {
      create: vi.fn(async () => ({ live_session_id: 'L1', session_token: 't', chunk_ms: 2000, max_chunks: 10 })),
      putChunk: vi.fn(async () => ({ state: 'received', duplicate: false })),
      get: vi.fn(async () => view()),
      setTarget: vi.fn(async () => view()),
      chunkAudio: vi.fn(async () => new ArrayBuffer(0)),
      postPlayback: vi.fn(async () => undefined),
      stop: vi.fn(async () => view({ phase: 'finalizing', final: { status: 'pending', video_id: null, job_id: null, error: null } })),
      metrics: vi.fn(),
    } as unknown as LiveApi;
  }

  function renderFlow(liveApi: LiveApi) {
    return render(
      <ApiProvider api={createMockApi({ latencyMs: 0, facesReadyMs: 0 })} isMock>
        <MemoryRouter>
          <LiveFlow liveApi={liveApi} />
        </MemoryRouter>
      </ApiProvider>,
    );
  }

  it('stops every camera/mic track when recording is stopped and sends the final chunk first', async () => {
    const liveApi = fakeApi();
    renderFlow(liveApi);
    await userEvent.click(screen.getByRole('button', { name: 'ابدأ التسجيل' }));
    await screen.findByRole('button', { name: 'إيقاف التسجيل' });
    expect(stops.every((s) => s.mock.calls.length === 0)).toBe(true);
    await userEvent.click(screen.getByRole('button', { name: 'إيقاف التسجيل' }));
    await waitFor(() => expect(liveApi.stop).toHaveBeenCalled());
    expect(stops.length).toBe(2);
    expect(stops.every((s) => s.mock.calls.length > 0)).toBe(true);
    expect(liveApi.putChunk).toHaveBeenCalledTimes(1);
    expect(vi.mocked(liveApi.putChunk).mock.invocationCallOrder[0]).toBeLessThan(
      vi.mocked(liveApi.stop).mock.invocationCallOrder[0],
    );
  });

  it('releases the camera when the screen unmounts', async () => {
    const view_ = renderFlow(fakeApi());
    await userEvent.click(screen.getByRole('button', { name: 'ابدأ التسجيل' }));
    await screen.findByRole('button', { name: 'إيقاف التسجيل' });
    await act(async () => view_.unmount());
    expect(stops.every((s) => s.mock.calls.length > 0)).toBe(true);
  });

  it.each(['unmount', 'pagehide'])('cleans up a late create after %s without starting camera or audio', async (leave) => {
    const api = fakeApi();
    const created = deferred<Awaited<ReturnType<LiveApi['create']>>>();
    vi.mocked(api.create).mockReturnValue(created.promise);
    const hook = renderHook(() => useLiveSession(api));
    let starting!: Promise<void>;
    act(() => { starting = hook.result.current.start(); });
    act(() => {
      if (leave === 'unmount') hook.unmount();
      else window.dispatchEvent(new Event('pagehide'));
    });
    await act(async () => {
      created.resolve({ live_session_id: 'abandoned', session_token: 'old-owner', chunk_ms: 2000, max_chunks: 10 });
      await starting;
    });
    expect(api.stop).toHaveBeenCalledExactlyOnceWith('abandoned', { sessionToken: 'old-owner', keepalive: true });
    expect(navigator.mediaDevices.getUserMedia).not.toHaveBeenCalled();
    expect(audioCreated).not.toHaveBeenCalled();
    expect(api.get).not.toHaveBeenCalled();
    expect(readSession().token).toBeNull();
  });

  it('releases late permission tracks without starting a recorder or touching a replacement session', async () => {
    const api = fakeApi();
    const permission = deferred<MediaStream>();
    vi.mocked(navigator.mediaDevices.getUserMedia).mockReturnValueOnce(permission.promise);
    const old = renderHook(() => useLiveSession(api));
    let starting!: Promise<void>;
    act(() => { starting = old.result.current.start(); });
    await waitFor(() => expect(navigator.mediaDevices.getUserMedia).toHaveBeenCalledTimes(1));
    old.unmount();
    expect(api.stop).toHaveBeenCalledExactlyOnceWith('L1', { sessionToken: 't', keepalive: true });
    expect(audioClosed).toHaveBeenCalledTimes(1);

    vi.mocked(api.create).mockResolvedValue({ live_session_id: 'replacement', session_token: 'new-owner', chunk_ms: 2000, max_chunks: 10 });
    const replacement = renderHook(() => useLiveSession(api));
    await act(async () => { await replacement.result.current.start(); });
    const stopTrack = vi.fn();
    await act(async () => {
      permission.resolve({ getTracks: () => [{ stop: stopTrack }] } as unknown as MediaStream);
      await starting;
    });
    expect(stopTrack).toHaveBeenCalledTimes(1);
    expect(recorderStart).toHaveBeenCalledTimes(1); // only the replacement
    expect(api.putChunk).not.toHaveBeenCalled();
    expect(api.stop).toHaveBeenCalledTimes(1);
    expect(replacement.result.current.state.phase).toBe('recording');
    expect(readSession().token).toBe('new-owner');
    expect(stops.every((s) => s.mock.calls.length === 0)).toBe(true);
  });

  it.each(['resolve', 'reject'])('isolates a superseded create that later %ss', async (outcome) => {
    const api = fakeApi();
    const created = deferred<Awaited<ReturnType<LiveApi['create']>>>();
    vi.mocked(api.create).mockReturnValueOnce(created.promise).mockResolvedValue({
      live_session_id: 'replacement', session_token: 'new-owner', chunk_ms: 2000, max_chunks: 10,
    });
    const hook = renderHook(() => useLiveSession(api));
    let first!: Promise<void>;
    act(() => { first = hook.result.current.start(); });
    await act(async () => { await hook.result.current.start(); });
    await act(async () => {
      if (outcome === 'resolve') created.resolve({
        live_session_id: 'abandoned', session_token: 'old-owner', chunk_ms: 2000, max_chunks: 10,
      });
      else created.reject(new Error('Old request failed'));
      await first;
    });
    expect(hook.result.current.state.phase).toBe('recording');
    expect(hook.result.current.liveId).toBe('replacement');
    expect(readSession().token).toBe('new-owner');
    expect(recorderStart).toHaveBeenCalledTimes(1);
    expect(audioCreated).toHaveBeenCalledTimes(1);
    expect(audioClosed).not.toHaveBeenCalled();
    if (outcome === 'resolve') {
      expect(api.stop).toHaveBeenCalledExactlyOnceWith('abandoned', { sessionToken: 'old-owner', keepalive: true });
    } else expect(api.stop).not.toHaveBeenCalled();
  });

  it('stops the server session when permission is denied', async () => {
    const api = fakeApi();
    vi.mocked(navigator.mediaDevices.getUserMedia).mockRejectedValueOnce(new Error('Permission denied'));
    const hook = renderHook(() => useLiveSession(api));
    await act(async () => { await hook.result.current.start(); });
    expect(api.stop).toHaveBeenCalledTimes(1);
    expect(hook.result.current.state.phase).toBe('error');
    expect(audioClosed).toHaveBeenCalledTimes(1);
    expect(recorderStart).not.toHaveBeenCalled();
  });

  it('shows overload and missing chunks as explicit states', async () => {
    const liveApi = fakeApi();
    vi.mocked(liveApi.get).mockResolvedValue(
      view({
        phase: 'live', mode: 'record_then_process', target_face_id: 'f', overload_at_seq: 3,
        chunks: [{ seq: 1, state: 'missing', capture_start_ms: 0, duration_ms: 0, error: null, warnings: [] }],
      }),
    );
    renderFlow(liveApi);
    await userEvent.click(screen.getByRole('button', { name: 'ابدأ التسجيل' }));
    expect(await screen.findByText(/سجّل وبعدين عالج/)).toBeInTheDocument();
    expect(await screen.findByText(/#1: ناقص/)).toBeInTheDocument();
  });
});

describe('live startup cleanup transport', () => {
  it('preserves finalization cancellation alongside cleanup options', async () => {
    const fetchImpl = vi.fn<typeof fetch>().mockResolvedValue(new Response(JSON.stringify(view())));
    const api = createLiveApi({ baseUrl: '/api', getToken: () => 'current-owner', fetchImpl });
    const request = new AbortController();
    await api.stop('L1', { signal: request.signal });
    expect(fetchImpl).toHaveBeenCalledExactlyOnceWith('/api/live/sessions/L1/stop', expect.objectContaining({
      method: 'POST', signal: request.signal,
      headers: expect.objectContaining({ Authorization: 'Bearer current-owner' }),
    }));
  });

  it.each([null, 'original-owner'])('keeps the create owner for cleanup when stored credentials change (%s)', async (initialToken) => {
    let token: string | null = initialToken;
    const response = deferred<Response>();
    const fetchImpl = vi.fn<typeof fetch>()
      .mockReturnValueOnce(response.promise)
      .mockResolvedValue(new Response(JSON.stringify(view())));
    const api = createLiveApi({ baseUrl: '/api', getToken: () => token, fetchImpl });
    const pending = api.create();
    token = 'replacement-owner';
    response.resolve(new Response(JSON.stringify({
      live_session_id: 'old/id', chunk_ms: 2000, max_chunks: 10,
      ...(initialToken ? {} : { session_token: 'new-anonymous-owner' }),
    })));
    const created = await pending;
    await api.stop(created.live_session_id, { sessionToken: created.session_token, keepalive: true });
    expect(fetchImpl).toHaveBeenLastCalledWith('/api/live/sessions/old%2Fid/stop', expect.objectContaining({
      method: 'POST', keepalive: true,
      headers: expect.objectContaining({ Authorization: `Bearer ${initialToken ?? 'new-anonymous-owner'}` }),
    }));
  });
});
