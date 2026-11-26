import type { ButtonHTMLAttributes, ReactNode } from 'react';

type Props = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: 'primary' | 'danger' | 'secondary' | 'quiet';
  busy?: boolean;
  icon?: ReactNode;
  density?: 'standard' | 'compact';
};

/** Keep labels and the icon slot stable while an action is in flight. */
export function ActionButton({ variant = 'primary', type = 'button', busy, disabled, icon, density = 'standard', children, ...props }: Props) {
  return <button {...props} type={type} disabled={disabled || busy} aria-busy={busy || undefined} data-ui="action-button" data-variant={variant} data-density={density}>
    {(icon || busy !== undefined) && <span aria-hidden="true" data-ui="action-icon">{busy ? <span data-ui="action-spinner" /> : icon}</span>}
    {children}
  </button>;
}
