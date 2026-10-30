/** Build-time configuration. Only public, non-secret values belong here. */

function readFlag(value: unknown): boolean {
  return value === true || value === '1' || value === 'true';
}

export const API_BASE_URL = String(import.meta.env.VITE_API_BASE_URL ?? '').trim();

/**
 * Dev mock mode. Must be switched on explicitly (npm run dev:mock / VITE_DEV_MOCK_API=1).
 * A production build never enables it by accident because the flag defaults to off.
 */
export const IS_DEV_MOCK = readFlag(import.meta.env.VITE_DEV_MOCK_API) && import.meta.env.DEV;

export const APP_NAME = 'FOCUS';

/** Upload guard rails shown to the user. The server stays the final authority. */
function readNumber(value: unknown, fallback: number): number {
  const parsed = Number(value);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : fallback;
}

export const UPLOAD_LIMITS = {
  maxBytes: readNumber(import.meta.env.VITE_MAX_UPLOAD_MB, 200) * 1024 * 1024,
  /** About 3 minutes; keep in step with FOCUS_MAX_VIDEO_MS on the server. */
  maxDurationMs: readNumber(import.meta.env.VITE_MAX_VIDEO_SECONDS, 180) * 1000,
  accept: 'video/mp4,video/quicktime,video/webm,video/x-matroska',
} as const;

/** Experimental near-live mode is hidden unless explicitly enabled at build time. */
export const LIVE_ENABLED = readFlag(import.meta.env.VITE_LIVE_ENABLED);

/** Continuous sliding-window live path (needs FOCUS_LIVE_STREAM on the server). */
export const LIVE_STREAM = readFlag(import.meta.env.VITE_LIVE_STREAM);
