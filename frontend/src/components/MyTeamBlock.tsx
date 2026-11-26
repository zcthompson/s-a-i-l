/**
 * E4 — "My team" (decision D1): a sales manager's team rollup, shown below the
 * personal dashboard sections. Data comes from GET /api/rollups/team/, which
 * the server limits to active sales managers and to accounts the manager can
 * currently read. Unknown stays unknown: amounts keep their coverage label and
 * never render as $0; counts of "no recorded" evidence are not proof of absence.
 */
import { useCallback, useEffect, useRef, useState } from 'react';
import type { CSSProperties } from 'react';
import { api, getAuthSalesRole } from '../lib/api';
import { formatPipelineAmount } from '../lib/accountImpact';
import type { TeamRollupRep, TeamRollupResponse, TeamRollupSummary } from '../types/teamRollup';

const muted: CSSProperties = { fontSize: '0.85rem', color: 'var(--neutral-500)' };
const cell: CSSProperties = { padding: '6px 8px', borderBottom: '1px solid var(--divider)', textAlign: 'left', verticalAlign: 'top' };

/** Renewals due within 90 days, including overdue ones. */
export function renewalsWithin90(s: TeamRollupSummary): number {
  const r = s.renewal_counts;
  return r.overdue + r.within_30 + r.within_60 + r.within_90;
}

export function repName(rep: TeamRollupRep): string {
  return rep.display_name || rep.username;
}

function acv(s: TeamRollupSummary): string {
  return formatPipelineAmount(s.pipeline.acv.total, s.pipeline.acv.coverage);
}

function Stat({ id, label, value, alert = false }: { id: string; label: string; value: string | number; alert?: boolean }) {
  return (
    <div data-testid={`my-team-stat-${id}`} style={{ minWidth: 0 }}>
      <div style={{ fontSize: '1.15rem', fontWeight: 700, color: alert ? 'var(--status-negative)' : 'var(--ink)', overflowWrap: 'anywhere' }}>{value}</div>
      <div style={{ ...muted, fontSize: '0.78rem' }}>{label}</div>
    </div>
  );
}

