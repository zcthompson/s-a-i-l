import { SectionIcon } from './SectionIcon';
/**
 * CHANGELOG 0.1.0 U5 — Account Overview + actionable intelligence summaries.
 *
 * Deterministic, fed by the U1 account-workspace endpoint
 * (`getAccountWorkspace`) — the same data that powers the Opportunities
 * panel, so nothing is re-derived or fabricated client-side:
 *
 *  - `AccountOverview` (the executive Overview, directives 16-20, 39-40,
 *    54-55): balanced headline metrics (Business Impact is ONE card with
 *    savings + revenue as sub-metrics, directive 20 — not three equal
 *    cards), the Account Snapshot (who / what we know / what's
 *    happening), the four actionable intelligence summaries (directive
 *    22-26), and the small Priority Use Cases list (the dense working
 *    table stays one rail step away, directive 39-40).
 *  - `IntelligencePanels` (the dedicated Intelligence ▸ Summary view,
 *    directive 51): the four actionable summaries on their own.
 *
 * Provenance (directive 21): the response's `method` is exposed through
 * tooltips only — never an implementation-oriented "Derived —
 * deterministic aggregation" label in the main UX. Semantic colors
 * (directives 43-44): red = critical risk, amber = attention, green =
 * healthy, accent = primary.
 */
import { AccountHealthCard } from './AccountHealthCard';
import { useEffect, useState } from 'react';
import { api } from '../lib/api';
import { AccountWorkspace } from '../types/sail';
import { SummaryCard } from './workspacePrimitives';

const PROVENANCE = 'Deterministic aggregation of customer records — not model output (method: deterministic_aggregation).';

function agoLabel(days: number | null): string {
  if (days == null) return '—';
  if (days === 0) return 'today';
  if (days === 1) return '1 day ago';
  return `${days} days ago`;
}

const VALUE_COLOR = {
  neutral: 'var(--neutral-700)',
  positive: 'var(--status-positive)',
  warning: 'var(--status-warning)',
  negative: 'var(--status-negative)',
} as const;

/** One "what is known / what needs attention" panel (directive 22-26). */
function IntelligencePanel({ title, lines, tone = 'neutral', onOpen }: {
  title: string;
  lines: Array<{ label: string; value: string; tone?: keyof typeof VALUE_COLOR }>;
  tone?: keyof typeof VALUE_COLOR;
  onOpen?: () => void;
}) {
  return (
    <section title={PROVENANCE} aria-label={title} style={{ background: 'var(--neutral-0)', borderRadius: 'var(--radius)', padding: '14px 16px', border: '1px solid var(--divider)', minWidth: 0 }}>
      <div style={{ fontSize: '0.8rem', fontWeight: 600, color: tone === 'negative' ? VALUE_COLOR.negative : 'var(--neutral-700)', marginBottom: '8px' }}>{title}</div>
      {lines.map((l) => (
        <div key={l.label} style={{ display: 'flex', justifyContent: 'space-between', gap: '8px', fontSize: '0.83rem', padding: '3px 0' }}>
          <span style={{ color: 'var(--neutral-500)' }}>{l.label}</span>
          <span style={{ fontWeight: 600, color: VALUE_COLOR[l.tone || 'neutral'], textAlign: 'right', overflowWrap: 'anywhere', minWidth: 0 }}>{l.value}</span>
        </div>
      ))}
      {onOpen && <button type="button" onClick={onOpen}>View {title}</button>}
    </section>
  );
}

/** The four actionable intelligence summaries as a pure function of the
 *  workspace data — shared by the Overview and the Intelligence ▸ Summary
 *  view (directive 22-26). */
