import { useEffect, useMemo, useState } from 'react';
import { api } from '../lib/api';
import { GlobalStats, PortfolioAccountImpact, AccountImpactCoverage, Customer } from '../types/use_case';
import { AdminConsole } from '../components/AdminConsole';
import { MyTasksBlock } from '../components/MyTasksBlock';
import { MyWorkBlock } from '../components/MyWorkBlock';
import { MyTeamBlock } from '../components/MyTeamBlock';
import { formatImpact, impactCoverage, formatPipelineAmount, loadPortfolioImpact, pipelineKpi, PIPELINE_KPI_LABEL, renewalKpi, renewalRowLine, RENEWAL_KPI_LABEL } from '../lib/accountImpact';
import { CustomerListPager } from '../components/CustomerListPager';
import { PortfolioFilterBar } from '../components/PortfolioFilterBar';
import { activeFilterSummary, filterRows, isFiltered, sortRows } from '../lib/portfolioNav';
import type { PortfolioNavRow, SortKey } from '../lib/portfolioNav';
import { paginateNav, usePortfolioNavState } from '../lib/usePortfolioNavState';
import { useDashboardScope } from '../lib/useDashboardScope';
import { useReducedMotion } from '../lib/theme';

const HOME_SORT_KEYS: readonly SortKey[] = ['newest', 'name', 'vertical', 'branch', 'owner', 'impact', 'pipeline'];

type HomeRow = PortfolioNavRow & {
  value: number | null;
  coverage: AccountImpactCoverage | undefined;
  pipeline?: PortfolioAccountImpact['customers'][number]['pipeline'];
  renewals?: PortfolioAccountImpact['customers'][number]['renewals'];
  canScore?: boolean;
  canManageCustomer?: boolean;
};

interface HomeDashboardProps {
  onNavigate: (view: string, customerName?: string, action?: string) => void;
  isAdmin?: boolean;
  username?: string;
}