export function MyTeamBlock() {
  const isManager = getAuthSalesRole() === 'sales_manager';
  const [data, setData] = useState<TeamRollupResponse | null>(null);
  const [state, setState] = useState<'loading' | 'ready' | 'failed' | 'forbidden'>('loading');
  const seq = useRef(0);

  const load = useCallback(() => {
    const mine = ++seq.current;
    setState('loading');
    setData(null);
    // A failure here must never take down the rest of the dashboard.
    Promise.resolve()
      .then(() => api.teamRollup())
      .then(r => { if (mine === seq.current) { setData(r); setState('ready'); } })
      .catch((err: { status?: number }) => {
        if (mine === seq.current) setState(err?.status === 403 ? 'forbidden' : 'failed');
      });
  }, []);

  useEffect(() => {
    if (!isManager) return;
    load();
    return () => { seq.current += 1; };
  }, [isManager, load]);

  // Server authority: a 403 (for example a stale stored role) hides the block.
  if (!isManager || state === 'forbidden') return null;

  return (
    <section data-testid="my-team" aria-labelledby="my-team-heading"
      style={{ background: 'var(--neutral-0)', borderRadius: 'var(--radius)', boxShadow: 'var(--shadow-card)', padding: '16px', minWidth: 0 }}>
      <h3 id="my-team-heading" style={{ margin: '0 0 10px', fontSize: '1.05rem', color: 'var(--neutral-700)' }}>My Team</h3>
      {state === 'loading' && <div role="status" aria-live="polite" style={muted}>Loading team summary…</div>}
      {state === 'failed' && (
        <div role="alert" data-testid="my-team-error" style={{ ...muted, color: 'var(--status-negative)', display: 'flex', gap: '8px', alignItems: 'center', flexWrap: 'wrap' }}>
          Team summary unavailable. Try again.
          <button type="button" onClick={load}>Retry</button>
        </div>
      )}
      {state === 'ready' && data && (data.reps.length === 0 ? (
        <div data-testid="my-team-empty" style={muted}>No active reps report to you yet.</div>
      ) : (
        <>
          <div data-testid="my-team-summary" style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(min(100%, 140px), 1fr))', gap: '12px', marginBottom: '14px' }}>
            <Stat id="accounts" label="Team accounts" value={data.team.accounts} />
            <Stat id="acv" label="Partner pipeline ACV (unweighted)" value={acv(data.team)} />
            <Stat id="renewals" label="Renewals due ≤ 90 days" value={renewalsWithin90(data.team)} alert={data.team.renewal_counts.overdue > 0} />
            <Stat id="tasks" label="Open tasks (overdue)" value={`${data.team.open_tasks} (${data.team.overdue_tasks})`} alert={data.team.overdue_tasks > 0} />
            <Stat id="no-interaction" label="Accounts with no recorded interaction" value={data.team.no_recorded_interaction} />
            <Stat id="no-contacts" label="Accounts with no contacts recorded" value={data.team.no_contacts_recorded} />
          </div>
          <div style={{ overflowX: 'auto', maxWidth: '100%' }}>
            <table data-testid="my-team-table" style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.85rem', minWidth: '640px' }}>
              <caption style={{ ...muted, textAlign: 'left', paddingBottom: '6px' }}>By rep (an account shared by reps appears under each; team totals count it once)</caption>
              <thead>
                <tr>
                  {['Rep', 'Accounts', 'Partner pipeline ACV', 'Rep-owned deals (open)', 'Renewals ≤ 90 days', 'Open tasks (overdue)', 'No recorded interaction', 'No economic buyer', 'No champion'].map(h => (
                    <th key={h} scope="col" style={{ ...cell, color: 'var(--neutral-600)', fontWeight: 600 }}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {data.reps.map(rep => (
                  <tr key={rep.user_id} data-testid={`my-team-rep-${rep.user_id}`}>
                    <th scope="row" style={{ ...cell, fontWeight: 600, color: 'var(--ink)', overflowWrap: 'anywhere' }}>{repName(rep)}</th>
                    <td style={cell}>{rep.accounts}</td>
                    <td style={cell} data-testid={`my-team-rep-acv-${rep.user_id}`}>{acv(rep)}</td>
                    <td style={cell}>{rep.rep_deals?.counts.open ?? 0}</td>
                    <td style={{ ...cell, color: rep.renewal_counts.overdue ? 'var(--status-negative)' : undefined }}>
                      {renewalsWithin90(rep)}{rep.renewal_counts.overdue ? ` (${rep.renewal_counts.overdue} overdue)` : ''}
                    </td>
                    <td style={{ ...cell, color: rep.overdue_tasks ? 'var(--status-negative)' : undefined }}>{rep.open_tasks} ({rep.overdue_tasks})</td>
                    <td style={cell}>{rep.no_recorded_interaction}</td>
                    <td style={cell}>{rep.no_economic_buyer_recorded}</td>
                    <td style={cell}>{rep.no_champion_recorded}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {data.team.rep_deals && <section aria-label="Rep-owned deal amounts"><h4>Open rep-owned deals · separate from partner pipeline</h4>
            <p>{data.team.rep_deals.counts.open} open deals</p>
            {data.team.rep_deals.open_amounts.map((amount, index) => <p key={index}>{amount.currency} {amount.minor === null ? 'Amount unknown' : (amount.minor / 100).toLocaleString()} · {amount.basis ?? 'Basis not recorded'} · {amount.unknown_amounts} amounts unknown</p>)}
          </section>}
          <p data-testid="my-team-basis" style={{ ...muted, fontSize: '0.75rem', margin: '10px 0 0' }}>{data.basis}</p>
        </>
      ))}
    </section>
  );
}
