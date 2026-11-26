import { DealPromotion } from './DealPromotion';
import { useDealSources } from '../lib/useDealSources';
import { useAccountListState } from '../lib/useAccountListState';
/**
 * Partner pipeline panel (Intelligence Import) — the imported partner deal
 * rows for one account, from GET /api/customers/{name}/pipeline/ (latest
 * import batch only). Read-only; an honest empty state when nothing has been
 * imported for the account.
 */
import { useEffect, useState } from 'react';
import { api } from '../lib/api';
import {
  formatAmountWithCoverage, formatDate, formatDaysUntil, formatRenewalExposure, formatUsd,
  RENEWAL_BUCKET_LABELS,
} from '../lib/pipelineFormat';
import type {
  ComparisonAmountSide, ComparisonOpportunity, CustomerPipeline as CustomerPipelineData,
  PipelineComparison, RenewalAttention, RenewalBucketKey,
} from '../types/intelligence_import';

interface CustomerPipelineProps {
  customerName: string;
  customerId?: number;
  allowDeals?: boolean;
  onOpenDeal?: (id: number) => void;
}

const cardStyle = {
  background: 'var(--neutral-0)', borderRadius: 'var(--radius)', boxShadow: 'var(--shadow-card)',
  overflow: 'hidden', marginTop: '16px',
} as const;
const thStyle = { padding: '8px 12px', textAlign: 'left', fontSize: '0.8rem', fontWeight: 600, color: 'var(--neutral-500)' } as const;
const RENEWAL_BUCKET_ORDER: RenewalBucketKey[] = ['overdue', 'within_30', 'within_60', 'within_90', 'within_180', 'unknown_date'];
const subStyle = { margin: '0 0 6px', fontSize: '0.8rem', color: 'var(--neutral-500)' } as const;
const blockStyle = { marginTop: '16px', paddingTop: '12px', borderTop: '1px solid var(--divider)' } as const;
const entryStyle = { fontSize: '0.82rem', color: 'var(--neutral-700)', padding: '6px 0', borderBottom: '1px solid var(--neutral-100)' } as const;
const linkageStyle = { fontSize: '0.75rem', color: 'var(--neutral-500)' } as const;
const tdStyle = { padding: '8px 12px', fontSize: '0.85rem', verticalAlign: 'top' } as const;

const rowsLabel = (rows: Array<number | null>) =>
  rows.length ? rows.map((r) => (r == null ? '—' : String(r))).join(', ') : '—';
const idsLabel = (ids: number[]) => (ids.length ? ids.map((i) => `#${i}`).join(', ') : '—');
const signedUsd = (n: number) => `${n < 0 ? '−' : '+'}${formatUsd(Math.abs(n))}`;
const sideUsd = (v: number | null) => (v == null ? 'not recorded' : formatUsd(v));

function AmountMove({ label, a }: { label: string; a: ComparisonAmountSide }) {
  return (
    <span>
      {label} {sideUsd(a.from)} → {sideUsd(a.to)}
      {a.delta != null ? ` (${signedUsd(a.delta)})` : ' (no delta — a side is not recorded)'}
    </span>
  );
}

function OppEntry({ kind, o, importId }: { kind: 'added' | 'removed'; o: ComparisonOpportunity; importId: number }) {
  return (
    <li data-testid={`customer-pipeline-comparison-${kind}-${o.opportunity_number}`} style={entryStyle}>
      <strong>{o.opportunity_name ?? '—'}</strong> ({o.opportunity_number}) · stage {o.stage_raw ?? 'not recorded'}
      {' '}· close {formatDate(o.close_date)} · ACV {formatAmountWithCoverage(o.est_acv_usd, null)} · TCV {formatAmountWithCoverage(o.est_tcv_usd, null)}
      {o.reported_renewal && <span style={{ marginLeft: '6px', color: 'var(--brand-700)' }}>reported renewal</span>}
      <div style={linkageStyle}>rows {rowsLabel(o.line_source_rows)} · import #{importId}</div>
    </li>
  );
}

