import { formatDealAmount } from '../lib/deals';
/**
 * E3 — "My work": the caller's personal, portfolio-level worklist from
 * GET /api/worklist/mine/ (scope re-evaluated server-side on every read).
 * Three sections — my tasks, renewals, QBRs — each capped at 5 rows with an
 * honest "Showing N of M" line. Money stays null-honest (never a $0 for
 * unknown); task due rendering and the QBR strings reuse the established ones.
 */
import { useCallback, useEffect, useRef, useState } from 'react';
import type { CSSProperties, ReactNode } from 'react';
import { api } from '../lib/api';
import { renderDue } from '../lib/engagement';
import { formatPipelineAmount } from '../lib/accountImpact';
import { RENEWAL_BUCKET_LABELS, formatDate } from '../lib/pipelineFormat';
import { qbrHeadline } from './AccountTimelinePanel';
import type { ClosingDeal, WorklistQbr, WorklistRenewal, WorklistResponse } from '../types/savedViews';
import type { MyTask } from '../types/engagement';

export const SECTION_CAP = 5;

interface Props {
  /** Account-agnostic by design. */
  customerId?: never;
  onOpenCustomer?: (customerId: number, dealId?: number) => void;
}

export function bucketLabel(bucket: string): string {
  return (RENEWAL_BUCKET_LABELS as Record<string, string>)[bucket] ?? bucket;
}

export function worklistQbrLine(q: WorklistQbr): string {
  return qbrHeadline({ state: q.state, next_qbr_due: q.next_qbr_due, days_until: q.days_until, last_qbr_date: null, cadence_days: 0 });
}

const row: CSSProperties = {
  display: 'flex', gap: '10px', alignItems: 'center', flexWrap: 'wrap', width: '100%', minWidth: 0, boxSizing: 'border-box',
  overflowWrap: 'anywhere', padding: '8px 10px', border: '1px solid var(--divider)', borderRadius: 'var(--radius)',
  background: 'var(--neutral-0)', fontSize: '0.85rem', textAlign: 'left', color: 'inherit', fontFamily: 'inherit',
};
const muted: CSSProperties = { fontSize: '0.85rem', color: 'var(--neutral-500)' };
const chip: CSSProperties = { fontSize: '0.72rem', color: 'var(--neutral-600)', background: 'var(--neutral-100)', borderRadius: '10px', padding: '2px 8px' };

function Section<T>({ id, title, items, empty, render, truncated = false }: {
  id: string; title: string; items: readonly T[]; empty: string; render: (item: T) => ReactNode; truncated?: boolean;
}) {
  const shown = items.slice(0, SECTION_CAP);
  return (
    <section data-testid={`my-work-${id}`} aria-label={title} style={{ display: 'flex', flexDirection: 'column', gap: '6px', minWidth: 0 }}>
      <h4 style={{ margin: 0, fontSize: '0.9rem', color: 'var(--neutral-700)' }}>{title}</h4>
      {items.length === 0 ? (
        <div data-testid={`my-work-${id}-empty`} style={muted}>{empty}</div>
      ) : (
        <>
          {shown.map(render)}
          {items.length > SECTION_CAP && (
            <div data-testid={`my-work-${id}-truncated`} style={{ ...muted, fontSize: '0.75rem' }}>
              Showing {shown.length} of {truncated ? `at least ${items.length + 1}` : items.length}
            </div>
          )}
        </>
      )}
    </section>
  );
}

