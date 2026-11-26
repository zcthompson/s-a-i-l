import type { CSSProperties } from 'react';

/** Inline-style conventions shared by the Intelligence Import vendor panes. */
export const cardStyle: CSSProperties = {
  background: 'var(--neutral-0)', borderRadius: 'var(--radius)',
  boxShadow: 'var(--shadow-card)', padding: '16px 20px', marginBottom: '16px',
};
export const thStyle: CSSProperties = { padding: '10px 12px', textAlign: 'left', fontSize: '0.8rem', fontWeight: 600, color: 'var(--neutral-500)' };
export const tdStyle: CSSProperties = { padding: '10px 12px', fontSize: '0.85rem', verticalAlign: 'middle' };
export const numStyle: CSSProperties = { ...tdStyle, textAlign: 'right' };
export const linkBtn: CSSProperties = { background: 'none', border: 'none', color: 'var(--brand-700)', cursor: 'pointer', fontSize: '0.85rem', textDecoration: 'underline', padding: 0 };

/** Non-blocking import warning banner. */
export const warningStyle: CSSProperties = {
  marginTop: '10px', padding: '8px 12px', fontSize: '0.85rem', fontWeight: 500,
  color: 'var(--neutral-700)', background: 'var(--neutral-50, #f5f9fa)',
  borderLeft: '4px solid var(--status-warning)',
};

/** The operator-specified warning for rows no customer name or alias matched. */
export function unmatchedRowsWarning(rows: number): string {
  return `${rows} row${rows === 1 ? '' : 's'} could not be imported — no matching customer name or alias. The rest of the file was imported; no customers were created.`;
}

export function isForbidden(err: unknown): boolean {
  return (err as { status?: number } | null)?.status === 403;
}
