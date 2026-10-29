import type { ReactNode } from 'react';

export type PillTone = 'neutral' | 'info' | 'ok' | 'warn' | 'danger';

interface PillProps {
  tone?: PillTone;
  busy?: boolean;
  children: ReactNode;
}

export function Pill({ tone = 'neutral', busy = false, children }: PillProps) {
  return (
    <span className={`pill pill--${tone}${busy ? ' pill--busy' : ''}`}>{children}</span>
  );
}