function IntelligencePanelsContent({ ws, includeAssessment = true, onNavigate }: { ws: AccountWorkspace; includeAssessment?: boolean; onNavigate?: (area: string) => void }) {
  const { technology_landscape: tl, knowledge: kn, sales_activity: sa, assessment: asmt } = ws;
  return (
    <>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(min(240px, 100%), 1fr))', gap: '14px' }}>
        <IntelligencePanel
          title="Sales Activity"
          onOpen={onNavigate ? () => onNavigate('sales-notes') : undefined}
          tone={sa.notes_stale ? 'warning' : 'neutral'}
          lines={[
            { label: 'Sales notes', value: String(sa.total_notes) },
            { label: 'Latest sales note', value: sa.last_interaction ? agoLabel(sa.days_since_last_interaction) : '—', tone: sa.notes_stale ? 'warning' : 'neutral' },
            { label: 'Active observations', value: String(sa.active_observations.length) },
            ...(sa.recent.length > 0
              ? [{ label: 'Most recent', value: sa.recent[0].title, tone: 'neutral' as const }]
              : []),
          ]}
        />
        <IntelligencePanel
          title="Technology Landscape"
          tone={tl.at_risk_count > 0 ? 'negative' : 'neutral'}
          lines={[
            { label: 'Items', value: String(tl.total) },
            { label: 'Key vendors', value: tl.key_vendors.length > 0 ? tl.key_vendors.slice(0, 3).map((v) => v.key).join(', ') : '—' },
            { label: 'End-of-life', value: String(tl.eol_count), tone: tl.eol_count > 0 ? 'negative' : 'neutral' },
            { label: 'Unsupported', value: String(tl.unsupported_count), tone: tl.unsupported_count > 0 ? 'warning' : 'neutral' },
            { label: 'Critical at risk', value: String(tl.at_risk_count), tone: tl.at_risk_count > 0 ? 'negative' : 'neutral' },
            { label: 'Unverified', value: tl.unverified_pct != null ? `${tl.unverified_pct}%` : '—', tone: (tl.unverified_pct ?? 0) >= 30 ? 'warning' : 'neutral' },
          ]}
        />
        <IntelligencePanel
          title="Customer Knowledge"
          onOpen={onNavigate ? () => onNavigate('customer-knowledge') : undefined}
          tone={kn.unprocessed_count > 0 ? 'warning' : 'neutral'}
          lines={[
            { label: 'Sources', value: String(kn.total) },
            { label: 'Recently added (30d)', value: String(kn.recently_added_count) },
            { label: 'Latest upload', value: kn.latest_uploaded ? agoLabel(kn.days_since_latest) : '—' },
            { label: 'Awaiting processing', value: String(kn.unprocessed_count), tone: kn.unprocessed_count > 0 ? 'warning' : 'neutral' },
          ]}
        />
        {includeAssessment && <IntelligencePanel
          title="Assessment & Use Cases"
          lines={[
            { label: 'Use cases', value: `${asmt.total_count} total · ${asmt.unscored_count} unscored`, tone: asmt.unscored_count > 0 ? 'warning' : 'neutral' },
            { label: 'Average score', value: asmt.average_score != null ? asmt.average_score.toFixed(1) : '—' },
            ...(asmt.active_assessment
              ? [{ label: 'Active round', value: `${asmt.active_assessment.name} · ${asmt.active_assessment.progress_pct == null ? 'progress unavailable' : `${asmt.active_assessment.progress_pct}%`}`, tone: 'positive' as const }]
              : []),
            ...(asmt.top_use_cases.length > 0
              ? [{ label: 'Top use case', value: asmt.top_use_cases[0].title, tone: 'neutral' as const }]
              : []),
          ]}
        />}
      </div>
      <details style={{ marginTop: 12, fontSize: '0.82rem', color: 'var(--neutral-600)' }}><summary>About these summaries</summary>{PROVENANCE}</details>
      {tl.important_gaps.length > 0 && (
        <div style={{ marginTop: '12px', fontSize: '0.82rem', color: 'var(--neutral-600)' }}>
          <b style={{ color: 'var(--status-warning)' }}>Knowledge gaps:</b> {tl.important_gaps.join(' · ')}
        </div>
      )}
    </>
  );
}