function ComparisonBlock({ c }: { c: PipelineComparison }) {
  // The honesty notes come from the backend verbatim (contract S0) — the
  // removed-note is located data-driven, never hard-coded in the UI.
  const removedNote = c.notes.find((n) => n.toLowerCase().startsWith('observed-removed')) ?? null;
  const noChanges = c.added.length === 0 && c.observed_removed.length === 0 && c.stage_changes.length === 0
    && c.close_date_changes.length === 0 && c.name_changes.length === 0 && c.amount_changes.length === 0;
  const f = c.from.import_id;
  const t = c.to.import_id;
  const linkage = (from: number[], to: number[]) => (
    <div style={linkageStyle}>lines {idsLabel(from)} · import #{f} → lines {idsLabel(to)} · import #{t}</div>
  );
  const section = (kind: string, title: string, n: number, children: React.ReactNode) => (
    <div data-testid={`customer-pipeline-comparison-${kind}`} style={{ marginTop: '10px' }}>
      <div style={{ fontSize: '0.85rem', fontWeight: 600, color: 'var(--neutral-700)' }}>{title} ({n})</div>
      {children}
    </div>
  );
  const list = (items: React.ReactNode[]) => (items.length ? <ul style={{ margin: '4px 0 0', padding: 0, listStyle: 'none' }}>{items}</ul> : null);
  const unidentifiedAny = c.unidentified.from > 0 || c.unidentified.to > 0;
  return (
    <div data-testid="customer-pipeline-comparison" style={blockStyle}>
      <div style={{ fontSize: '0.9rem', fontWeight: 600, color: 'var(--neutral-700)' }}>
        Changes from import #{f} ({formatDate(c.from.imported_at)}) to import #{t} ({formatDate(c.to.imported_at)})
      </div>
      <p style={{ ...subStyle, marginTop: '4px' }}>
        Opportunities {c.opportunity_count.from} → {c.opportunity_count.to} · dates are import times, not business effective dates
      </p>
      {noChanges ? (
        <p data-testid="customer-pipeline-comparison-none" style={{ margin: '4px 0 0', fontSize: '0.85rem', color: 'var(--neutral-700)' }}>
          No changes between these snapshots
        </p>
      ) : (
        <>
          {c.added.length > 0 && section('added', 'Added', c.added.length, list(c.added.map((o) => <OppEntry key={o.opportunity_number} kind="added" o={o} importId={t} />)))}
          {c.observed_removed.length > 0 && section('removed', 'Observed-removed', c.observed_removed.length, (
            <>
              {removedNote && <p data-testid="customer-pipeline-comparison-removed-note" style={{ ...subStyle, margin: '2px 0 0' }}>{removedNote}</p>}
              {list(c.observed_removed.map((o) => <OppEntry key={o.opportunity_number} kind="removed" o={o} importId={f} />))}
            </>
          ))}
          {c.stage_changes.length > 0 && section('stage', 'Stage changes', c.stage_changes.length, list(c.stage_changes.map((e) => (
            <li key={e.opportunity_number} data-testid={`customer-pipeline-comparison-stage-${e.opportunity_number}`} style={entryStyle}>
              {e.opportunity_number}: {e.from_stage ?? 'not recorded'} ({e.from_class}) → {e.to_stage ?? 'not recorded'} ({e.to_class})
              {linkage(e.line_ids_from, e.line_ids_to)}
            </li>
          ))))}
          {c.close_date_changes.length > 0 && section('close', 'Close-date slips', c.close_date_changes.length, list(c.close_date_changes.map((e) => (
            <li key={e.opportunity_number} data-testid={`customer-pipeline-comparison-close-${e.opportunity_number}`} style={entryStyle}>
              {e.opportunity_number}: {formatDate(e.from_close_date)} → {formatDate(e.to_close_date)}
              {' '}({e.slip_days >= 0 ? `slipped ${e.slip_days} ${e.slip_days === 1 ? 'day' : 'days'} later` : `moved ${Math.abs(e.slip_days)} ${Math.abs(e.slip_days) === 1 ? 'day' : 'days'} earlier`})
              {linkage(e.line_ids_from, e.line_ids_to)}
            </li>
          ))))}
          {c.name_changes.length > 0 && section('name', 'Name changes', c.name_changes.length, list(c.name_changes.map((e) => (
            <li key={e.opportunity_number} data-testid={`customer-pipeline-comparison-name-${e.opportunity_number}`} style={entryStyle}>
              {e.opportunity_number}: “{e.name_from ?? '—'}” → “{e.name_to ?? '—'}”
              {linkage(e.line_ids_from, e.line_ids_to)}
            </li>
          ))))}
          {c.amount_changes.length > 0 && section('amount', 'ACV/TCV movement', c.amount_changes.length, list(c.amount_changes.map((e) => (
            <li key={e.opportunity_number} data-testid={`customer-pipeline-comparison-amount-${e.opportunity_number}`} style={entryStyle}>
              {e.opportunity_number}: <AmountMove label="ACV" a={e.acv} /> · <AmountMove label="TCV" a={e.tcv} />
              {linkage(e.line_ids_from, e.line_ids_to)}
            </li>
          ))))}
          {c.unchanged.length > 0 && section('unchanged', 'Unchanged', c.unchanged.length, (
            <details style={{ fontSize: '0.8rem', color: 'var(--neutral-500)' }}>
              <summary style={{ cursor: 'pointer' }}>Show opportunity numbers</summary>
              {c.unchanged.map((n, i) => (
                <span key={n} data-testid={`customer-pipeline-comparison-unchanged-${n}`}>{i > 0 && ', '}{n}</span>
              ))}
            </details>
          ))}
          {c.ambiguity.length > 0 && section('ambiguity', 'Ambiguity', c.ambiguity.length, (
            <ul style={{ margin: '4px 0 0', padding: 0, listStyle: 'none', color: 'var(--status-warning)' }}>
              {c.ambiguity.map((a) => (
                <li key={a.opportunity_number} data-testid={`customer-pipeline-comparison-ambiguity-${a.opportunity_number}`} style={entryStyle}>
                  {a.opportunity_number} — import #{f}: {a.from_conflicts.length ? a.from_conflicts.join('; ') : 'no conflicts'}
                  {' '}· import #{t}: {a.to_conflicts.length ? a.to_conflicts.join('; ') : 'no conflicts'}
                  <div style={linkageStyle}>{a.note}</div>
                </li>
              ))}
            </ul>
          ))}
        </>
      )}
      {unidentifiedAny && (
        <p data-testid="customer-pipeline-comparison-unidentified" style={{ ...subStyle, marginTop: '10px' }}>
          Unidentified lines (no opportunity number — never matched): import #{f}: {c.unidentified.from} · import #{t}: {c.unidentified.to}
        </p>
      )}
      {c.notes.filter((n) => n !== removedNote).map((n) => (
        <p key={n} style={{ ...subStyle, marginTop: '6px' }}>{n}</p>
      ))}
    </div>
  );
}

