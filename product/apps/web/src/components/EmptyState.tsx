import type { ReactNode } from 'react';

import { Icon, type IconName } from './Icon';

interface EmptyStateProps {
  icon?: IconName;
  title: ReactNode;
  children?: ReactNode;
  action?: ReactNode;
}

export function EmptyState({ icon = 'info', title, children, action }: EmptyStateProps) {
  return (
    <div className="empty">
      <Icon name={icon} size={26} />
      <p className="empty__title">{title}</p>
      {children ? <p>{children}</p> : null}
      {action}
    </div>
  );
}
