import { act, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { ApiProvider } from '../lib/api/ApiContext';
import { createMockApi } from '../lib/api/mock';
import { LiveFlow } from '../features/live/LiveFlow';
import type { LiveApi } from '../lib/live/liveApi';
import { newPlan, planSlot } from '../lib/live/playbackPlan';
import type { LiveSessionView } from '../lib/live/types';

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
  let onChunk: ((e: { data: Blob }) => void) | null = null;

  beforeEach(() => {
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
      state = 'running';
      currentTime = 0;
      resume = async () => undefined;
      close = async () => undefined;
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