function RenewalsBlock({ r, bucket, setBucket, customerId, allowDeals, onOpenDeal, sources }: { customerId: number; allowDeals: boolean; onOpenDeal?: (id: number) => void; sources: Record<string, number> } & { bucket: string; setBucket: (bucket: string) => void; r: RenewalAttention }) {
  if (!r.snapshot) return null; // no_data: the panel's own empty state already says so
  const c = r.counts;
  const attention = c.overdue + c.within_30 + c.within_60 + c.within_90 + c.within_180 + c.unknown_date > 0;
  const beyond = r.buckets.beyond_180_count;
  const importId = r.snapshot.import_id;
  const cards = RENEWAL_BUCKET_ORDER.filter(key => bucket === 'all' || (bucket === 'due' ? ['overdue', 'within_30', 'within_60', 'within_90', 'within_180'].includes(key) : key === bucket)).flatMap((k) => r.buckets[k] ?? []);
  return (
    <div data-testid="customer-pipeline-renewals" style={blockStyle}>
      <label>Renewal window <select aria-label="Renewal window" value={bucket} onChange={event => setBucket(event.target.value)}>
        <option value="all">All recorded renewals</option><option value="due">Overdue or due within 180 days</option>{RENEWAL_BUCKET_ORDER.map(key => <option key={key} value={key}>{key.replace(/_/g, ' ')}</option>)}
      </select></label>
      <div style={{ fontSize: '0.9rem', fontWeight: 600, color: 'var(--neutral-700)' }}>Renewals — vendor-reported</div>
      {attention && (
        <div data-testid="customer-pipeline-renewal-chips" style={{ display: 'flex', gap: '8px', flexWrap: 'wrap', margin: '8px 0', fontSize: '0.8rem' }}>
          {RENEWAL_BUCKET_ORDER.map((k) => (
            <span key={k} data-testid={`customer-pipeline-renewal-chip-${k}`} style={{ padding: '2px 10px', borderRadius: '999px', background: 'var(--neutral-50)', border: '1px solid var(--divider)', color: k === 'overdue' && c[k] > 0 ? 'var(--status-negative)' : 'var(--neutral-700)' }}>
              {RENEWAL_BUCKET_LABELS[k]} <strong>{c[k]}</strong>
            </span>
          ))}
          {beyond > 0 && (
            <span data-testid="customer-pipeline-renewal-chip-beyond_180" style={{ padding: '2px 10px', borderRadius: '999px', background: 'var(--neutral-50)', border: '1px solid var(--divider)', color: 'var(--neutral-700)' }}>
              Beyond 180 days <strong>{beyond}</strong>
            </span>
          )}
        </div>
      )}
      {!attention && beyond === 0 && (
        <p data-testid="customer-pipeline-renewals-none" style={{ ...subStyle, marginTop: '6px' }}>
          No current contract end dates recorded in the latest snapshot
        </p>
      )}
      {bucket !== 'all' && cards.length === 0 && <p>No renewals match this window. <button onClick={() => setBucket('all')}>Show all renewals</button></p>}
      {cards.map((card) => (
        <div key={card.opportunity_number} data-testid={`customer-pipeline-renewal-card-${card.opportunity_number}`} style={entryStyle}>
          <div>
            <DealPromotion key={`${customerId}-${card.opportunity_number}`} customerId={customerId} allowed={allowDeals} linkedDealId={sources[`vendor:${card.opportunity_number}`]} onOpen={onOpenDeal} vendor={{ import_id: r.snapshot?.import_id ?? 0, opportunity_number: card.opportunity_number }} />
            <strong>{card.opportunity_name ?? '—'}</strong> ({card.opportunity_number})
            {card.reported_renewal && <span data-testid={`customer-pipeline-renewal-reported-${card.opportunity_number}`} style={{ marginLeft: '6px', color: 'var(--brand-700)' }}>reported renewal</span>}
          </div>
          <div>
            {card.renewal_date
              ? <>Current contract end {formatDate(card.renewal_date)} · {formatDaysUntil(card.days)}</>
              : <>Current contract end date not recorded (renewal reported by the source)</>}
            {' '}· {card.lines} {card.lines === 1 ? 'line' : 'lines'}
          </div>
          <div>
            Est. ACV {formatRenewalExposure(card.est_acv)} · Est. TCV {formatRenewalExposure(card.est_tcv)}
          </div>
          {(card.conflicting_end_dates ?? []).length > 0 && (
            <div data-testid={`customer-pipeline-renewal-conflict-${card.opportunity_number}`} style={{ color: 'var(--status-warning)', fontSize: '0.8rem' }}>
              Lines disagree on the end date: {(card.conflicting_end_dates ?? []).map((d) => formatDate(d)).join(', ')} (earliest shown)
            </div>
          )}
          {card.original_contract_end && (
            <div style={linkageStyle}>Original contract end {formatDate(card.original_contract_end)} (historical)</div>
          )}
          <div style={linkageStyle}>rows {rowsLabel(card.line_source_rows)} · import #{importId}</div>
        </div>
      ))}
      {beyond > 0 && (
        <p data-testid="customer-pipeline-renewal-beyond" style={{ ...subStyle, marginTop: '8px' }}>
          {beyond} more end beyond 180 days
        </p>
      )}
    </div>
  );
}

