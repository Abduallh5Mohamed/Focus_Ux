import { beforeEach, expect, it, vi } from 'vitest';
import { withSessionCapture } from '../ApiContext';
import { createMockApi } from '../mock';
import { ApiError } from '../errors';
import { getToken, readSession, saveSession } from '../../session';

beforeEach(() => window.localStorage.clear());
const file = new File(['fixture'], 'test.mp4', { type: 'video/mp4' });

it('replaces a rejected stale session once when starting a new upload', async () => {
  saveSession({ token: 'test-expired', videoId: 'old', jobId: 'old-job' });
  const api = createMockApi({ latencyMs: 0 });
  const upload = vi.spyOn(api, 'uploadVideo')
    .mockRejectedValueOnce(new ApiError({ code: 'UNAUTHORIZED', status: 401, message: 'expired' }))
    .mockImplementationOnce(async () => {
      expect(getToken()).toBeNull();
      return { video_id: 'new', session_token: 'test-renewed' } as Awaited<ReturnType<typeof api.uploadVideo>>;
    });
  await withSessionCapture(api).uploadVideo(file);
  expect(upload).toHaveBeenCalledTimes(2);
  expect(readSession()).toEqual({ token: 'test-renewed', videoId: 'new', jobId: null });
});

it('does not retry a second unauthorized response', async () => {
  saveSession({ token: 'test-expired' });
  const api = createMockApi();
  const error = new ApiError({ code: 'UNAUTHORIZED', status: 401, message: 'expired' });
  const upload = vi.spyOn(api, 'uploadVideo').mockRejectedValue(error);
  await expect(withSessionCapture(api).uploadVideo(file)).rejects.toBe(error);
  expect(upload).toHaveBeenCalledTimes(2);
});

it('preserves the session and does not retry forbidden responses', async () => {
  saveSession({ token: 'test-valid' });
  const api = createMockApi();
  const error = new ApiError({ code: 'UNAUTHORIZED', status: 403, message: 'forbidden' });
  const upload = vi.spyOn(api, 'uploadVideo').mockRejectedValue(error);
  await expect(withSessionCapture(api).uploadVideo(file)).rejects.toBe(error);
  expect(upload).toHaveBeenCalledTimes(1);
  expect(getToken()).toBe('test-valid');
});