interface OverviewProps {
  customerId: number;
  /** Drill-down targets are customer-area ids (e.g. 'use-cases',
   *  'business-impact') — the parent owns navigation. */
  onNavigate?: (target: string) => void;
  /** Caller role — the departments drill-down label mirrors
   *  DepartmentManager's canManage rule (auditor/none cannot manage). */
  userRole?: string;

}

export function AccountOverview({ customerId, onNavigate, userRole = 'member' }: OverviewProps) {
  const [ws, setWs] = useState<AccountWorkspace | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [retry, setRetry] = useState(0);
  // Same rule as DepartmentManager (userRole !== 'auditor' && !== 'none'):
  // read-only callers see an honest "View" affordance, not "Manage".
  const canManageDepartments = userRole !== 'auditor' && userRole !== 'none';

  useEffect(() => {
    let alive = true;
    setWs(null);
    setError(null);
    api
      .getAccountWorkspace(customerId)
      .then((w) => { if (alive) { if (!w || w.customer_id !== customerId) setError('Customer response unavailable'); else setWs(w); } })
      .catch((e: any) => { if (alive) setError(e?.message || 'Failed to load account overview'); });
    return () => { alive = false; }
  }, [customerId, retry]);

  const valid = ws && ws.customer_id === customerId && ws.headline?.business_impact && ws.technology_landscape && ws.account && ws.knowledge && ws.sales_activity && ws.assessment;
  return <div data-ui="account-overview">
    {valid ? <OverviewContent ws={ws} onNavigate={onNavigate} canManageDepartments={canManageDepartments} section="snapshot" /> :
      error || (ws && ws.customer_id === customerId) ? <div role="alert">Account overview unavailable. <button type="button" onClick={() => setRetry(value => value + 1)}>Retry overview</button></div> : <p role="status">Loading account overview…</p>}
    <CustomerActions onNavigate={onNavigate} />
    {valid && <OverviewContent ws={ws} onNavigate={onNavigate} canManageDepartments={canManageDepartments} section="metrics" />}
    <div style={{ marginBottom: 'var(--space-5)' }}><AccountHealthCard key={customerId} customerId={customerId} onNavigate={onNavigate} /></div>
    {valid && <OverviewContent ws={ws} onNavigate={onNavigate} canManageDepartments={canManageDepartments} section="intelligence" />}
  </div>;
}

