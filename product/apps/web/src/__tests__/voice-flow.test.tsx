import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { ApiProvider } from '../lib/api/ApiContext';
import { createMockApi } from '../lib/api/mock';
import type { JobState } from '../lib/api/types';
import { FaceSelect } from '../features/input/FaceSelect';
import { ProcessingView } from '../features/input/ProcessingView';
import { VoiceConfirm, problemFor, warningsFor } from '../features/input/VoiceConfirm';
import { ComparePlayer } from '../features/results/ComparePlayer';

beforeEach(() => {
  URL.createObjectURL = vi.fn(() => 'blob:focus-test');
  URL.revokeObjectURL = vi.fn();
});

function setup() {
  const api = createMockApi({ latencyMs: 0, facesReadyMs: 0, engine: 'audio_only' });
  const onJobCreated = vi.fn();
  const create = vi.spyOn(api, 'createJob');
  const enroll = vi.spyOn(api, 'createEnrollment');
  const upload = vi.spyOn(api, 'createVoiceFileEnrollment');
  const fetchMedia = vi.spyOn(api, 'fetchMedia');
  render(
    <ApiProvider api={api} isMock>
      <MemoryRouter>
        <VoiceConfirm videoId="vid1" faceId="face1" onJobCreated={onJobCreated} />
      </MemoryRouter>
    </ApiProvider>,
  );
  return { api, onJobCreated, create, enroll, upload, fetchMedia };
}

describe('VoiceConfirm', () => {
  it('says the ranking is a suggestion, lists the suggested voice first and pre-selects it', async () => {
    setup();
    expect(await screen.findByText('ده اقتراح مش تأكيد')).toBeInTheDocument();
    const radios = await screen.findAllByRole('radio');
    expect(radios).toHaveLength(3);
    // voice-1 is ranked first by the server and is the pre-selected, suggested one.
    expect(radios[0]).toBeChecked();
    expect(screen.getByText('مقترح')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /أكّد الصوت المقترح/ })).toBeEnabled();
  });

  it('does nothing until the visitor confirms, then sends the enrollment — not a face — with the job', async () => {
    const { enroll, create, onJobCreated } = setup();
    await screen.findAllByRole('radio');
    expect(enroll).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole('button', { name: /أكّد الصوت المقترح/ }));
    await waitFor(() => expect(onJobCreated).toHaveBeenCalledTimes(1));
    expect(enroll).toHaveBeenCalledWith('vid1', { face_id: 'face1', source: 'voice', voice_id: 'voice-1' });
    const body = create.mock.calls[0][0];
    expect(body.enrollment_id).toBeTruthy();
    expect(body.face_id).toBeUndefined();
  });

  it('lets the visitor choose another candidate', async () => {
    const { enroll } = setup();
    const radios = await screen.findAllByRole('radio');
    await userEvent.click(radios[1]);
    await userEvent.click(screen.getByRole('button', { name: /أكّد وابدأ/ }));
    await waitFor(() => expect(enroll).toHaveBeenCalled());
    expect(enroll.mock.calls[0][1]).toMatchObject({ source: 'voice', voice_id: 'voice-0' });
  });

  it('shows a refusal reason and cannot select a too-short voice', async () => {
    setup();
    const radios = await screen.findAllByRole('radio');
    expect(radios[2]).toBeDisabled();
    expect(screen.getByText('سمعنا أقل من ٤ ثواني نضيفة من الصوت ده.')).toBeInTheDocument();
  });

  it('refuses a too-short manual range and enables a long enough one', async () => {
    const { enroll } = setup();
    await screen.findAllByRole('radio');
    await userEvent.click(screen.getByRole('button', { name: 'مدة بالوقت' }));
    fireEvent.change(screen.getByLabelText('بداية المدة'), { target: { value: '8000' } });
    expect(screen.getByText(/المدة قصيرة جدًا/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /أكّد وابدأ/ })).toBeDisabled();
    fireEvent.change(screen.getByLabelText('بداية المدة'), { target: { value: '1000' } });
    expect(screen.getByRole('button', { name: /أكّد وابدأ/ })).toBeEnabled();
    await userEvent.click(screen.getByRole('button', { name: /أكّد وابدأ/ }));
    await waitFor(() => expect(enroll).toHaveBeenCalledWith('vid1',
      { face_id: 'face1', source: 'range', start_ms: 1000, end_ms: 9000 }));
  });

  it('uploads a separate voice recording', async () => {
    const { upload, onJobCreated } = setup();
    await screen.findAllByRole('radio');
    await userEvent.click(screen.getByRole('button', { name: 'تسجيل منفصل' }));
    expect(screen.getByRole('button', { name: /أكّد وابدأ/ })).toBeDisabled();
    const file = new File(['x'], 'me.wav', { type: 'audio/wav' });
    fireEvent.change(screen.getByLabelText('ملف الصوت'), { target: { files: [file] } });
    await userEvent.click(screen.getByRole('button', { name: /أكّد وابدأ/ }));
    await waitFor(() => expect(onJobCreated).toHaveBeenCalled());
    expect(upload).toHaveBeenCalledWith('vid1', 'face1', file);
  });

  it('plays a sample only after the visitor asks', async () => {
    const { fetchMedia } = setup();
    await screen.findAllByRole('radio');
    expect(fetchMedia).not.toHaveBeenCalled();
    await userEvent.click(screen.getAllByRole('button', { name: 'اسمع العيّنة' })[0]);
    await waitFor(() => expect(fetchMedia).toHaveBeenCalledTimes(1));
  });
});

