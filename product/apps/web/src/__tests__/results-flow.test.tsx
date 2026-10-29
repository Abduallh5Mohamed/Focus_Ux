import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { ApiProvider } from '../lib/api/ApiContext';
import { createMockApi } from '../lib/api/mock';
import type { JobState } from '../lib/api/types';
import { ResultView } from '../features/results/ResultView';

/**
 * jsdom has no media stack: stub the three methods the transport touches so the component
 * tree can mount. Playback itself is not simulated — only that the UI wires it correctly.
 */
beforeEach(() => {
  window.HTMLMediaElement.prototype.load = vi.fn();
  window.HTMLMediaElement.prototype.play = vi.fn(() => Promise.resolve());
  window.HTMLMediaElement.prototype.pause = vi.fn();
  // jsdom implements neither object URLs nor a media stack.
  URL.createObjectURL = vi.fn(() => 'blob:focus-test');
  URL.revokeObjectURL = vi.fn();
});

const JOB: JobState = {
  job_id: 'job_test',
  status: 'completed',
  stage: 'ready',
  selected_face_id: 'face_1',
  audio_status: 'ready',
  transcript_status: 'ready',
  queue_position: 0,
  error: null,
  result: { duration_ms: 9_000, sample_rate: 16_000 },
};

function renderResults() {
  const api = createMockApi({ latencyMs: 0 });
  const onDeleted = vi.fn();
  render(
    <ApiProvider api={api} isMock>
      <ResultView job={JOB} videoId="vid_test" onDeleted={onDeleted} />
    </ApiProvider>,
  );
  return { onDeleted };
}

describe('ResultView', () => {
  it('renders exactly one audio element for both tracks', async () => {
    renderResults();
    await waitFor(() => {
      expect(screen.getAllByLabelText('مشغل المقارنة')).toHaveLength(1);
    });
  });

  it('offers both tracks once the WAV and original are fetched', async () => {
    renderResults();
    await waitFor(() => {
      expect(screen.getByRole('radio', { name: 'المعزول' })).toBeEnabled();
      expect(screen.getByRole('radio', { name: 'الأصل' })).toBeEnabled();
    });
  });

  it('enables the WAV download only after the blob exists', async () => {
    renderResults();
    const download = screen.getByRole('button', { name: /تنزيل WAV/ });
    expect(download).toBeDisabled();
    await waitFor(() => expect(download).toBeEnabled());
  });

  it('lists transcript segments and seeks without crashing', async () => {
    renderResults();
    const segment = await screen.findByRole('button', { name: /أهلًا بيكم/ });
    expect(segment).toBeInTheDocument();
    await userEvent.click(segment);
    expect(segment).toBeInTheDocument();
  });

  it('requires a second confirmation before deleting', async () => {
    const { onDeleted } = renderResults();
    const deleteButton = screen.getByRole('button', { name: /حذف الطلب/ });
    await userEvent.click(deleteButton);
    expect(onDeleted).not.toHaveBeenCalled();

    await userEvent.click(screen.getByRole('button', { name: /أيوه، احذف/ }));
    await waitFor(() => expect(onDeleted).toHaveBeenCalledTimes(1));
  });

  it('marks the transcript as machine generated, not ground truth', async () => {
    renderResults();
    expect(screen.getByText(/نص آلي غير مُراجع/)).toBeInTheDocument();
  });
});
