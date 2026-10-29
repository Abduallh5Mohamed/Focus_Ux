/**
 * Local session state.
 *
 * Holds only opaque identifiers — never file contents, audio, transcripts or tokens in a URL.
 * Scope is this browser profile, which is enough to survive a refresh without leaking one
 * visitor's job into another session.
 */

const KEY = 'focus.session.v1';

export interface StoredSession {
  token: string | null;
  videoId: string | null;
  jobId: string | null;
}

const EMPTY: StoredSession = { token: null, videoId: null, jobId: null };

function storage(): Storage | null {
  try {
    const probe = '__focus_probe__';
    window.localStorage.setItem(probe, '1');
    window.localStorage.removeItem(probe);
    return window.localStorage;
  } catch {
    return null;
  }
}

export function readSession(): StoredSession {
  const store = storage();
  if (!store) return { ...EMPTY };
  try {
    const raw = store.getItem(KEY);
    if (!raw) return { ...EMPTY };
    const parsed = JSON.parse(raw) as Partial<StoredSession>;
    return {
      token: typeof parsed.token === 'string' ? parsed.token : null,
      videoId: typeof parsed.videoId === 'string' ? parsed.videoId : null,
      jobId: typeof parsed.jobId === 'string' ? parsed.jobId : null,
    };
  } catch {
    return { ...EMPTY };
  }
}

export function saveSession(patch: Partial<StoredSession>): StoredSession {
  const next = { ...readSession(), ...patch };
  const store = storage();
  if (store) {
    try {
      store.setItem(KEY, JSON.stringify(next));
    } catch {
      // Storage full or blocked: the flow still works, it just will not survive a refresh.
    }
  }
  return next;
}

export function clearSession(): void {
  const store = storage();
  if (!store) return;
  try {
    store.removeItem(KEY);
  } catch {
    /* ignore */
  }
}

/** Drops the finished job but keeps the session token and the video it belongs to. */
export function clearJob(): void {
  saveSession({ jobId: null });
}

export function getToken(): string | null {
  return readSession().token;
}
