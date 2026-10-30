import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { ApiProvider } from '../lib/api/ApiContext';
import { createMockApi } from '../lib/api/mock';
import { FaceSelect } from '../features/input/FaceSelect';
import { IntakeFlow } from '../features/input/IntakeFlow';

beforeEach(() => {
  URL.createObjectURL = vi.fn(() => 'blob:focus-test');
  URL.revokeObjectURL = vi.fn();
});

function makeFile(name: string, type: string, bytes: number): File {
  const file = new File(['x'], name, { type });
  Object.defineProperty(file, 'size', { value: bytes });
  return file;
}

describe('IntakeFlow local validation', () => {
  function renderIntake() {
    const onUploaded = vi.fn();
    const api = createMockApi({ latencyMs: 0, facesReadyMs: 0 });
    const uploadSpy = vi.spyOn(api, 'uploadVideo');
    const view = render(
      <ApiProvider api={api} isMock>
        <MemoryRouter>
          <IntakeFlow onUploaded={onUploaded} />
        </MemoryRouter>
      </ApiProvider>,
    );
    const input = view.container.querySelector('input[type="file"]') as HTMLInputElement;
    return { onUploaded, uploadSpy, input };
  }

  it('rejects a file over the size limit without uploading it', async () => {
    const { input, uploadSpy } = renderIntake();
    fireEvent.change(input, { target: { files: [makeFile('big.mp4', 'video/mp4', 210 * 1024 * 1024)] } });

    expect(await screen.findByText('الملف أكبر من الحد المسموح')).toBeInTheDocument();
    expect(uploadSpy).not.toHaveBeenCalled();
  });

  it('rejects an unsupported container without uploading it', async () => {
    const { input, uploadSpy } = renderIntake();
    fireEvent.change(input, {
      target: { files: [makeFile('notes.txt', 'text/plain', 1024)] },
    });

    expect(await screen.findByText('صيغة الملف مش مدعومة')).toBeInTheDocument();
    expect(uploadSpy).not.toHaveBeenCalled();
  });

  it('accepts a small mp4 and offers the upload action', async () => {
    const { input } = renderIntake();
    fireEvent.change(input, { target: { files: [makeFile('clip.mp4', 'video/mp4', 1024 * 1024)] } });

    expect(await screen.findByText('clip.mp4')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /ارفع وابدأ/ })).toBeInTheDocument();
  });
});

describe('FaceSelect', () => {
  /** The mock only knows about videos it has actually accepted, so upload first. */
  async function renderFaces<T>(prepare?: (api: ReturnType<typeof createMockApi>) => T) {
    const api = createMockApi({ latencyMs: 0, facesReadyMs: 0 });
    const uploaded = await api.uploadVideo(makeFile('clip.mp4', 'video/mp4', 1024));
    const onJobCreated = vi.fn();
    // Spy before mounting: ApiProvider copies the transport into a wrapper.
    const prepared = prepare?.(api);
    render(
      <ApiProvider api={api} isMock>
        <MemoryRouter>
          <FaceSelect videoId={uploaded.video_id} onJobCreated={onJobCreated} />
        </MemoryRouter>
      </ApiProvider>,
    );
    return { onJobCreated, api, videoId: uploaded.video_id, prepared };
  }

  it('lists the candidates the server returned', async () => {
    await renderFaces();
    const options = await screen.findAllByRole('radio');
    expect(options).toHaveLength(2);
  });

  it('starts the job with the selected face id, not a list index', async () => {
    const { onJobCreated, videoId, prepared: createSpy } = await renderFaces((api) =>
      vi.spyOn(api, 'createJob'),
    );

    const options = await screen.findAllByRole('radio');
    await userEvent.click(options[1]);
    await userEvent.click(screen.getByRole('button', { name: /ابدأ عزل الصوت/ }));

    await waitFor(() => expect(onJobCreated).toHaveBeenCalledTimes(1));
    if (!createSpy) throw new Error('createJob spy was not installed');
    expect(createSpy).toHaveBeenCalledWith(
      expect.objectContaining({ video_id: videoId, face_id: `${videoId}_face_2` }),
    );
    expect(typeof createSpy.mock.calls[0][0].client_request_id).toBe('string');
  });

  it('keeps the confirm button disabled until a face is chosen', async () => {
    await renderFaces();
    await screen.findAllByRole('radio');
    expect(screen.getByRole('button', { name: /ابدأ عزل الصوت/ })).toBeDisabled();
  });
});