function OverviewContent({ ws, onNavigate, canManageDepartments = true, section }: { ws: AccountWorkspace; onNavigate?: (target: string) => void; canManageDepartments?: boolean; section: "snapshot" | "metrics" | "intelligence" }) {
  const { headline, account, technology_landscape: tl, knowledge: kn, sales_activity: sa } = ws;
  const impact = headline.business_impact;


  // Directive 56 — partial empty state: when SOME sources are empty (a sparse
  // account), name exactly what's missing and give ONE obvious next action
  // instead of leaving a grid of bare zeros. (The fully-empty case below
  // keeps the larger EmptyState.)
  const missingSources: string[] = [];
  if (tl.total === 0) missingSources.push('technology inventory');
  if (sa.total_notes === 0) missingSources.push('sales notes');
  if (kn.total === 0) missingSources.push('knowledge sources');
  const partialSparse = missingSources.length > 0;

  return (
    <>
      {section === "snapshot" && <>{/* ── Account Snapshot (directives 16-18, 48) ─────────────────── */}
      <div style={{ background: 'var(--neutral-0)', borderRadius: 'var(--radius)', border: '1px solid var(--divider)', padding: 'var(--space-4) var(--space-5)', marginBottom: 'var(--space-5)' }}>
        <h3 style={{ margin: '0 0 12px 0', fontSize: '1rem', color: 'var(--neutral-700)' }}><SectionIcon name="🏢" /> Account Snapshot</h3>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(min(220px, 100%), 1fr))', gap: '14px', fontSize: '0.85rem' }}>
          <div>
            <div style={{ fontSize: '0.75rem', color: 'var(--neutral-500)', marginBottom: '3px' }}>Ownership</div>
            <div style={{ color: 'var(--neutral-700)' }}>
              {account.owner
                ? `Owner: ${account.owner.display_name || account.owner.username || '—'}`
                : 'No owner assigned'}
              <span style={{ color: 'var(--neutral-500)' }}> · {account.member_count} team member{account.member_count === 1 ? '' : 's'}</span>
            </div>
          </div>
          <div>
            <div style={{ fontSize: '0.75rem', color: 'var(--neutral-500)', marginBottom: '3px' }}>Departments</div>
            <div style={{ color: 'var(--neutral-700)' }}>
              {account.department_count > 0 ? `${account.department_count} active` : 'None recorded'}
              {onNavigate && account.department_count > 0 && (
                <button role="button" aria-label={canManageDepartments ? 'Manage departments' : 'View departments'}
                  onClick={() => onNavigate('departments')}
                  style={{ marginLeft: '8px', padding: 0, background: 'none', border: 'none', color: 'var(--brand-700)', fontWeight: 600, cursor: 'pointer', fontSize: '0.85rem' }}>
                  {canManageDepartments ? 'Manage' : 'View'}
                </button>
              )}
            </div>
          </div>
          <div>
            <div style={{ fontSize: '0.75rem', color: 'var(--neutral-500)', marginBottom: '3px' }}>Recent activity</div>
            <div style={{ color: sa.notes_stale ? 'var(--status-warning)' : 'var(--neutral-700)' }}>
              {sa.last_interaction
                ? `Latest sales note ${agoLabel(sa.days_since_last_interaction)}`
                : 'No sales notes recorded yet'}
            </div>
          </div>
        </div>
        {/* Intelligence completeness (directive 18) — what S-A-I-L knows about
            this account; zeros are honest unknowns, not omissions. */}
        <div style={{ marginTop: '14px', paddingTop: '12px', borderTop: '1px solid var(--divider)', fontSize: '0.8rem', color: 'var(--neutral-600)' }}>
          <span title={PROVENANCE}>
            Intelligence: <b>{tl.total} technologies</b> · <b>{sa.total_notes} sales notes</b> · <b>{kn.total} knowledge sources</b>
          </span>
        </div>
      </div>

      </>}
      {section === "metrics" && <>{/* ── Headline metrics (directives 19-20, 55) ─────────────────── */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(min(200px, 100%), 1fr))', gap: 'var(--space-4)', marginBottom: 'var(--space-5)' }}>
        <SummaryCard
          label="Needs attention"
          value={headline.open_opportunities_count}
          sub="gaps, risks & follow-ups across all sources"
          tone={headline.open_opportunities_count > 0 ? 'warning' : 'neutral'}
          tooltip={PROVENANCE}
        />
        <SummaryCard
          label="Technologies Known"
          value={headline.technologies_known}
          sub={tl.eol_count > 0 || tl.unsupported_count > 0
            ? `${tl.eol_count} end-of-life · ${tl.unsupported_count} unsupported`
            : 'No lifecycle flags recorded'}
          tone={tl.at_risk_count > 0 ? 'negative' : tl.eol_count > 0 ? 'warning' : 'neutral'}
          tooltip={PROVENANCE}
          onCardClick={onNavigate ? () => onNavigate('technology-inventory') : undefined}
        />
        <SummaryCard
          label="Projected business impact"
          value={impact.contributing_use_cases ? "View estimates" : "No estimates recorded"}
          sub="Currency and time basis are not recorded"
          tone="accent"
          tooltip={`${PROVENANCE} ${impact.contributing_use_cases} contributing use case${impact.contributing_use_cases === 1 ? '' : 's'}.`}
          onCardClick={onNavigate ? () => onNavigate('business-impact') : undefined}
        />
      </div>

      </>}
      {section === "intelligence" && <>{/* ── Partial empty state (directive 56) — sparse account: name what's
          missing + one obvious next action instead of a grid of bare zeros. ── */}
      {partialSparse && (
        <div style={{
          display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 'var(--space-3)',
          flexWrap: 'wrap', padding: 'var(--space-3) var(--space-4)', marginBottom: 'var(--space-5)',
          background: 'var(--neutral-0)',
          border: '1px solid var(--neutral-300)', borderRadius: 'var(--radius)',
        }}>
          <div style={{ fontSize: '0.85rem', color: 'var(--neutral-700)' }}>
            <b>Sources not yet recorded:</b> no {missingSources.join(', ')} recorded yet.
          </div>

        </div>
      )}

      {/* ── Actionable intelligence summaries (directives 22-26) ────── */}
      <div style={{ marginBottom: 'var(--space-5)' }}>
        <h3 style={{ margin: '0 0 12px 0', fontSize: '1rem', color: 'var(--neutral-700)' }}><SectionIcon name="🧭" /> Account Intelligence</h3>
        <IntelligencePanelsContent ws={ws} includeAssessment={false} onNavigate={onNavigate} />
      </div>

      </>}
    </>
  );
}

