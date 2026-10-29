import { beforeEach, describe, expect, it } from 'vitest';

import { clearJob, clearSession, readSession, saveSession } from '../session';

describe('session store', () => {
  beforeEach(() => {
    window.localStorage.clear();
  });

  it('starts empty', () => {
    expect(readSession()).toEqual({ token: null, videoId: null, jobId: null });
  });

  it('merges patches instead of replacing the record', () => {
    saveSession({ token: 't1' });
    saveSession({ videoId: 'v1' });
    expect(readSession()).toEqual({ token: 't1', videoId: 'v1', jobId: null });
  });

  it('drops only the job id on clearJob', () => {
    saveSession({ token: 't1', videoId: 'v1', jobId: 'j1' });
    clearJob();
    expect(readSession()).toEqual({ token: 't1', videoId: 'v1', jobId: null });
  });

  it('wipes everything on clearSession', () => {
    saveSession({ token: 't1', videoId: 'v1', jobId: 'j1' });
    clearSession();
    expect(readSession()).toEqual({ token: null, videoId: null, jobId: null });
  });

  it('survives corrupted storage instead of throwing', () => {
    window.localStorage.setItem('focus.session.v1', '{not json');
    expect(readSession()).toEqual({ token: null, videoId: null, jobId: null });
  });

  it('ignores non-string values from storage', () => {
    window.localStorage.setItem(
      'focus.session.v1',
      JSON.stringify({ token: 42, videoId: 'v1', jobId: null }),
    );
    expect(readSession().token).toBeNull();
    expect(readSession().videoId).toBe('v1');
  });
});
