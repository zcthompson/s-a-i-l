/**
 * E1 — Account 360 timeline panel (+ E10 QBR cadence header).
 *
 * Read-only, derived feed: the backend merges notes, activities, task and
 * contact events, imports (labelled "imported" — never business events),
 * strategy publishes and scoped membership audit. Pagination uses the opaque
 * cursor verbatim; a superseded response (rapid clicks / customer switch) is
 * ignored via a request sequence number.
 */
import { useCallback, useEffect, useRef, useState } from 'react';
import { api } from '../lib/api';
import { renderOccurred } from '../lib/engagement';
import { hasDestination } from '../lib/useCustomerRecord';
import type { AccountTimelineResponse, TimelineItem, TimelineQbr } from '../types/accountTimeline';

interface Props {
  customerId: number;
  onSelect?: (module: string, id: number) => void;
}

export function qbrHeadline(qbr: TimelineQbr): string {
  switch (qbr.state) {
    case 'current':
      return `Next QBR due ${qbr.next_qbr_due}`;
    case 'due_soon':
      return `QBR due ${qbr.next_qbr_due} (in ${qbr.days_until} days)`;
    case 'overdue':
      return `QBR overdue (${Math.abs(qbr.days_until ?? 0)} days late)`;
    default:
      return 'No QBR recorded';
  }
}

function renderWhen(item: TimelineItem): string {
  if (item.timestamp === null) return '—';
  return renderOccurred(item.date_only
    ? { occurred_at: null, occurred_date: item.timestamp }
    : { occurred_at: item.timestamp, occurred_date: null });
}

const chipStyle: React.CSSProperties = {
  fontSize: '0.7rem', fontWeight: 600, padding: '2px 6px', borderRadius: 'var(--radius)',
  background: 'var(--neutral-100, #f0f0f0)', color: 'var(--neutral-600)', letterSpacing: '0.03em',
};

export function AccountTimelinePanel({ customerId, onSelect }: Props) {
  const [data, setData] = useState<AccountTimelineResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);
  const [moreError, setMoreError] = useState(false);
  const seq = useRef(0);

  const load = useCallback(async () => {
    const mine = ++seq.current;
    setLoading(true);
    setError(false);
    setLoadingMore(false);
    setMoreError(false);
    try {
      const page = await api.getAccountTimeline(customerId);
      if (mine !== seq.current) return;
      setData(page);
    } catch {
      if (mine !== seq.current) return;
      setData(null);
      setError(true);
    } finally {
      if (mine === seq.current) setLoading(false);
    }
  }, [customerId]);

  useEffect(() => {
    setData(null);
    load();
    return () => { seq.current += 1; };
  }, [load]);

  const loadOlder = async () => {
    if (!data?.next_cursor) return;
    const mine = ++seq.current;
    const cursor = data.next_cursor;
    setLoadingMore(true);
    setMoreError(false);
    try {
      const page = await api.getAccountTimeline(customerId, undefined, cursor);
      if (mine !== seq.current) return;
      setData((prev) => prev && ({ ...page, items: [...prev.items, ...page.items] }));
    } catch {
      if (mine !== seq.current) return;
      setMoreError(true);
    } finally {
      if (mine === seq.current) setLoadingMore(false);
    }
  };

  if (loading) return <div data-testid="timeline-loading">Loading timeline…</div>;
  if (error || data === null) {
    return (
      <div data-testid="timeline-error">
        <span>Timeline unavailable. Try again.</span>{' '}
        <button type="button" onClick={() => load()}>Retry</button>
      </div>
    );
  }

  return (
    <div data-testid="account-timeline" style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
      <div data-testid="timeline-qbr" style={{ fontWeight: 600 }}>{qbrHeadline(data.qbr)}</div>
      {data.items.length === 0 ? (
        <div data-testid="timeline-empty">No recorded activity for this account.</div>
      ) : (
        <ul style={{ listStyle: 'none', margin: 0, padding: 0, display: 'flex', flexDirection: 'column', gap: '6px' }}>
          {data.items.map((item) => {
            const key = `${item.kind}-${item.id ?? 'computed'}-${item.timestamp ?? 'undated'}`;
            const selectable = item.id !== null && hasDestination(item.kind);
            const open = () => onSelect?.(item.kind, item.kind === 'deal' ? Number(new URLSearchParams(item.source_ref ?? '').get('id') ?? item.id) : item.id as number);
            return (
              <li
                key={key}
                data-testid={`timeline-item-${item.kind}-${item.id ?? 'computed'}`}
                role={selectable ? 'button' : undefined}
                tabIndex={selectable ? 0 : undefined}
                onClick={selectable ? open : undefined}
                onKeyDown={selectable ? (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); open(); } } : undefined}
                style={{ padding: '8px', border: '1px solid var(--divider)', borderRadius: 'var(--radius)',
                  cursor: selectable ? 'pointer' : 'default', display: 'flex', flexDirection: 'column', gap: '2px' }}
              >
                <div style={{ display: 'flex', gap: '6px', alignItems: 'center', flexWrap: 'wrap' }}>
                  <span data-testid="timeline-kind" style={chipStyle}>{item.kind.toUpperCase()}</span>
                  <span data-testid="timeline-title">{item.title}</span>
                  {item.imported && <span data-testid="timeline-imported" style={chipStyle}>imported</span>}
                </div>
                {item.detail && <div data-testid="timeline-detail" style={{ fontSize: '0.85rem' }}>{item.detail}</div>}
                <div style={{ fontSize: '0.75rem', color: 'var(--neutral-600)', display: 'flex', gap: '8px' }}>
                  <span data-testid="timeline-when">{renderWhen(item)}</span>
                  {item.actor && <span data-testid="timeline-actor">by {item.actor}</span>}
                </div>
              </li>
            );
          })}
        </ul>
      )}
      {moreError && <div data-testid="timeline-more-error">Timeline unavailable. Try again.</div>}
      {data.more && (loadingMore
        ? <div data-testid="timeline-loading-more">Loading…</div>
        : <button type="button" onClick={loadOlder}>Show older items</button>)}
    </div>
  );
}

export default AccountTimelinePanel;
