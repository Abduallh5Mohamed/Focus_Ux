import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { ApiProvider } from '../lib/api/ApiContext';
import type { FocusApi } from '../lib/api/client';
import { createMockApi } from '../lib/api/mock';
import type { MixInfo } from '../lib/api/types';
import { VoiceMixPanel } from '../features/results/VoiceMixPanel';

const gainTargets: number[] = [];
const sourcesStarted = vi.fn();

function fakeParam(record?: number[]) {
  return {
    value: 0,
    setTargetAtTime: vi.fn((v: number) => {
      record?.push(v);
    }),
  };
}

class FakeAudioContext {
  currentTime = 0;
  sampleRate = 48_000;
  destination = {};
  createGain() {
    const gain = fakeParam(gainTargets);
    return { gain, connect: vi.fn() };
  }
  createBiquadFilter() {
    return { type: '', Q: { value: 0 }, frequency: fakeParam(), connect: vi.fn() };
  }
  createDynamicsCompressor() {
    return {
      threshold: { value: 0 }, knee: { value: 0 }, ratio: { value: 0 },
      attack: { value: 0 }, release: { value: 0 }, connect: vi.fn(),
    };
  }
  createBufferSource() {
    return {
      buffer: null, playbackRate: { value: 1 }, connect: vi.fn(), disconnect: vi.fn(),
      start: sourcesStarted, stop: vi.fn(),
    };
  }
  decodeAudioData() {
    return Promise.resolve({ duration: 9 } as AudioBuffer);
  }
  resume = vi.fn(() => Promise.resolve());
  close = vi.fn(() => Promise.resolve());
}

const INFO: MixInfo = {
  sample_rate: 48_000, others_available: true, others_unavailable_reason: null,
  alignment_ms: 0, level_gain: 1, correlation: 0.9, noise_filters: {},
};

beforeEach(() => {
  // jsdom's Blob has no arrayBuffer().
  if (!Blob.prototype.arrayBuffer) {
    Blob.prototype.arrayBuffer = function () {
      return Promise.resolve(new ArrayBuffer(8));
    };
  }
  gainTargets.length = 0;
  sourcesStarted.mockClear();
  (window as unknown as { AudioContext: unknown }).AudioContext = FakeAudioContext;
  window.HTMLMediaElement.prototype.load = vi.fn();
  window.HTMLMediaElement.prototype.play = vi.fn(() => Promise.resolve());
  window.HTMLMediaElement.prototype.pause = vi.fn();
  URL.createObjectURL = vi.fn(() => 'blob:export');
  URL.revokeObjectURL = vi.fn();
});

function renderPanel(overrides: Partial<FocusApi> = {}) {
  const api = { ...createMockApi({ latencyMs: 0 }), getMixInfo: async () => INFO, ...overrides } as FocusApi;
  render(
    <ApiProvider api={api} isMock>
      <VoiceMixPanel jobId="job_test" videoUrl="blob:video" audioReady />
    </ApiProvider>,
  );
  return api;
}

describe('VoiceMixPanel', () => {
  it('shows the three controls, labelling noise reduction as a plain filter', async () => {
    renderPanel();
    expect(await screen.findByLabelText('مستوى صوت الشخص المختار')).toBeInTheDocument();
    expect(screen.getByLabelText('مستوى الأصوات التانية')).toBeInTheDocument();
    const group = screen.getByRole('radiogroup', { name: 'تقليل الضوضاء' });
    expect(group).toHaveTextContent('مش ذكاء اصطناعي');
    for (const label of ['بدون', 'خفيف', 'قوي']) {
      expect(screen.getByRole('radio', { name: label })).toBeInTheDocument();
    }
    await waitFor(() => expect(screen.getByLabelText('مستوى الأصوات التانية')).toBeEnabled());
  });

  it('changes gains live without restarting playback', async () => {
    renderPanel();
    const slider = await screen.findByLabelText('مستوى صوت الشخص المختار');
    await waitFor(() => expect(screen.getByLabelText('مستوى الأصوات التانية')).toBeEnabled());
    const video = screen.getByLabelText('فيديو المقارنة') as HTMLVideoElement;
    const startsBefore = sourcesStarted.mock.calls.length;
    const loadsBefore = vi.mocked(window.HTMLMediaElement.prototype.load).mock.calls.length;
    fireEvent.change(slider, { target: { value: '1.5' } });
    await waitFor(() => expect(gainTargets).toContain(1.5));
    expect(sourcesStarted.mock.calls.length).toBe(startsBefore);
    expect(vi.mocked(window.HTMLMediaElement.prototype.load).mock.calls.length).toBe(loadsBefore);
    expect(vi.mocked(window.HTMLMediaElement.prototype.pause)).not.toHaveBeenCalled();
    expect(video.paused).toBe(true);
  });

  it('switches original/mix by muting the video only, on the same element', async () => {
    renderPanel();
    await waitFor(() => expect(screen.getByRole('radio', { name: 'الميكس الحالي' })).toBeEnabled());
    const video = screen.getByLabelText('فيديو المقارنة') as HTMLVideoElement;
    expect(video.muted).toBe(true);
    await userEvent.click(screen.getByRole('radio', { name: 'الصوت الأصلي' }));
    expect(video.muted).toBe(false);
    await userEvent.click(screen.getByRole('radio', { name: 'الميكس الحالي' }));
    expect(video.muted).toBe(true);
    expect(screen.getAllByLabelText('فيديو المقارنة')).toHaveLength(1);
  });

  it('disables the other-voices slider with a plain message when unreliable', async () => {
    renderPanel({
      getMixInfo: async () => ({
        ...INFO, others_available: false, others_unavailable_reason: 'isolated audio does not match the original',
      }),
    });
    expect(await screen.findByText(/مقدرناش نطلّع أصوات الباقيين/)).toBeInTheDocument();
    expect(screen.getByLabelText('مستوى الأصوات التانية')).toBeDisabled();
  });

  it('exports with others at zero when unreliable and offers the download', async () => {
    const startExport = vi.fn(async () => ({ export_id: 'e1', status: 'rendering' as const }));
    const getExport = vi.fn(async () => ({ export_id: 'e1', status: 'ready' as const }));
    renderPanel({
      getMixInfo: async () => ({ ...INFO, others_available: false, others_unavailable_reason: 'x' }),
      startExport, getExport,
      fetchExport: async () => new Blob(['mp4'], { type: 'video/mp4' }),
    });
    const button = screen.getByRole('button', { name: /تصدير الفيديو/ });
    await waitFor(() => expect(button).toBeEnabled());
    await userEvent.click(button);
    expect(startExport).toHaveBeenCalledWith('job_test', {
      voice_level: 1, others_level: 0, noise_reduction: 'off',
    });
    expect(await screen.findByText('بنجهّز الفيديو الجديد…')).toBeInTheDocument();
    const link = await screen.findByRole('link', { name: /نزّل الفيديو/ }, { timeout: 4000 });
    expect(link).toHaveAttribute('href', 'blob:export');
  });

  it('shows an Arabic error when the export fails', async () => {
    renderPanel({
      startExport: async () => ({
        export_id: 'e2', status: 'failed' as const,
        error: { code: 'EXPORT_UNSUPPORTED', message: 'x', retryable: false },
      }),
    });
    const button = screen.getByRole('button', { name: /تصدير الفيديو/ });
    await waitFor(() => expect(button).toBeEnabled());
    await userEvent.click(button);
    expect(await screen.findByText('مقدرناش نصدّر الفيديو')).toBeInTheDocument();
  });
});
