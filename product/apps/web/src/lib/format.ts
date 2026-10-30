/** Small formatting helpers shared by both feature areas. */

export function formatClock(seconds: number): string {
  if (!Number.isFinite(seconds) || seconds < 0) return '0:00';
  if (seconds > 0 && seconds < 1) {
    const fraction = Math.max(1, Math.floor(seconds * 1000)).toString().padStart(3, '0').replace(/0+$/, '');
    return `0:00.${fraction}`;
  }
  const total = Math.floor(seconds);
  const mm = Math.floor(total / 60);
  const ss = total % 60;
  return `${mm}:${ss.toString().padStart(2, '0')}`;
}

export function formatDuration(ms: number | null | undefined): string {
  if (ms === null || ms === undefined || !Number.isFinite(ms)) return '—';
  if (ms > 0 && ms < 1000) return `${Math.max(0.001, Math.round(ms) / 1000)} ث`;
  const totalSeconds = Math.round(ms / 1000);
  const mm = Math.floor(totalSeconds / 60);
  const ss = totalSeconds % 60;
  return mm > 0 ? `${mm} د ${ss} ث` : `${ss} ث`;
}

export function formatTimestamp(ms: number): string {
  return formatClock(ms / 1000);
}

export function formatBytes(bytes: number | null | undefined): string {
  if (bytes === null || bytes === undefined || !Number.isFinite(bytes)) return '—';
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value));
}
