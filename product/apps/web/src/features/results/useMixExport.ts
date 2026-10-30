import { useCallback, useEffect, useRef, useState } from 'react';

import { useApi } from '../../lib/api/ApiContext';
import type { MixSettings } from '../../lib/api/types';

export type ExportPhase = 'idle' | 'rendering' | 'downloading' | 'done' | 'failed';

const POLL_MS = 1000;
const MAX_POLLS = 180;

/** Request an MP4 export, poll its status, then download the file. */
export function useMixExport(jobId: string) {
  const api = useApi();
  const [phase, setPhase] = useState<ExportPhase>('idle');
  const [error, setError] = useState<unknown>(null);
  const [url, setUrl] = useState<string | null>(null);
  const runRef = useRef(0);
  const urlRef = useRef<string | null>(null);

  const release = useCallback(() => {
    if (urlRef.current) URL.revokeObjectURL(urlRef.current);
    urlRef.current = null;
  }, []);

  useEffect(
    () => () => {
      runRef.current += 1;
      release();
    },
    [release],
  );

  const start = useCallback(
    async (settings: MixSettings) => {
      const run = ++runRef.current;
      const live = () => runRef.current === run;
      release();
      setUrl(null);
      setError(null);
      setPhase('rendering');
      try {
        let state = await api.startExport(jobId, settings);
        for (let i = 0; state.status === 'rendering' && i < MAX_POLLS; i += 1) {
          await new Promise((resolve) => setTimeout(resolve, POLL_MS));
          if (!live()) return;
          state = await api.getExport(jobId, state.export_id);
        }
        if (!live()) return;
        if (state.status !== 'ready') {
          throw Object.assign(new Error(state.error?.message ?? 'export failed'), {
            exportError: state.error,
          });
        }
        setPhase('downloading');
        const blob = await api.fetchExport(jobId, state.export_id);
        if (!live()) return;
        const created = URL.createObjectURL(blob);
        urlRef.current = created;
        setUrl(created);
        setPhase('done');
      } catch (caught) {
        if (!live()) return;
        setError(caught);
        setPhase('failed');
      }
    },
    [api, jobId, release],
  );

  return { phase, error, url, start };
}
