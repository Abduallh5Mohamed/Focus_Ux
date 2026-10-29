/**
 * In-memory handle on the file the visitor just uploaded.
 *
 * The API contract exposes the isolated WAV (GET /jobs/{id}/audio) but has no endpoint
 * for the original track, so "compare with the original" can only be honest while the
 * uploaded file is still in this tab. Nothing is persisted: after a refresh the original
 * is reported as unavailable instead of being faked.
 */

interface RememberedUpload {
  videoId: string;
  file: File;
}

let current: RememberedUpload | null = null;

export function rememberUpload(videoId: string, file: File): void {
  current = { videoId, file };
}

export function getRememberedUpload(videoId: string | null | undefined): File | null {
  if (!videoId || !current) return null;
  return current.videoId === videoId ? current.file : null;
}

export function forgetUpload(videoId?: string): void {
  if (!videoId || current?.videoId === videoId) current = null;
}
