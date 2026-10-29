import type { ReactNode } from 'react';

interface PageHeaderProps {
  eyebrow?: string;
  title: ReactNode;
  lead?: ReactNode;
  action?: ReactNode;
}

export function PageHeader({ eyebrow, title, lead, action }: PageHeaderProps) {
  return (
    <header className="page-head">
      {eyebrow ? <p className="page-head__eyebrow">{eyebrow}</p> : null}
      <div className="row row--between">
        <h1 className="page-head__title">{title}</h1>
        {action}
      </div>
      {lead ? <p className="page-head__lead">{lead}</p> : null}
    </header>
  );
}
