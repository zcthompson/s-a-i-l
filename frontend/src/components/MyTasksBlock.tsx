/**
 * H5 — "My Tasks" block for the my-dashboard. Rows come from
 * GET /api/tasks/mine/ (already re-authorized server-side per account).
 * The overdue flag is the server's; rows navigate to the account detail.
 */
import { useEffect, useId, useState } from 'react';
import { api } from '../lib/api';
import { renderDue } from '../lib/engagement';
import type { MyTask } from '../types/engagement';

interface Props {
  username: string;
  onOpenAccount: (customerName: string) => void;
}

export function MyTasksBlock({ username, onOpenAccount }: Props) {
  const descriptionPrefix = useId();
  const [tasks, setTasks] = useState<MyTask[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    setTasks(null);
    setError(null);
    // A failure here must never take down the rest of the dashboard.
    Promise.resolve()
      .then(() => api.myTasks())
      .then((t) => { if (alive) setTasks(Array.isArray(t) ? t : []); })
      .catch((e: any) => { if (alive) setError(e?.message || 'Failed to load tasks'); });
    return () => { alive = false; };
  }, [username]);

  const overdueCount = (tasks ?? []).filter((t) => t.overdue).length;

  return (
    <div data-testid="my-tasks" style={{ background: 'var(--neutral-0)', borderRadius: 'var(--radius)', boxShadow: 'var(--shadow-card)', padding: '16px' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: '10px', marginBottom: '10px', flexWrap: 'wrap' }}>
        <h3 style={{ margin: 0, fontSize: '1.05rem', color: 'var(--neutral-700)' }}>My Tasks</h3>
        {tasks && (
          <>
            <span data-testid="my-tasks-open-count" style={{ fontSize: '0.75rem', fontWeight: 600, color: 'var(--brand-700)', background: 'var(--brand-50)', borderRadius: '10px', padding: '2px 10px' }}>
              {tasks.length} open
            </span>
            <span data-testid="my-tasks-overdue-count" style={{ fontSize: '0.75rem', fontWeight: 600, color: overdueCount > 0 ? 'var(--status-negative)' : 'var(--neutral-500)', background: overdueCount > 0 ? 'var(--status-negative-soft)' : 'var(--neutral-100)', borderRadius: '10px', padding: '2px 10px' }}>
              {overdueCount} overdue
            </span>
          </>
        )}
      </div>
      {error ? (
        <div role="alert" data-testid="my-tasks-error" style={{ fontSize: '0.85rem', color: 'var(--status-negative)' }}>{error}</div>
      ) : tasks === null ? (
        <div style={{ fontSize: '0.85rem', color: 'var(--neutral-500)' }}>Loading…</div>
      ) : tasks.length === 0 ? (
        <div style={{ fontSize: '0.85rem', color: 'var(--neutral-500)' }}>No open tasks assigned to you.</div>
      ) : (
        <div style={{ display: 'grid', gridTemplateColumns: 'minmax(0, 1fr)', gap: '6px', minWidth: 0 }}>
          {tasks.map((t) => (
            <div
              key={t.id}
              role="button"
              tabIndex={0}
              data-testid={`my-task-${t.id}`}
              aria-label={`Open account ${t.customer_name} for task ${t.title}`}
              aria-describedby={`${descriptionPrefix}-task-${t.id}`}
              onClick={() => onOpenAccount(t.customer_name)}
              onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onOpenAccount(t.customer_name); } }}
              style={{ display: 'flex', gap: '12px', alignItems: 'center', flexWrap: 'wrap', minWidth: 0, maxWidth: '100%', boxSizing: 'border-box', overflowWrap: 'anywhere', padding: '8px 10px', border: '1px solid var(--divider)', borderRadius: 'var(--radius)', cursor: 'pointer', fontSize: '0.85rem' }}
            >
              <span style={{ fontWeight: 600, color: 'var(--ink)', minWidth: 0, maxWidth: '100%', overflowWrap: 'anywhere' }}>{t.title}</span>
              <span style={{ color: 'var(--neutral-600)', minWidth: 0, maxWidth: '100%', overflowWrap: 'anywhere' }}>{t.customer_name}</span>
              <span data-testid={`my-task-due-${t.id}`} style={{ color: t.overdue ? 'var(--status-negative)' : 'var(--neutral-600)', fontWeight: t.overdue ? 700 : 400, minWidth: 0, maxWidth: '100%', overflowWrap: 'anywhere' }}>
                Due: {renderDue(t)}{t.overdue ? ' (overdue)' : ''}
              </span>
              <span style={{ fontSize: '0.72rem', color: 'var(--neutral-600)', background: 'var(--neutral-100)', borderRadius: '10px', padding: '2px 8px', minWidth: 0, maxWidth: '100%', boxSizing: 'border-box', overflowWrap: 'anywhere' }}>{t.status}</span>
              <span id={`${descriptionPrefix}-task-${t.id}`} style={{ position: 'absolute', width: '1px', height: '1px', padding: 0, margin: '-1px', overflow: 'hidden', clip: 'rect(0, 0, 0, 0)', whiteSpace: 'nowrap', border: 0 }}>
                {t.due_date || t.due_at ? `Due: ${renderDue(t)}${t.overdue ? ', overdue' : ''}.` : `No due date${t.overdue ? ', overdue' : ''}.`} Status: {t.status}.
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
