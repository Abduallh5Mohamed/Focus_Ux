import { clamp } from '../lib/format';

interface ProgressBarProps {
  /** 0..1 when a real, measured fraction exists (e.g. upload bytes). Omit for indeterminate. */
  value?: number;
  label?: string;
}

/**
 * Indeterminate by default. We never invent a percentage for server-side processing;
 * a determinate bar is only used when the browser reports real byte progress.
 */
export function ProgressBar({ value, label }: ProgressBarProps) {
  const determinate = typeof value === 'number' && Number.isFinite(value);
  const pct = determinate ? Math.round(clamp(value, 0, 1) * 100) : 0;

  return (
    <div
      className={`bar${determinate ? ' bar--determinate' : ''}`}
      role="progressbar"
      aria-label={label ?? 'التقدم'}
      aria-valuemin={determinate ? 0 : undefined}
      aria-valuemax={determinate ? 100 : undefined}
      aria-valuenow={determinate ? pct : undefined}
      aria-valuetext={determinate ? `${pct}%` : 'جارٍ'}
    >
      <span className="bar__fill" style={determinate ? { width: `${pct}%` } : undefined} />
    </div>
  );
}