describe('enrollment validation helpers', () => {
  const voice = (over = {}) => ({
    voice_id: 'voice-0', speech_s: 9, clean_s: 9, overlap_fraction: 0, usable: true, refusal: null,
    warnings: [], sample: null, sample_url: null, ...over,
  });
  it('refuses too-short ranges, over-long ranges, missing files and unusable voices', () => {
    expect(problemFor('range', null, 3_999, null)).toMatch(/قصيرة/);
    expect(problemFor('range', null, 60_001, null)).toMatch(/طويلة/);
    expect(problemFor('range', null, 6_000, null)).toBeNull();
    expect(problemFor('file', null, 0, null)).toBeTruthy();
    expect(problemFor('voice', voice({ usable: false, refusal: 'قصيرة' }), 0, null)).toBe('قصيرة');
  });
  it('warns about short and overlapping samples without refusing them', () => {
    expect(warningsFor('voice', voice({ clean_s: 5 }), 0).join()).toMatch(/قصيرة/);
    expect(warningsFor('voice', voice({ overlap_fraction: 0.3 }), 0).join()).toMatch(/بيتداخل/);
    expect(warningsFor('range', null, 5_000)).toHaveLength(1);
    expect(warningsFor('range', null, 12_000)).toHaveLength(0);
  });
});

describe('FaceSelect in the audio-only flow', () => {
  it('hands the chosen face on to voice confirmation and creates no job', async () => {
    const api = createMockApi({ latencyMs: 0, facesReadyMs: 0, engine: 'audio_only' });
    const up = await api.uploadVideo(new File(['x'], 'c.mp4', { type: 'video/mp4' }));
    const create = vi.spyOn(api, 'createJob');
    const chosen = vi.fn();
    render(
      <ApiProvider api={api} isMock>
        <MemoryRouter>
          <FaceSelect videoId={up.video_id} onJobCreated={vi.fn()} onFaceChosen={chosen} />
        </MemoryRouter>
      </ApiProvider>,
    );
    const options = await screen.findAllByRole('radio');
    await userEvent.click(options[1]);
    await userEvent.click(screen.getByRole('button', { name: /التالي: تأكيد الصوت/ }));
    expect(chosen).toHaveBeenCalledWith(`${up.video_id}_face_2`);
    expect(create).not.toHaveBeenCalled();
  });
});

function job(over: Partial<JobState> = {}): JobState {
  return {
    job_id: 'j1', status: 'processing', stage: 'matching', selected_face_id: 'f', audio_status: 'pending',
    transcript_status: 'pending', queue_position: 0, error: null, result: null, transcript_enabled: false,
    ...over,
  };
}

describe('audio-only processing and result views', () => {
  function renderProcessing(j: JobState) {
    render(
      <ApiProvider api={createMockApi({ latencyMs: 0 })} isMock>
        <MemoryRouter>
          <ProcessingView job={j} error={null} loading={false} polling onRetry={vi.fn()} onOpenResult={vi.fn()} />
        </MemoryRouter>
      </ApiProvider>,
    );
  }
  it('shows the real stages and no transcription step', () => {
    renderProcessing(job());
    const rail = screen.getByRole('list', { name: 'مراحل المعالجة' });
    expect(rail.textContent).toContain('مطابقة الصوت المؤكَّد');
    expect(rail.textContent).not.toContain('تفريغ النص');
    expect(rail.textContent).not.toContain('تتبّع الوجه');
    expect(screen.queryByText('تفريغ النص')).toBeNull();
  });
  it('keeps the transcript row for the lip-based flow', () => {
    renderProcessing(job({ transcript_enabled: true, stage: 'tracking' }));
    expect(screen.getAllByText('تفريغ النص').length).toBeGreaterThan(0);
  });
  it('labels uncertain periods as muted on the timeline', () => {
    const transport = {
      playing: false, buffering: false, currentTime: 0, duration: 10, toggle: vi.fn(), seek: vi.fn(),
    } as never;
    const { container } = render(
      <ComparePlayer
        transport={transport}
        mode="isolated"
        onModeChange={vi.fn()}
        originalAvailable={false}
        originalSource={null}
        originalLoading={false}
        originalError={null}
        onRetryOriginal={vi.fn()}
        isolatedReady
        isolatedLoading={false}
        isolatedError={null}
        onRetryIsolated={vi.fn()}
        durationMs={10_000}
        followPeriods={[
          { start_ms: 0, end_ms: 6000, state: 'voice_follow', reason: 'voice_match', output_allowed: true },
          { start_ms: 6000, end_ms: 8000, state: 'uncertain', reason: 'close_score', output_allowed: false },
        ]}
      />,
    );
    expect(container.querySelector('.follow-strip__seg--uncertain')).not.toBeNull();
    expect(container.querySelector('.follow-strip__seg--voice_follow')).not.toBeNull();
    expect(container.textContent).toContain('مكتومة');
  });
});
