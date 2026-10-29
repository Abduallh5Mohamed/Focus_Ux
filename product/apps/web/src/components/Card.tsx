import type { ReactNode } from 'react';

interface CardProps {
  children: ReactNode;
  flush?: boolean;
  quiet?: boolean;
  className?: string;
}

export function Card({ children, flush = false, quiet = false, className }: CardProps) {
  const classes = ['card', flush ? 'card--flush' : '', quiet ? 'card--quiet' : '', className ?? '']
    .filter(Boolean)
    .join(' ');
  return <section className={classes}>{children}</section>;
}

interface CardHeadProps {
  title: ReactNode;
  hint?: ReactNode;
  action?: ReactNode;
}

export function CardHead({ title, hint, action }: CardHeadProps) {
  return (
    <div className="card__head">
      <div>
        <h2 className="card__title">{title}</h2>
        {hint ? <p className="card__hint">{hint}</p> : null}
      </div>
      {action}
    </div>
  );
}
