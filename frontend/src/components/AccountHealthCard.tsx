import { SectionIcon } from './SectionIcon';
/**
 * Account health components (Overview surface).
 *
 * Six independent, labelled components from GET /api/customers/{id}/health/:
 * Engagement, Renewals, Buying coverage, Tasks, End-of-support, Data freshness.
 * Deliberately NO composite score, traffic-light rollup or single "health"
 * number. Every backend `basis` string is rendered verbatim; money is
 * null-honest (formatPipelineAmount — never a fabricated $0); an EOL source is
 * never invented ("not recorded" when absent). Missing/null components render
 * their honest empty state instead of crashing.
 */
import { useCallback, useEffect, useRef, useState } from 'react';
import type { CSSProperties, ReactNode } from 'react';
import { api } from '../lib/api';
import { formatPipelineAmount } from '../lib/accountImpact';
import { RENEWAL_BUCKET_LABELS, formatDate } from '../lib/pipelineFormat';
import { BUYING_ROLE_LABELS } from '../types/contact';
import type { AccountHealthResponse, HealthDataFreshness } from '../types/accountHealth';

export const EOL_ITEM_CAP = 5;

interface Props {
  customerId: number;
  onNavigate?: (area: string) => void;
}

/** Strip sub-second precision from an ISO timestamp (keeps the zone suffix). */
export function stripSubSecond(value: string): string {
  return value.replace(/(T\d{2}:\d{2}:\d{2})\.\d+/, '$1');
}

function displayTimestamp(value: string): string {
  if (/^\d{4}-\d{2}-\d{2}$/.test(value)) return formatDate(value);
  if (!/(Z|[+-]\d{2}:?\d{2})$/i.test(value)) return `${value.replace('T', ' ')} (timezone not recorded)`;
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : `${date.toLocaleString(undefined, { timeZone: 'UTC', dateStyle: 'medium', timeStyle: 'short' })} UTC`;
}

export function renewalBucketLabel(key: string): string {
  return (RENEWAL_BUCKET_LABELS as Record<string, string>)[key] ?? key;
}

export function buyingRoleLabel(key: string): string {
  return (BUYING_ROLE_LABELS as Record<string, string>)[key] ?? key;
}

const FRESHNESS_SOURCES: Array<[keyof HealthDataFreshness, string]> = [
  ['pipeline_import', 'Pipeline import'],
  ['rep_import', 'Rep intelligence'],
  ['rvtools_import', 'RVTools'],
  ['latest_note', 'Latest note'],
  ['latest_activity', 'Latest activity'],
];

const muted: CSSProperties = { fontSize: '0.8rem', color: 'var(--neutral-500)' };
const line: CSSProperties = { fontSize: '0.85rem', color: 'var(--neutral-700)' };
const chip: CSSProperties = { fontSize: '0.72rem', color: 'var(--neutral-600)', background: 'var(--neutral-100)', borderRadius: '10px', padding: '2px 8px' };
const block: CSSProperties = {
  display: 'flex', flexDirection: 'column', gap: '4px', minWidth: 0, padding: '10px 12px',
  border: '1px solid var(--divider)', borderRadius: 'var(--radius)', background: 'var(--neutral-0)', overflowWrap: 'anywhere',
};

function Block({ id, title, children }: { id: string; title: string; children: ReactNode }) {
  return (
    <section data-testid={`account-health-${id}`} aria-label={title} style={block}>
      <h4 style={{ margin: 0, fontSize: '0.9rem', color: 'var(--neutral-700)' }}>{title}</h4>
      {children}
    </section>
  );
}

function Basis({ id, text }: { id: string; text: string | null | undefined }) {
  if (!text) return null;
  return <div data-testid={`account-health-${id}-basis`} style={muted}>{text}</div>;
}

const n = (v: number | null | undefined): number => (typeof v === 'number' ? v : 0);
const countLabel = (v: number | null | undefined): string | number => typeof v === 'number' ? v : 'unavailable';

