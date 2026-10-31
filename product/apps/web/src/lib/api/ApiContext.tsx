import { createContext, useContext, useMemo, type ReactNode } from 'react';

import { createHttpApi, type FocusApi } from './client';
import { createMockApi } from './mock';
import { API_BASE_URL, IS_DEV_MOCK } from '../env';
import { clearSession, getToken, saveSession } from '../session';
import { isApiError } from './errors';

interface ApiContextValue {
  api: FocusApi;
  isMock: boolean;
}

const ApiContext = createContext<ApiContextValue | null>(null);

/**
 * Wraps the transport so the session token handed back by the first upload is persisted
 * exactly once, in the API layer instead of in each screen.
 */
export function withSessionCapture(api: FocusApi): FocusApi {
  return {
    ...api,
    async uploadVideo(file, options) {
      const previousToken = getToken();
      let response;
      try {
        response = await api.uploadVideo(file, options);
      } catch (error) {
        // A rejected old session must not permanently block a new upload.
        // Only retry a definitive 401, never ambiguous network errors or 403s.
        if (!previousToken || !isApiError(error) || error.status !== 401 ||
            options?.signal?.aborted || getToken() !== previousToken) throw error;
        clearSession();
        response = await api.uploadVideo(file, options);
      }
      if (response.session_token) saveSession({ token: response.session_token });
      if (response.video_id) saveSession({ videoId: response.video_id, jobId: null });
      return response;
    },
  };
}

export function ApiProvider({
  children,
  api,
  isMock,
}: {
  children: ReactNode;
  /** Test seam: inject a transport instead of building one from the environment. */
  api?: FocusApi;
  isMock?: boolean;
}) {
  const value = useMemo<ApiContextValue>(() => {
    if (api) return { api: withSessionCapture(api), isMock: isMock ?? false };
    const transport = IS_DEV_MOCK
      ? createMockApi()
      : createHttpApi({ baseUrl: API_BASE_URL, getToken });
    return { api: withSessionCapture(transport), isMock: IS_DEV_MOCK };
  }, [api, isMock]);

  return <ApiContext.Provider value={value}>{children}</ApiContext.Provider>;
}

export function useApi(): FocusApi {
  return useApiContext().api;
}

export function useIsMockApi(): boolean {
  return useApiContext().isMock;
}

function useApiContext(): ApiContextValue {
  const context = useContext(ApiContext);
  if (!context) throw new Error('useApi must be used inside <ApiProvider>');
  return context;
}