function CustomerActions({ onNavigate }: { onNavigate?: (target: string) => void }) {
  return <>
      {onNavigate && <div style={{ marginBottom: 'var(--space-5)' }}><nav aria-label="Primary customer actions" className="crm-actions">
        <button type="button" onClick={() => onNavigate('tasks')}>View follow-ups</button>
        <button type="button" onClick={() => onNavigate('activities')}>View interactions</button>
        <button type="button" onClick={() => onNavigate('sales-deals')}>View deals</button>
        <button type="button" onClick={() => onNavigate('contacts')}>View contacts</button>
      </nav><nav aria-label="More customer information" className="crm-actions" style={{ marginTop: 8 }}>
        <button type="button" onClick={() => onNavigate('account-timeline')}>View timeline</button>
        <button type="button" onClick={() => onNavigate('sales-opportunities')}>View attention</button>
        <button type="button" onClick={() => onNavigate('sales-pipeline')}>View partner pipeline</button>
        <button type="button" onClick={() => onNavigate('sales-vendor-intelligence')}>View vendor intelligence</button>
      </nav></div>}
  </>;
}

/** Dedicated Intelligence ▸ Summary view (directive 51): the four
 *  actionable summaries on their own. Fetches the workspace independently
 *  (same convention as the other intelligence components). */
export function IntelligencePanels({ customerId }: { customerId: number }) {
  const [ws, setWs] = useState<AccountWorkspace | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [retry, setRetry] = useState(0);

  useEffect(() => {
    let alive = true;
    setWs(null);
    setError(null);
    api
      .getAccountWorkspace(customerId)
      .then((w) => { if (alive) { if (!w || w.customer_id !== customerId) setError('Customer response unavailable'); else setWs(w); } })
      .catch((e: any) => { if (alive) setError(e?.message || 'Failed to load customer intelligence'); });
    return () => { alive = false; }
  }, [customerId, retry]);

  if (error) {
    return (
      <div role="alert" style={{ padding: '10px 14px', background: 'var(--status-negative-soft)', color: 'var(--status-negative)', borderRadius: 'var(--radius)', fontSize: '0.85rem', marginBottom: '24px' }}>
        {error} <button type="button" onClick={() => setRetry(value => value + 1)}>Retry intelligence</button>
      </div>
    );
  }

  return (
    <div>
      <h2 style={{ margin: '0 0 4px 0', fontSize: '1.3rem', color: 'var(--ink)' }}><SectionIcon name="🧭" /> Customer Intelligence</h2>
      <p title={PROVENANCE} style={{ margin: '0 0 16px 0', color: 'var(--neutral-500)', fontSize: '0.9rem' }}>
        What S-A-I-L knows about this account across the technology, knowledge, and sales sources — and what needs attention.
      </p>
      {ws && ws.customer_id === customerId && ws.technology_landscape && ws.knowledge && ws.sales_activity && ws.assessment ? <IntelligencePanelsContent ws={ws} /> : ws && ws.customer_id === customerId ? <div role="alert">Customer intelligence unavailable. <button type="button" onClick={() => setRetry(value => value + 1)}>Retry intelligence</button></div> : <p role="status">Loading customer intelligence…</p>}
    </div>
  );
}