export function AccountHealthCard({ customerId, onNavigate }: Props) {
  const [data, setData] = useState<AccountHealthResponse | null>(null);
  const [failed, setFailed] = useState(false);
  const seq = useRef(0);

  const load = useCallback(() => {
    const mine = ++seq.current;
    setData(null);
    setFailed(false);
    Promise.resolve()
      .then(() => api.getCustomerHealth(customerId))
      .then((r) => { if (mine === seq.current) setData(r); })
      .catch(() => { if (mine === seq.current) setFailed(true); });
  }, [customerId]);

  useEffect(() => {
    load();
    return () => { seq.current += 1; };
  }, [load]);

  const currentData = data?.customer_id === customerId ? data : null;
  const c = currentData?.components;
  const eng = c?.engagement ?? null;
  const ren = c?.renewals ?? null;
  const buy = c?.buying_coverage ?? null;
  const tasks = c?.tasks ?? null;
  const eol = c?.eol ?? null;
  const fresh = c?.data_freshness ?? null;

  const renderEngagement = () => {
    const last = eng?.last_contacted ?? null;
    const days = eng?.days_since;
    const text = eng?.last_contacted === undefined ? 'Interaction data unavailable' : last
      ? `Last meaningful interaction ${formatDate(last)}${days != null ? ` (${days} days ago)` : ''}`
      : 'No meaningful interaction recorded';
    return (
      <Block id="engagement" title="Engagement">
        <div data-testid="account-health-engagement-line" style={line}>{text}</div>
        <Basis id="engagement" text={eng?.basis} />
    </Block>
    );
  };

  const renderRenewals = () => {
    const counts = ren?.counts ?? {};
    const hasSnapshot = ren?.snapshot != null;
    return (
      <Block id="renewals" title="Renewals">
        {ren?.snapshot === undefined ? <div style={line}>Pipeline data unavailable.</div> : hasSnapshot ? (
          <div data-testid="account-health-renewals-counts" style={{ display: 'flex', gap: '6px', flexWrap: 'wrap' }}>
            {Object.entries(counts).map(([key, count]) => (
              <span key={key} data-testid={`account-health-renewals-count-${key}`} style={chip}>
                {renewalBucketLabel(key)}: {count}
              </span>
            ))}
          </div>
        ) : (
          <div data-testid="account-health-renewals-empty" style={line}>No pipeline data recorded.</div>
        )}
        {ren?.counts == null && hasSnapshot && <div style={muted}>Renewal counts unavailable.</div>}
        <div data-testid="account-health-renewals-exposure" style={line}>
          {!ren?.exposure ? 'Exposure unavailable' : ren.exposure.coverage === 'no_data' ? 'Not recorded' : <>
            ACV {formatPipelineAmount(ren?.exposure?.acv ?? null)} · TCV {formatPipelineAmount(ren?.exposure?.tcv ?? null)}
            {ren?.exposure?.coverage === 'partial' && <span> · Partial sum — unknown amounts excluded</span>}
          </>}
        </div>
        <Basis id="renewals" text={ren?.basis} />
        {onNavigate && <button type="button" onClick={() => onNavigate('renewals-due')}>Review renewals</button>}
    </Block>
    );
  };

  const renderBuying = () => {
    const roles = Object.entries(buy?.roles ?? {});
    const gaps = buy?.gaps ?? [];
    return (
      <Block id="buying" title="Buying coverage">
        <div data-testid="account-health-buying-contacts" style={line}>{countLabel(buy?.contacts_recorded)} contacts</div>
        {buy?.roles == null && <div style={muted}>Role coverage unavailable.</div>}
        {buy?.gaps == null && <div style={muted}>Coverage gaps unavailable.</div>}
        {roles.length > 0 && (
          <div data-testid="account-health-buying-roles" style={{ display: 'flex', gap: '6px', flexWrap: 'wrap' }}>
            {roles.map(([key, count]) => (
              <span key={key} data-testid={`account-health-buying-role-${key}`} style={chip}>
                {buyingRoleLabel(key)}: {count}
              </span>
            ))}
          </div>
        )}
        {gaps.map((g, i) => (
          <div key={i} data-testid="account-health-buying-gap" style={muted}>{g}</div>
        ))}
        {onNavigate && <button type="button" onClick={() => onNavigate('buying-gaps')}>Review buying contacts</button>}
    </Block>
    );
  };

  const renderTasks = () => (
    <Block id="tasks" title="Tasks">
      <div data-testid="account-health-tasks-line" style={line}>
        {countLabel(tasks?.open)} open · {countLabel(tasks?.in_progress)} in progress · {countLabel(tasks?.overdue)} overdue
      </div>
      <Basis id="tasks" text={tasks?.basis} />
      {onNavigate && (tasks?.overdue ?? 0) > 0 && <button type="button" onClick={() => onNavigate('tasks-overdue')}>View overdue follow-ups</button>}
    </Block>
  );

  const renderEol = () => {
    const count = n(eol?.dated_count);
    const items = (eol?.items ?? []).slice(0, EOL_ITEM_CAP);
    return (
      <Block id="eol" title="End-of-support">
        {eol?.items == null && <div style={muted}>Evidence list unavailable.</div>}
        {eol?.dated_count == null ? <div style={line}>Count unavailable.</div> : count === 0 ? (
          <div data-testid="account-health-eol-empty" style={line}>No dated end-of-support records.</div>
        ) : (
          <>
            <div data-testid="account-health-eol-count" style={line}>
              {count} dated end-of-support record{count === 1 ? '' : 's'}:
            </div>
            {items.map((it) => (
              <div key={it.id} data-testid={`account-health-eol-item-${it.id}`} style={{ ...line, display: 'flex', gap: '8px', flexWrap: 'wrap' }}>
                <span style={{ fontWeight: 600, color: 'var(--ink)' }}>
                  {it.name}{it.vendor ? ` (${it.vendor})` : ''}
                </span>
                <span>{it.end_of_support_date ? formatDate(it.end_of_support_date) : 'date not recorded'}</span>
                <span style={muted}>source: {it.eol_source || 'not recorded'}</span>
                {it.business_criticality && <span style={chip}>{it.business_criticality}</span>}
              </div>
            ))}
          </>
        )}
    </Block>
    );
  };

  const renderFreshness = () => (
    <Block id="freshness" title="Data freshness">
      {FRESHNESS_SOURCES.map(([key, label]) => {
        const v = fresh?.[key] ?? null;
        return (
          <div key={key} data-testid={`account-health-freshness-${key}`} style={line}>
            {label}: {v ? <><span>{displayTimestamp(v)}</span><details><summary>Exact timestamp</summary>{v}</details></> : fresh?.[key] === undefined ? 'unavailable' : 'not recorded'}
          </div>
        );
      })}
    </Block>
  );

  const meta = [currentData?.calc_version, currentData?.as_of ? `as of ${stripSubSecond(currentData.as_of)}` : null]
    .filter(Boolean)
    .join(' · ');

  return (
    <div data-testid="account-health" style={{ background: 'var(--neutral-0)', borderRadius: 'var(--radius)', border: '1px solid var(--divider)', padding: '16px', minWidth: 0 }}>
      <h3 style={{ margin: '0 0 10px', fontSize: '1.05rem', color: 'var(--neutral-700)' }}><SectionIcon name="📊" /> Account health</h3>
      {failed ? (
        <div role="alert" data-testid="account-health-error" style={{ ...muted, color: 'var(--status-negative)', display: 'flex', gap: '8px', alignItems: 'center', flexWrap: 'wrap' }}>
          Account health unavailable. Try again.
          <button type="button" onClick={load}>Retry</button>
        </div>
      ) : currentData === null && data !== null ? (
        <div role="alert">Account health unavailable. <button type="button" onClick={load}>Retry</button></div>
      ) : currentData === null ? (
        <div style={muted}>Loading account health…</div>
      ) : (
        <>
          {meta && <details style={{ ...muted, marginBottom: '10px' }}><summary>Health calculation details</summary><div data-testid="account-health-meta">{meta}</div></details>}
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(min(240px, 100%), 1fr))', gap: '10px' }}>
            {tasks ? renderTasks() : <Block id="tasks" title="Tasks">Unavailable. <button type="button" onClick={load}>Retry</button></Block>}
            {ren ? renderRenewals() : <Block id="renewals" title="Renewals">Unavailable. <button type="button" onClick={load}>Retry</button></Block>}
            {eng ? renderEngagement() : <Block id="engagement" title="Engagement">Unavailable. <button type="button" onClick={load}>Retry</button></Block>}
            {buy ? renderBuying() : <Block id="buying" title="Buying coverage">Unavailable. <button type="button" onClick={load}>Retry</button></Block>}
            {eol ? renderEol() : <Block id="eol" title="End-of-support">Unavailable. <button type="button" onClick={load}>Retry</button></Block>}
            {fresh ? renderFreshness() : <Block id="freshness" title="Data freshness">Unavailable. <button type="button" onClick={load}>Retry</button></Block>}
          </div>
        </>
      )}
    </div>
  );
}

export default AccountHealthCard;
