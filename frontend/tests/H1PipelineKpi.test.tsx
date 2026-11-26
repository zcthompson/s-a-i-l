/**
 * H1 — dashboards carry a separate, honest partner-pipeline KPI + per-customer
 * "Pipeline:" line from the SAME portfolio payload (no new request).
 */
import { describe, it, expect, vi, afterEach, beforeEach } from 'vitest';
import { render, screen, cleanup, within } from '@testing-library/react';
import React from 'react';

const { apiStub, impactFn } = vi.hoisted(() => {
  const impactFn = vi.fn();
  const methods: Record<string, (...a: any[]) => Promise<unknown>> = {
    getCustomersStats: () => Promise.resolve({
      total_customers: 2, total_use_cases: 9, total_scored: 5, average_score: 42,
      total_savings: 1, total_revenue: 1, total_impact: 2,
      customers: [
        { customer_id: 1, customer_name: 'Acme', use_case_count: 5, user_count: 3 },
        { customer_id: 2, customer_name: 'Globex', use_case_count: 4, user_count: 1 },
      ],
    }),
    getPortfolioAccountImpact: () => impactFn(),
    getMyCustomers: () => Promise.resolve([
      { id: 1, customer_id: 1, customer_name: 'Acme', user_id: 1, username: 'u', role: 'owner', granted_by: null, granted_at: null },
    ]),
    listCustomers: () => Promise.resolve([{ name: 'Acme', vertical: null }]),
    getGlobalAdminStats: () => Promise.resolve({
      total_customers: 1, total_users: 1,
      customers: [{ customer_id: 1, customer_name: 'Acme', user_count: 3 }],
    }),
    listAllThirdPartyServices: () => Promise.resolve([]),
  };
  const stub: any = new Proxy({}, {
    get: (_t, p) => (typeof p === 'string' && methods[p] ? methods[p] : () => Promise.resolve([])),
  });
  return { apiStub: stub, impactFn };
});

vi.mock('../src/lib/api', () => ({
  api: apiStub,
  getAuthToken: () => 'tok',
  clearAuth: () => undefined,
  getAuthUsername: () => 'tester',
  getAuthIsAdmin: () => true,
  getAuthSalesRole: () => null,
}));
vi.mock('../src/components/AppHealthCard', () => ({ AppHealthCard: () => null }));
vi.mock('../src/components/AdminConsole', () => ({ AdminConsole: () => null }));

import { HomeDashboard } from '../src/pages/HomeDashboard';
import { GlobalAdminDashboard } from '../src/components/GlobalAdminDashboard';


const amt = (over: object) => ({ total: null, lines: 0, accounts_quantified: 0, accounts_partial: 0, accounts_recorded_zero: 0, accounts_all_unknown: 0, accounts_no_data: 0, ...over });
const withPipeline = {
  customer_count: 2, as_of: 'x', calculation_version: 'account-impact/2', coverage: 'quantified',
  scope: 'All authorized customers',
  total_impact: { value: 1500, perspective: 'customer_benefit', realization_basis: 'estimated', currency: null },
  rollup: { quantified: 1, partial: 0, not_quantified: 1 },
  customers: [
    { customer_id: 1, customer_name: 'Acme', coverage: 'quantified', total_impact: 1500, pipeline: { acv: 98765, tcv: null, coverage: 'quantified' } },
    { customer_id: 2, customer_name: 'Globex', coverage: 'not_quantified', total_impact: null, pipeline: { acv: null, tcv: null, coverage: 'all_unknown' } },
  ],
  pipeline: {
    calculation_version: 'pipeline-read-model/1', as_of: 'x', note: 'n',
    acv: amt({ total: 98765, lines: 4, accounts_quantified: 1, accounts_all_unknown: 1 }),
    tcv: amt({ accounts_all_unknown: 2 }),
  },
};
const noPipeline = { ...withPipeline, pipeline: undefined, customers: withPipeline.customers.map(({ pipeline: _p, ...c }) => c) };


beforeEach(() => { impactFn.mockReset(); });
afterEach(cleanup);