export function CustomerPipeline({ customerId = 0, customerName, allowDeals = false, onOpenDeal }: CustomerPipelineProps) {
  const sources = useDealSources(customerId);
  const [filters, updateFilters] = useAccountListState(customerId, 'renewal', { bucket: 'all' });
  const [data, setData] = useState<CustomerPipelineData | null>(null);
  const [error, setError] = useState<string | null>(null);
  // A different account never inherits another account's comparison choice.
  const [compareChoice, setCompareChoice] = useState<{ customer: string; id: number | null }>({ customer: customerName, id: null });
  const compareWith = compareChoice.customer === customerName ? compareChoice.id : null;
  const setCompareWith = (id: number | null) => setCompareChoice({ customer: customerName, id });

  useEffect(() => {
    let cancelled = false;
    setError(null);
    // Keep the current view while only the comparison choice changes.
    if (compareWith == null) setData(null);
    (compareWith == null ? api.getCustomerPipeline(customerName) : api.getCustomerPipeline(customerName, compareWith))
      .then((d) => { if (!cancelled) setData(d); })
      .catch((e: unknown) => {
        if (!cancelled) setError(e instanceof Error ? e.message : 'Failed to load partner pipeline');
      });
    return () => { cancelled = true; };
  }, [customerName, compareWith]);

  const history = data?.history ?? [];
  const selectedSnapshot = history.find((h) => h.selected);
  const priorSnapshots = history.filter((h) => !h.selected);
  const rows = data?.rows ?? [];
  const totals = data?.totals;
  const summary = data?.summary;
  const unidentified = summary?.grain.unidentified_lines ?? 0;
  const ambiguous = summary?.grain.ambiguous_opportunities ?? [];
  const acvLines = summary ? { included: summary.amounts.acv.lines_included, excluded: summary.amounts.acv.lines_excluded } : undefined;
  const tcvLines = summary ? { included: summary.amounts.tcv.lines_included, excluded: summary.amounts.tcv.lines_excluded } : undefined;

  return (
    <section style={cardStyle} data-testid="customer-pipeline" aria-label="Partner pipeline">
      <div style={{ padding: '16px 20px', borderBottom: '1px solid var(--divider)' }}>
        <h3 style={{ margin: 0, fontSize: '1rem', color: 'var(--neutral-700)' }}>Partner Pipeline</h3>
      </div>
      <div style={{ padding: '16px 20px' }}>
        {error && (
          <div role="alert" data-testid="customer-pipeline-error" style={{ color: 'var(--status-negative)', fontSize: '0.9rem' }}>{error}</div>
        )}
        {!error && !data && (
          <div role="status" style={{ color: 'var(--neutral-500)', fontSize: '0.9rem' }}>Loading partner pipeline…</div>
        )}
        {data && rows.length === 0 && (
          <p data-testid="customer-pipeline-empty" style={{ margin: 0, color: 'var(--neutral-500)', fontSize: '0.9rem' }}>
            No partner pipeline data imported for this account
          </p>
        )}
        {data && totals && rows.length > 0 && (
          <>
            <div data-testid="customer-pipeline-totals" style={{ display: 'flex', gap: '20px', flexWrap: 'wrap', marginBottom: '12px', fontSize: '0.85rem', color: 'var(--neutral-700)' }}>
              <span data-testid="customer-pipeline-grain">
                <strong>{totals.deal_count}</strong> {totals.deal_count === 1 ? 'opportunity' : 'opportunities'} · <strong>{totals.line_count ?? rows.length}</strong> {(totals.line_count ?? rows.length) === 1 ? 'line' : 'lines'}
                {unidentified > 0 && ` (${unidentified} unidentified ${unidentified === 1 ? 'line' : 'lines'})`}
              </span>
              <span data-testid="customer-pipeline-stages">
                <strong>{totals.open_deals}</strong> open
                {(totals.unknown_deals ?? 0) > 0 && <> / <strong>{totals.unknown_deals}</strong> unknown stage</>}
              </span>
              <span><strong>{totals.growth}</strong> growth / <strong>{totals.risk}</strong> risk</span>
              <span data-testid="customer-pipeline-acv">Est. ACV <strong>{formatAmountWithCoverage(totals.est_acv_total, totals.amount_coverage?.acv, acvLines)}</strong></span>
              <span data-testid="customer-pipeline-tcv">Est. TCV <strong>{formatAmountWithCoverage(totals.est_tcv_total, totals.amount_coverage?.tcv, tcvLines)}</strong></span>
            </div>
            {(summary?.currency_basis || summary?.currency_note) && (
              <p data-testid="customer-pipeline-coverage" style={{ margin: '0 0 12px', fontSize: '0.8rem', color: 'var(--neutral-500)' }}>
                {summary.currency_basis}
                {summary.currency_note && (
                  <span data-testid="customer-pipeline-currency-note"> · {summary.currency_note}</span>
                )}
              </p>
            )}
            {ambiguous.length > 0 && (
              <div data-testid="customer-pipeline-ambiguity" style={{ margin: '0 0 12px', fontSize: '0.8rem', color: 'var(--status-warning)' }}>
                <strong>{ambiguous.length}</strong> {ambiguous.length === 1 ? 'opportunity has' : 'opportunities have'} conflicting source values (stage shown as unknown):
                <ul style={{ margin: '4px 0 0', paddingLeft: '20px' }}>
                  {ambiguous.map((a) => (
                    <li key={a.opportunity_number} data-testid={`customer-pipeline-ambiguous-${a.opportunity_number}`}>
                      {a.opportunity_number} — {a.conflicts.join('; ')}
                    </li>
                  ))}
                </ul>
              </div>
            )}
            {(data.technologies ?? []).length > 0 && (
              <p data-testid="customer-pipeline-technologies" style={{ margin: '0 0 12px', fontSize: '0.85rem', color: 'var(--neutral-700)' }}>
                <strong>{data.technologies.length}</strong> technology record{data.technologies.length === 1 ? '' : 's'} from renewal: {data.technologies.join(', ')}
              </p>
            )}
            <div style={{ overflowX: 'auto' }}>
              <table style={{ width: '100%', borderCollapse: 'collapse' }}>
                <thead>
                  <tr style={{ borderBottom: '2px solid var(--divider)' }}>
                    <th style={thStyle}>Opportunity</th>
                    <th style={thStyle}>Stage</th>
                    <th style={thStyle}>Product</th>
                    <th style={{ ...thStyle, textAlign: 'right' }}>Est. ACV</th>
                    <th style={{ ...thStyle, textAlign: 'right' }}>Est. TCV</th>
                    <th style={thStyle}>Close Date</th>
                    <th style={thStyle}>Flag</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((r) => (
                    <tr key={r.id} data-testid={`customer-pipeline-row-${r.id}`} style={{ borderBottom: '1px solid var(--neutral-100)' }}>
                      <td style={tdStyle}>{r.opportunity_name ?? '—'}</td>
                      <td style={tdStyle}>{r.opp_stage ?? '—'}</td>
                      <td style={tdStyle}>{r.product_offering_group ?? '—'}</td>
                      <td style={{ ...tdStyle, textAlign: 'right' }}>{formatUsd(r.est_acv_usd)}</td>
                      <td style={{ ...tdStyle, textAlign: 'right' }}>{formatUsd(r.est_tcv_usd)}</td>
                      <td style={tdStyle}>{formatDate(r.close_date)}</td>
                      <td style={tdStyle}>{r.growth_risk_flag ?? '—'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <p data-testid="customer-pipeline-source" style={{ margin: '10px 0 0', fontSize: '0.75rem', color: 'var(--neutral-500)' }}>
              Source: {data.source_file ?? 'unknown file'} · imported {formatDate(data.imported_at)}
            </p>
            {history.length > 1 && (
              <div data-testid="customer-pipeline-history" style={{ margin: '8px 0 0', fontSize: '0.8rem', color: 'var(--neutral-700)', display: 'flex', gap: '8px', flexWrap: 'wrap', alignItems: 'center' }}>
                {selectedSnapshot && (
                  <span>
                    Comparing latest: import #{selectedSnapshot.import_id} · {selectedSnapshot.source_file ?? 'unknown file'} · imported {formatDate(selectedSnapshot.imported_at)}
                  </span>
                )}
                <select
                  data-testid="customer-pipeline-compare-select"
                  aria-label="Compare with a prior snapshot"
                  value={compareWith ?? ''}
                  onChange={(e) => setCompareWith(e.target.value === '' ? null : Number(e.target.value))}
                >
                  <option value="">Compare with a prior snapshot…</option>
                  {priorSnapshots.map((h) => (
                    <option key={h.import_id} value={h.import_id}>
                      #{h.import_id} · {h.source_file ?? 'unknown file'} · {formatDate(h.imported_at)} · {h.opportunity_count} opp / {h.line_count} lines
                    </option>
                  ))}
                </select>
                {compareWith != null && (
                  <button
                    type="button"
                    data-testid="customer-pipeline-compare-reset"
                    onClick={() => setCompareWith(null)}
                    style={{ background: 'none', border: 'none', padding: 0, margin: 0, color: 'var(--brand-700)', cursor: 'pointer', textDecoration: 'underline', fontSize: '0.8rem' }}
                  >
                    Showing changes vs import #{compareWith} — reset
                  </button>
                )}
              </div>
            )}
            {data.comparison && <ComparisonBlock c={data.comparison} />}
            <details><summary>Vendor opportunity evidence</summary>
              {[...new Map(rows.filter(row => row.opportunity_number).map(row => [row.opportunity_number!.trim(), row])).values()].map(row => <article key={row.opportunity_number} className="crm-surface">
                <strong>{row.opportunity_name ?? row.opportunity_number}</strong>
                <p>Vendor opportunity {row.opportunity_number} · import #{data.import_id}</p>
                <DealPromotion key={`${customerId}-${row.opportunity_number}`} customerId={customerId} allowed={allowDeals} linkedDealId={sources[`vendor:${row.opportunity_number?.trim()}`]} onOpen={onOpenDeal} vendor={{ import_id: data.import_id!, opportunity_number: row.opportunity_number! }} />
              </article>)}
            </details>
            {data.renewals && <RenewalsBlock sources={sources} customerId={customerId} allowDeals={allowDeals} onOpenDeal={onOpenDeal} r={data.renewals} bucket={filters.bucket} setBucket={bucket => updateFilters({ bucket })} />}
          </>
        )}
      </div>
    </section>
  );
}

export default CustomerPipeline;