export function HomeDashboard({ onNavigate, isAdmin, username }: HomeDashboardProps) {
  const [customerStats, setCustomerStats] = useState<GlobalStats | null>(null);
  const [impact, setImpact] = useState<PortfolioAccountImpact | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadedScope, setLoadedScope] = useState<boolean | null>(null);
  const [error, setError] = useState<string | null>(null);
  const { myView, toggle: toggleScope, invalid: invalidScope } = useDashboardScope(!!isAdmin);
  const [customerList, setCustomerList] = useState<Customer[]>([]);
  const { state: nav, update: updateNav, reset: resetNav } = usePortfolioNavState();
  const [sortFallback, setSortFallback] = useState(false);
  useEffect(() => {
    if (nav.sort === 'granted') {
      setSortFallback(true);
      updateNav({ sort: 'name', dir: 'asc', page: 1 });
    }
  }, [nav.sort, updateNav]);

  useEffect(() => {
    let alive = true;
    const loadData = async () => {
      try {
        setLoading(true);
        setError(null);
        const [customerStatsData, impactData, listData] = await Promise.all([
          api.getCustomersStats(myView).catch(() => null),
          loadPortfolioImpact(myView),
          // H2: authorized customer list = metadata join source (one request).
          Promise.resolve(api.listCustomers()).catch(() => null),
        ]);
        if (!alive) return;
        setError(null);
        setCustomerStats(customerStatsData);
        setImpact(impactData);
        setCustomerList(Array.isArray(listData) ? listData : []);
        setLoadedScope(myView);
      } catch (err) {
        if (alive) {
          setLoadedScope(myView);
          setError(err instanceof Error ? err.message : 'Failed to load dashboard');
        }
      } finally {
        if (alive) setLoading(false);
      }
    };
    void loadData();
    return () => { alive = false; };
  }, [myView]);

  const userCountById = new Map((customerStats?.customers ?? []).map(c => [c.customer_id, c.user_count]));
  // Portfolio rows come from the account-impact contract; fall back to the
  // customer list (impact "Not quantified") if that contract is unavailable.
  const customerById = useMemo(() => new Map(customerList.map(c => [c.id, c])), [customerList]);
  const rows: HomeRow[] = useMemo(() => {
    // The /customers/ join wins (same source record); on a join miss fall back
    // to the impact row's own metadata, else the row is knownMetadata=false.
    const meta = (id: number, own?: PortfolioAccountImpact['customers'][number]) => {
      const j = customerById.get(id);
      if (j) {
        return {
          description: j.description ?? null, vertical: j.vertical ?? null, branch: j.branch ?? null,
          salesArea: j.sales_area ?? null, primarySubsidiary: j.primary_subsidiary ?? null,
          primaryRep: j.primary_rep ?? null, managerName: j.manager_name ?? null, knownMetadata: true,
        };
      }
      const hasOwn = own !== undefined && (own.primary_rep !== undefined || own.vertical !== undefined || own.branch !== undefined);
      return {
        vertical: own?.vertical ?? null, branch: own?.branch ?? null, salesArea: own?.sales_area ?? null,
        primarySubsidiary: own?.primary_subsidiary ?? null, primaryRep: own?.primary_rep ?? null, knownMetadata: hasOwn,
      };
    };
    // Portfolio rows come from the account-impact contract; fall back to the
    // customer list (impact "Not quantified") if that contract is unavailable.
    return impact
      ? impact.customers.map(c => ({
          id: c.customer_id, name: c.customer_name, value: c.total_impact, coverage: c.coverage, pipeline: c.pipeline, renewals: c.renewals,
          totalImpact: c.total_impact, pipelineAcv: c.pipeline?.acv ?? null, canScore: c.can_score, canManageCustomer: c.can_manage_customer, ...meta(c.customer_id, c),
        }))
      : (customerStats?.customers ?? []).map(c => ({
          id: c.customer_id, name: c.customer_name, value: null, coverage: undefined,
          totalImpact: null, pipelineAcv: null, ...meta(c.customer_id),
        }));
  }, [impact, customerStats, customerById]);
  // Search/filter/sort span the FULL authorized rows; the pager only slices.
  const shownRows = useMemo(() => sortRows(filterRows(rows, nav), nav), [rows, nav]);
  // The worklist references accounts by id; the portfolio rows carry
  // the same authorized set, so resolve id → name for the by-name navigation.
  const idToName = useMemo(() => new Map(rows.map(r => [r.id, r.name] as const)), [rows]);
  const pager = paginateNav(shownRows, nav, updateNav);
  const headerSort = (key: SortKey) => (nav.sort === key ? (nav.dir === 'asc' ? 'ascending' : 'descending') : 'none') as 'ascending' | 'descending' | 'none';
  const clickHeader = (key: SortKey) => updateNav(nav.sort === key ? { dir: nav.dir === 'asc' ? 'desc' : 'asc' } : { sort: key, dir: 'asc' });

  // A scope change is visible before the effect starts; never render data
  // from the previous scope during that render or a later in-flight request.
  const scopeReady = !loading && loadedScope === myView && !error;
  const activeError = loadedScope === myView ? error : null;
  const customerCount = scopeReady ? (impact?.customer_count ?? customerStats?.total_customers) : undefined;
  const scopeLabel = myView ? 'My customers' : (scopeReady ? impact?.scope || 'Authorized customers' : 'Authorized customers');

  return (
    <div style={{ padding: 'clamp(10px, 3vw, 24px)', maxWidth: '1400px', minWidth: 0, margin: '0 auto' }}>
      <style>{`#dashboard-portfolio-table th button:focus-visible { outline: 3px solid var(--brand-700); outline-offset: 2px; border-radius: 2px; }`}</style>
      <div style={{ marginBottom: '24px' }}>
        <h1 style={{ margin: '0 0 4px 0', fontSize: '1.8rem', color: 'var(--ink)' }}>Dashboard</h1>
        <p style={{ margin: 0, color: 'var(--neutral-500)', fontSize: '0.95rem' }}>
          {/* UX audit #12: pluralize the count ("1 customers" → "1 customer"). */}
          {!scopeReady && !activeError ? 'Portfolio updating…' : customerCount == null ? 'Customer portfolio unavailable' : `Customer portfolio — ${customerCount} customer${customerCount === 1 ? '' : 's'}`}
        </p>
      </div>

      {username && <div style={{ marginBottom: '24px' }}><MyTasksBlock username={username} onOpenAccount={name => onNavigate('customers', name)} /></div>}
      {username && <div style={{ marginBottom: '24px' }}><MyWorkBlock onOpenCustomer={(id, dealId) => {
        const name = idToName.get(id);
        if (name) onNavigate('customers', name, dealId ? `deal:${dealId}` : undefined);
      }} /></div>}
      {/* managers keep their personal sections first; the team rollup follows. */}
      {username && <div style={{ marginBottom: '24px' }}><MyTeamBlock /></div>}
      <div style={{ marginBottom: '28px' }}>
        <h2 style={{ margin: '0 0 12px 0', fontSize: '1.1rem', color: 'var(--neutral-700)' }}>Quick Actions</h2>
        <div style={{ display: 'flex', gap: '12px', flexWrap: 'wrap' }}>
          <ActionButton onClick={() => onNavigate('customers')} label="My Customers" icon="🏢" color="var(--brand-500)" />
          <ActionButton onClick={() => onNavigate('export-pdf')} label="Export PDF" icon="📄" color="var(--status-negative)" />
        </div>
        <p style={{ margin: '12px 0 0', color: 'var(--neutral-500)', fontSize: '0.85rem' }}>
          Assessments, scoring and impact analysis live inside a customer — open a customer to work on them.
        </p>
      </div>
      {isAdmin && <details style={{ marginBottom: '24px', padding: '12px 16px', background: 'var(--neutral-50)', border: '1px solid var(--divider)', borderRadius: 'var(--radius)' }}>
        <summary style={{ cursor: 'pointer', fontWeight: 600, color: 'var(--ink)' }}>Administration</summary>
        <AdminConsole onNavigate={onNavigate} showPortfolio={false} />
      </details>}
      {sortFallback && <p role="status">The previous added-date sort is unavailable and was replaced with name sorting.</p>}
      {invalidScope && <p role="status">The requested portfolio scope is unavailable. Showing {isAdmin ? 'your scoped portfolio' : 'your authorized portfolio'}.</p>}

      <p id="dashboard-scope-description" style={{ margin: '0 0 12px', color: 'var(--neutral-600)', overflowWrap: 'anywhere' }}>Current portfolio scope: {scopeLabel}</p>

      {/* Portfolio KPI cards */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '8px', marginBottom: '16px' }}>
        <h2 style={{ margin: 0, fontSize: '1.1rem', color: 'var(--neutral-700)' }}>Portfolio</h2>
        {isAdmin && <button role="button" aria-label="Toggle between My View and All View" aria-pressed={myView} aria-describedby="dashboard-scope-description"
          onClick={toggleScope}
          style={{
            padding: '6px 14px',
            background: myView ? 'var(--brand-500)' : 'var(--brand-50)',
            border: '1px solid var(--brand-500)',
            color: myView ? 'var(--neutral-0)' : 'var(--brand-700)',
            borderRadius: 'var(--radius)',
            cursor: 'pointer',
            fontSize: '0.85rem',
            fontWeight: 600,
          }}
        >
          {myView ? '👤 My View' : '🌐 All View'}
        </button>}
      </div>
      {activeError && <div role="alert" style={{ padding: '16px', color: 'var(--status-negative)', background: 'var(--status-negative-soft)', borderRadius: 'var(--radius-sm)' }}>
        {activeError} <button type="button" onClick={() => window.location.reload()}>Retry</button>
      </div>}
      {!scopeReady && !activeError && <div role="status" aria-live="polite" aria-busy="true" style={{ padding: '16px 0', color: 'var(--neutral-500)' }}>Loading portfolio…</div>}
      {scopeReady && <div aria-busy="false">
      {!impact && <p role="alert" style={{ color: 'var(--status-negative)' }}>Portfolio impact is unavailable. Refresh the page to retry; financial values below cannot be confirmed.</p>}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(min(100%, 250px), 1fr))', gap: '12px', marginBottom: '28px' }}>
        <KPICard
          value={impact ? formatImpact(impact.total_impact.value, impact.coverage, impact.total_impact.currency) : 'Unavailable'}
          label={impact ? `Estimated customer benefit · ${impactCoverage(impact)}${Number.isNaN(Date.parse(impact.as_of)) ? '' : ` · As of ${new Date(impact.as_of).toLocaleDateString()}`}` : 'Estimated customer benefit'}
          gradient="var(--gradient-brand)"
          icon="💰"
        />
        <div data-testid="pipeline-kpi">
          <KPICard
            value={impact ? pipelineKpi(impact.pipeline).value : 'Unavailable'}
            label={impact ? `${PIPELINE_KPI_LABEL} (${pipelineKpi(impact.pipeline).detail})` : PIPELINE_KPI_LABEL}
            gradient="var(--gradient-brand)"
            icon="📈"
          />
        </div>
        <div data-testid="renewals-kpi">
          <KPICard
            value={impact ? renewalKpi(impact.renewals).value : 'Unavailable'}
            label={impact ? `${RENEWAL_KPI_LABEL} (${renewalKpi(impact.renewals).detail})` : RENEWAL_KPI_LABEL}
            gradient="var(--gradient-brand)"
            icon="🔄"
          />
        </div>
      </div>

      {/* Customer portfolio */}
      {rows.length > 0 && (
        <div style={{ background: 'var(--neutral-0)', borderRadius: 'var(--radius)', padding: 'clamp(8px, 2vw, 20px)', minWidth: 0, boxShadow: 'var(--shadow-card)', marginBottom: '20px' }}>
          <h3 style={{ margin: '0 0 16px 0', fontSize: '1rem', color: 'var(--neutral-700)' }}>Customer Portfolio</h3>
          <PortfolioFilterBar rows={rows} state={nav} onChange={updateNav} onReset={resetNav} filteredCount={shownRows.length} sortKeys={HOME_SORT_KEYS} />
          {shownRows.length === 0 ? (
            <div data-testid="no-matches" style={{ padding: 'clamp(8px, 5vw, 32px)', textAlign: 'center' }}>
              <p style={{ margin: '0 0 8px', fontSize: '1.05rem', color: 'var(--neutral-500)' }}>No matches</p>
              <p style={{ margin: '0 0 8px', fontSize: '0.85rem', color: 'var(--neutral-500)' }}>
                {activeFilterSummary(nav)}
              </p>
              {isFiltered(nav) && (
                <button type="button" aria-label="Reset filters" onClick={resetNav}
                  style={{ padding: '6px 14px', border: '1px solid var(--brand-500)', borderRadius: 'var(--radius-sm)', background: 'var(--neutral-0)', color: 'var(--brand-700)', cursor: 'pointer' }}>
                  Reset filters
                </button>
              )}
            </div>
          ) : (<>
          <CustomerListPager {...pager.pagerProps} />
          <div style={{ overflowX: 'auto' }}>
            <table id="dashboard-portfolio-table" style={{ width: '100%', borderCollapse: 'collapse' }}>
              <thead>
                <tr style={{ borderBottom: '2px solid var(--divider)' }}>
                  {([['Customer', 'name'], ['Owner', 'owner'], ['Vertical', 'vertical'], ['Branch', 'branch'], ['Users', null], ['Account Impact', 'impact'], ['Actions', null]] as [string, SortKey | null][]).map(([h, key]) => (
                    <th key={h} aria-sort={key ? headerSort(key) : undefined} style={{ padding: '12px 16px', textAlign: 'left', fontSize: '0.85rem', fontWeight: 600, color: 'var(--neutral-500)' }}>
                      {key ? (
                        <button type="button" onClick={() => clickHeader(key)} aria-label={`Sort by ${h}`}
                          onFocus={event => {
                            // Keep the entire focus ring inside the table's own scroll area.
                            const scroller = event.currentTarget.closest('table')?.parentElement;
                            if (!scroller) return;
                            const target = event.currentTarget.getBoundingClientRect();
                            const viewport = scroller.getBoundingClientRect();
                            const left = target.left - viewport.left - 5;
                            const right = target.right - viewport.right + 5;
                            if (left < 0) scroller.scrollLeft += left;
                            else if (right > 0) scroller.scrollLeft += right;
                          }}
                          style={{ border: 0, background: 'transparent', padding: 0, font: 'inherit', color: 'inherit', cursor: 'pointer', display: 'inline-flex', gap: '4px', alignItems: 'center' }}>
                          {h}<span aria-hidden="true">{nav.sort === key ? (nav.dir === 'asc' ? '▲' : '▼') : ''}</span>
                        </button>
                      ) : h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {pager.visible.map(c => (
                  <tr key={c.id} style={{ borderBottom: '1px solid var(--neutral-100)' }}>
                    <td style={{ padding: '12px 16px', fontWeight: 500, color: 'var(--ink)' }}><button type="button" onClick={() => onNavigate('customers', c.name)} style={{ border: 0, padding: 0, background: 'transparent', color: 'var(--brand-700)', cursor: 'pointer', font: 'inherit', textAlign: 'left', textDecoration: 'underline' }}>{c.name}</button></td>
                    <td style={{ padding: '12px 16px', color: 'var(--neutral-500)' }}>{c.primaryRep || '—'}</td>
                    <td style={{ padding: '12px 16px', color: 'var(--neutral-500)' }}>{c.vertical || '—'}</td>
                    <td style={{ padding: '12px 16px', color: 'var(--neutral-500)' }}>{c.branch || '—'}</td>
                    <td style={{ padding: '12px 16px', color: 'var(--neutral-500)' }}>{userCountById.get(c.id) ?? '—'}</td>
                    <td style={{ padding: '12px 16px', fontWeight: 'bold', color: c.value != null ? 'var(--status-warning)' : 'var(--neutral-500)' }}>
                      {impact ? formatImpact(c.value, c.coverage) : 'Unavailable'}
                      <div data-testid={`customer-pipeline-line-${c.id}`} style={{ fontSize: '0.75rem', fontWeight: 400, color: 'var(--neutral-500)' }}>
                        Pipeline: {impact ? formatPipelineAmount(c.pipeline?.acv, c.pipeline?.coverage) : 'Unavailable'}
                      </div>
                      <div data-testid={`customer-renewals-line-${c.id}`} style={{ fontSize: '0.75rem', fontWeight: 400, color: 'var(--neutral-500)' }}>
                        Renewals: {impact ? renewalRowLine(c.renewals) : 'Unavailable'}
                      </div>
                    </td>
                    <td style={{ padding: '12px 16px' }}>
                      <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap' }}>
                        {c.canScore && <button type="button" aria-label={`Score ${c.name}`} onClick={() => onNavigate('customers', c.name, 'bulk-score')}>Score</button>}
                        {c.canManageCustomer && <><button type="button" aria-label={`Edit ${c.name}`} onClick={() => onNavigate('customers', c.name, 'edit')}>Edit</button><button type="button" aria-label={`Remove ${c.name}`} onClick={() => onNavigate('customers', c.name, 'remove')}>Remove</button></>}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          </>)}
        </div>
      )}

      {rows.length === 0 && impact && <p style={{ padding: '20px', background: 'var(--neutral-50)', borderRadius: 'var(--radius)' }}>No customers in this portfolio.</p>}
      </div>}

    </div>
  );
}


function KPICard({ value, label, gradient, icon }: { value: string; label: string; gradient: string; icon: string }) {
  return (
    <div style={{ background: gradient, color: 'white', padding: '14px 16px', borderRadius: 'var(--radius)', display: 'flex', alignItems: 'flex-start', gap: '12px', minWidth: 0, height: '100%', boxSizing: 'border-box' }}>
      <span aria-hidden="true" style={{ fontSize: '1.25rem', flexShrink: 0 }}>{icon}</span>
      <div style={{ minWidth: 0, overflowWrap: 'anywhere' }}>
        <div style={{ fontSize: '1.2rem', fontWeight: 'bold' }}>{value}</div>
        <div style={{ fontSize: '0.85rem' }}>{label}</div>
      </div>
    </div>
  );
}

// FE-10: `color` here is a CSS variable (e.g. var(--brand-500)); hex-alpha
// suffixes on a var() expression are invalid, so compose with color-mix().
const mix = (c: string, p: number) => `color-mix(in srgb, ${c} ${p}%, transparent)`;

function ActionButton({ onClick, label, icon, color }: { onClick: () => void; label: string; icon: string; color: string }) {
  const reducedMotion = useReducedMotion();
  return (
    <button role="button" aria-label={`Go to ${label}`} onClick={onClick}
      style={{
        padding: '10px 20px',
        background: mix(color, 20),
        border: `1px solid ${mix(color, 40)}`,
        borderRadius: 'var(--radius)',
        cursor: 'pointer',
        fontSize: '0.9rem',
        color: color,
        fontWeight: 600,
        display: 'flex',
        alignItems: 'center',
        gap: '8px',
        transition: reducedMotion ? 'none' : 'all 0.2s',
        transform: reducedMotion ? 'none' : undefined,
      }}
      onMouseEnter={e => { e.currentTarget.style.background = mix(color, 30); e.currentTarget.style.transform = reducedMotion ? 'none' : 'translateY(-1px)'; }}
      onMouseLeave={e => { e.currentTarget.style.background = mix(color, 20); e.currentTarget.style.transform = reducedMotion ? 'none' : 'translateY(0)'; }}
    >
      <span>{icon}</span>{label}
    </button>
  );
}
