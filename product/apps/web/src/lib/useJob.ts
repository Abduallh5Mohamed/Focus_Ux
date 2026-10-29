import { useCallback, useEffect, useRef, useState } from 'react';

import { useApi } from './api/ApiContext';
import { isApiError } from './api/errors';
import { isTerminalStatus, type JobState } from './api/types';

export interface UseJobResult {
  job: JobState | null;
  error: unknown | null;
  /** True until the first successful response for this job id. */
  loading: boolean;
  /** True while the hook is still scheduling polls. */
  polling: boolean;
  refresh: () => void;
}

const ACTIVE_DELAY = 1_500;
const TRANSCRIPT_DELAY = 2_500;
const MAX_BACKOFF = 15_000;
const MAX_CONSECUTIVE_FAILURES = 6;
const MAX_POLLS = 240;

/**
 * Polls GET /jobs/{id} until the job is terminal and the transcript is settled.
 *
 * Deliberately no fake progress: the UI only ever sees real status/stage values.
 * Network hiccups back off exponentially instead of hammering the API.
 */
export function useJob(jobId: string | null): UseJobResult {
  const api = useApi();
  const [job, setJob] = useState<JobState | null>(null);
  const [error, setError] = useState<unknown | null>(null);
  const [loading, setLoading] = useState(Boolean(jobId));
  const [polling, setPolling] = useState(Boolean(jobId));
  const [nonce, setNonce] = useState(0);
  const jobRef = useRef<JobState | null>(null);

  const refresh = useCallback(() => setNonce((value) => value + 1), []);

  useEffect(() => {
    if (!jobId) {
      setJob(null);
      setLoading(false);
      setPolling(false);
      return;
    }

    let cancelled = false;
    let timer: number | undefined;
    let failures = 0;
    let polls = 0;

    setLoading(true);
    setPolling(true);

    const tick = async () => {
      polls += 1;
      try {
        const next = await api.getJob(jobId);
        if (cancelled) return;
        jobRef.current = next;
        setJob(next);
        setError(null);
        setLoading(false);
        failures = 0;

        const delay = nextDelay(next);
        if (delay === null || polls >= MAX_POLLS) {
          setPolling(false);
          return;
        }
        timer = window.setTimeout(tick, delay);
      } catch (caught) {
        if (cancelled) return;
        failures += 1;
        setLoading(false);

        const fatal = isApiError(caught) && !caught.retryable;
        if (fatal || failures >= MAX_CONSECUTIVE_FAILURES) {
          setError(caught);
          setPolling(false);
          return;
        }

        setError(caught);
        timer = window.setTimeout(tick, Math.min(ACTIVE_DELAY * 2 ** (failures - 1), MAX_BACKOFF));
      }
    };

    void tick();

    return () => {
      cancelled = true;
      if (timer) window.clearTimeout(timer);
    };
  }, [api, jobId, nonce]);

  return { job, error, loading, polling, refresh };
}

function nextDelay(job: JobState): number | null {
  if (!isTerminalStatus(job.status)) return ACTIVE_DELAY;
  if (job.transcript_status === 'pending' || job.transcript_status === 'processing') {
    return TRANSCRIPT_DELAY;
  }
  return null;
}
