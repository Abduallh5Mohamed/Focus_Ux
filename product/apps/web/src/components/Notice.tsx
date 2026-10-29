import type { ReactNode } from 'react';

import { Icon } from './Icon';

type Tone = 'info' | 'warn' | 'danger';

interface NoticeProps {
  tone?: Tone;
  title: ReactNode;
  children?: ReactNode;
  code?: string;
  action?: ReactNode;
}

const ICON: Record<Tone, 'info' | 'alert'> = {
  info: 'info',
  warn: 'alert',
  danger: 'alert',
};

export function Notice({ tone = 'info', title, children, code, action }: NoticeProps) {
  const role = tone === 'danger' ? 'alert' : 'status';
  return (
    <div className={`notice notice--${tone}`} role={role}>
      <Icon name={ICON[tone]} size={18} />
      <div className="notice__body">
        <p className="notice__title">{title}</p>
        {children ? <div className="notice__text">{children}</div> : null}
        {code ? <p className="notice__code">{code}</p> : null}
        {action ? <div style={{ marginTop: 'var(--sp-2)' }}>{action}</div> : null}
      </div>
    </div>
  );
}