export function MyWorkBlock({ onOpenCustomer }: Props) {
  const [data, setData] = useState<WorklistResponse | null>(null);
  const [failed, setFailed] = useState(false);
  const seq = useRef(0);

  const load = useCallback(() => {
    const mine = ++seq.current;
    setData(null);
    setFailed(false);
    // A failure here must never take down the rest of the dashboard.
    Promise.resolve()
      .then(() => api.myWorklist())
      .then(r => { if (mine === seq.current) setData(r); })
      .catch(() => { if (mine === seq.current) setFailed(true); });
  }, []);

  useEffect(() => {
    load();
    return () => { seq.current += 1; };
  }, [load]);

  const open = (customerId: number) => onOpenCustomer?.(customerId);
  const clickable: CSSProperties = { ...row, cursor: onOpenCustomer ? 'pointer' : 'default' };

  const renderTask = (t: MyTask) => (
    <button
      key={`t-${t.id}`} type="button" data-testid={`my-work-task-${t.id}`} disabled={!onOpenCustomer}
      aria-label={`Open account ${t.customer_name} for task ${t.title}`} onClick={() => open(t.customer_id)} style={clickable}
    >
      <span style={{ fontWeight: 600, color: 'var(--ink)' }}>{t.title}</span>
      <span style={{ color: 'var(--neutral-600)' }}>{t.customer_name}</span>
      <span data-testid={`my-work-task-due-${t.id}`} style={{ color: t.overdue ? 'var(--status-negative)' : 'var(--neutral-600)', fontWeight: t.overdue ? 700 : 400 }}>
        Due: {renderDue(t)}{t.overdue ? ' (overdue)' : ''}
      </span>
    </button>
  );

  const renderRenewal = (r: WorklistRenewal) => (
    <button
      key={`r-${r.customer_id}`} type="button" data-testid={`my-work-renewal-${r.customer_id}`} disabled={!onOpenCustomer}
      aria-label={`Open account ${r.customer_name} renewal`} onClick={() => open(r.customer_id)} style={clickable}
    >
      <span style={{ fontWeight: 600, color: 'var(--ink)' }}>{r.customer_name}</span>
      <span data-testid={`my-work-renewal-opp-${r.customer_id}`} style={{ color: 'var(--neutral-600)' }}>
        {r.opportunity_name ?? 'Opportunity not recorded'}
      </span>
      <span data-testid={`my-work-renewal-bucket-${r.customer_id}`} style={chip}>{bucketLabel(r.bucket)}</span>
      <span data-testid={`my-work-renewal-end-${r.customer_id}`} style={{ color: 'var(--neutral-600)' }}>
        {r.end_date ? `Ends ${formatDate(r.end_date)}` : 'End date not recorded'}
      </span>
      <span data-testid={`my-work-renewal-money-${r.customer_id}`} style={{ color: 'var(--neutral-600)' }}>
        ACV {formatPipelineAmount(r.acv_usd)} · TCV {formatPipelineAmount(r.tcv_usd)}
      </span>
    </button>
  );

  const renderDeal = (deal: ClosingDeal) => <button key={deal.id} type="button" disabled={!onOpenCustomer} onClick={() => onOpenCustomer?.(deal.customer_id, deal.id)} style={clickable}>
    <strong>{deal.name}</strong><span>{deal.customer_name} · Close {deal.close_date}</span><span>{formatDealAmount(deal)}</span>
  </button>;

  const renderQbr = (q: WorklistQbr) => (
    <button
      key={`q-${q.customer_id}`} type="button" data-testid={`my-work-qbr-${q.customer_id}`} disabled={!onOpenCustomer}
      aria-label={`Open account ${q.customer_name} QBR`} onClick={() => open(q.customer_id)} style={clickable}
    >
      <span style={{ fontWeight: 600, color: 'var(--ink)' }}>{q.customer_name}</span>
      <span data-testid={`my-work-qbr-state-${q.customer_id}`} style={{ color: q.state === 'overdue' ? 'var(--status-negative)' : 'var(--neutral-600)', fontWeight: q.state === 'overdue' ? 700 : 400 }}>
        {worklistQbrLine(q)}
      </span>
    </button>
  );

  return (
    <div data-testid="my-work" style={{ background: 'var(--neutral-0)', borderRadius: 'var(--radius)', boxShadow: 'var(--shadow-card)', padding: '16px', minWidth: 0 }}>
      <h3 style={{ margin: '0 0 10px', fontSize: '1.05rem', color: 'var(--neutral-700)' }}>My Work</h3>
      {failed ? (
        <div role="alert" data-testid="my-work-error" style={{ ...muted, color: 'var(--status-negative)', display: 'flex', gap: '8px', alignItems: 'center', flexWrap: 'wrap' }}>
          Worklist unavailable. Try again.
          <button type="button" onClick={load}>Retry</button>
        </div>
      ) : data === null ? (
        <div style={muted}>Loading worklist…</div>
      ) : (
        <div style={{ display: 'grid', gridTemplateColumns: 'minmax(0, 1fr)', gap: '14px' }}>
          <Section id="tasks" title="My tasks" items={data.tasks ?? []} truncated={data.truncated?.tasks} empty="No open tasks." render={renderTask} />
          <Section id="renewals" title="Renewals" items={data.renewals ?? []} truncated={data.truncated?.renewals} empty="No renewals due." render={renderRenewal} />
          <Section id="closing-deals" title="My closing deals · overdue or within 90 days" items={data.closing_deals ?? []} truncated={data.truncated?.closing_deals} empty="No closing deals recorded." render={renderDeal} />
          <Section id="qbr" title="QBR" items={data.qbr ?? []} truncated={data.truncated?.qbr} empty="No QBRs due." render={renderQbr} />
        </div>
      )}
    </div>
  );
}

export default MyWorkBlock;