describe('H1 pipeline KPI', () => {
  it('HomeDashboard: KPI + per-customer line; impact KPI untouched; unknown never $0', async () => {
    impactFn.mockResolvedValue(withPipeline);
    render(<HomeDashboard onNavigate={() => undefined} isAdmin />);
    const kpi = await screen.findByTestId('pipeline-kpi');
    expect(kpi.textContent).toContain('$98,765');
    expect(kpi.textContent).toContain('Partner pipeline — unweighted, source-labelled USD');
    expect(kpi.textContent).toContain('TCV Not recorded');
    expect(screen.getAllByText('1,500 (currency not recorded)').length).toBeGreaterThan(0);
    expect(screen.getByTestId('customer-pipeline-line-1').textContent).toBe('Pipeline: $98,765');
    expect(screen.getByTestId('customer-pipeline-line-2').textContent).toBe('Pipeline: Not recorded');
  });

  it('Dashboard with personal tasks: KPI + per-customer line', async () => {
    impactFn.mockResolvedValue(withPipeline);
    render(<HomeDashboard username="tester" isAdmin={false} onNavigate={() => undefined} />);
    const kpi = await screen.findByTestId('pipeline-kpi');
    await vi.waitFor(() => expect(kpi.textContent).toContain('$98,765'));
    expect(screen.getByTestId('customer-pipeline-line-1').textContent).toBe('Pipeline: $98,765');
  });

  it('GlobalAdminDashboard: KPI + per-customer line', async () => {
    impactFn.mockResolvedValue(withPipeline);
    render(<GlobalAdminDashboard userIsAdmin />);
    const kpi = await screen.findByTestId('pipeline-kpi');
    await vi.waitFor(() => expect(within(kpi).getByText('$98,765 (partial)')).toBeTruthy());
    expect(screen.getByTestId('customer-pipeline-line-1').textContent).toBe('Pipeline: $98,765');
  });

  it('honest null state when the pipeline block is absent', async () => {
    impactFn.mockResolvedValue(noPipeline);
    render(<HomeDashboard onNavigate={() => undefined} isAdmin />);
    const kpi = await screen.findByTestId('pipeline-kpi');
    expect(kpi.textContent).toContain('Not recorded');
    expect(kpi.textContent).not.toContain('$0');
    expect((await screen.findAllByText('1,500 (currency not recorded)')).length).toBeGreaterThan(0);
    expect(screen.getByTestId('customer-pipeline-line-1').textContent).toBe('Pipeline: Not recorded');
  });
});

describe('H3 renewals KPI + per-row line (same portfolio payload, no new request)', () => {
  const zero = { overdue: 0, within_30: 0, within_60: 0, within_90: 0, within_180: 0, beyond_180: 0, unknown_date: 0 };
  const grp = (o: object) => ({ total: null, coverage: 'no_data', lines_included: 0, lines_excluded: 0, ...o });
  const withRenewals = {
    ...withPipeline,
    customers: [
      { ...withPipeline.customers[0], renewals: { counts: { ...zero, overdue: 1, within_30: 1 }, acv_exposure: 5000, next_renewal: '2026-11-15' } },
      { ...withPipeline.customers[1], renewals: { counts: zero, acv_exposure: null, next_renewal: null } },
    ],
    renewals: {
      calculation_version: 'pipeline-renewal/1', as_of: 'x', reference_date: '2026-10-27',
      accounts_scoped: 2, accounts_with_renewal_evidence: 1, accounts_no_data: 1,
      counts: { ...zero, overdue: 1, within_30: 1, within_90: 2, unknown_date: 1 },
      exposure: { acv: grp({ total: 5000, coverage: 'quantified', lines_included: 2 }), tcv: grp({ coverage: 'all_unknown', lines_excluded: 2 }) },
      next_renewals: [{ customer_id: 1, customer_name: 'Acme', opportunity_number: '123', renewal_date: '2026-11-15', days: 19 }],
    },
  };

  it('HomeDashboard: KPI after the pipeline KPI + per-customer lines; pipeline KPI untouched', async () => {
    impactFn.mockResolvedValue(withRenewals);
    render(<HomeDashboard onNavigate={() => undefined} isAdmin />);
    const kpi = await screen.findByTestId('renewals-kpi');
    expect(kpi.textContent).toContain('Renewals — vendor-reported');
    expect(kpi.textContent).toContain('1 overdue · 1 in 30d · 2 in 90d+ · 1 unknown date');
    expect(kpi.textContent).toContain('Est. ACV exposure $5,000');
    expect(kpi.textContent).toContain('Next: Acme Nov 15, 2026');
    expect(screen.getByTestId('pipeline-kpi').textContent).toContain('$98,765');
    expect(screen.getByTestId('customer-renewals-line-1').textContent).toBe('Renewals: 1 overdue · next Nov 15, 2026');
    expect(screen.getByTestId('customer-renewals-line-2').textContent).toBe('Renewals: —');
    expect(screen.getByTestId('customer-pipeline-line-1').textContent).toBe('Pipeline: $98,765');
  });

  it('Dashboard with personal tasks: KPI + per-customer line', async () => {
    impactFn.mockResolvedValue(withRenewals);
    render(<HomeDashboard username="tester" isAdmin={false} onNavigate={() => undefined} />);
    const kpi = await screen.findByTestId('renewals-kpi');
    await vi.waitFor(() => expect(kpi.textContent).toContain('1 overdue · 1 in 30d'));
    expect(screen.getByTestId('customer-renewals-line-1').textContent).toBe('Renewals: 1 overdue · next Nov 15, 2026');
  });

  it('honest empty state when renewals are absent', async () => {
    impactFn.mockResolvedValue(withPipeline);
    render(<HomeDashboard onNavigate={() => undefined} isAdmin />);
    const kpi = await screen.findByTestId('renewals-kpi');
    expect(kpi.textContent).toContain('No renewal evidence recorded');
    expect(kpi.textContent).not.toContain('$0');
    expect((await screen.findByTestId('customer-renewals-line-1')).textContent).toBe('Renewals: —');
  });
});
