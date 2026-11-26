/**
 * gcm-p5 — global surfaces are a customer/sales portfolio.
 * HomeDashboard / MyDashboard / GlobalAdminDashboard read the account-impact
 * contract, show "Not quantified" (never a fabricated 0) when there is no
 * comparable total, and carry no global use-case KPIs, readiness scores,
 * score bands, or assessment-centric quick actions.
 */
import { describe, it, expect, vi, afterEach, beforeEach } from 'vitest';
import { render, screen, cleanup, fireEvent } from '@testing-library/react';
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
import { HomeDashboard as MyDashboard } from '../src/pages/HomeDashboard';
import { GlobalAdminDashboard } from '../src/components/GlobalAdminDashboard';

const quantified = {
  customer_count: 2, as_of: 'x', calculation_version: 'account-impact/1', coverage: 'quantified',
  scope: 'All authorized customers',
  total_impact: { value: 1500, perspective: 'customer_benefit', realization_basis: 'estimated', currency: null },
  rollup: { quantified: 1, partial: 0, not_quantified: 1 },
  customers: [
    { customer_id: 1, customer_name: 'Acme', coverage: 'quantified', total_impact: 1500, can_score: true },
    { customer_id: 2, customer_name: 'Globex', coverage: 'not_quantified', total_impact: null },
  ],
};

beforeEach(() => { impactFn.mockReset(); });
afterEach(cleanup);

describe('gcm-p5 HomeDashboard', () => {
  it('reads account impact, labels scope, and has no use-case KPIs or assessment quick-actions', async () => {
    impactFn.mockResolvedValue(quantified);
    const onNavigate = vi.fn();
    render(<HomeDashboard onNavigate={onNavigate} isAdmin />);
    expect((await screen.findAllByText('1,500 (currency not recorded)')).length).toBeGreaterThan(0);
    expect(screen.getAllByText('Not quantified').length).toBeGreaterThan(0); // Globex, not "$0"
    expect(screen.getByText('Current portfolio scope: All authorized customers')).toBeTruthy();
    for (const gone of ['Use Cases', 'Avg Score', 'New Assessment', 'My Assessments',
      'Scoring Dashboard', 'Impact Matrix', 'Predictions', 'Business Impact',
      'Top Scoring Use Cases', 'Department Breakdown']) {
      expect(screen.queryByText(gone)).toBeNull();
    }
    fireEvent.click(screen.getByLabelText('Go to My Customers'));
    expect(onNavigate).toHaveBeenCalledWith('customers');
  });

  it('shows unavailable (not $0) when the contract is unavailable', async () => {
    impactFn.mockRejectedValue(new Error('boom'));
    render(<HomeDashboard onNavigate={() => undefined} />);
    expect((await screen.findAllByText('Unavailable')).length).toBeGreaterThan(0);
    expect(screen.queryByText('$0')).toBeNull();
  });
});

describe('gcm-p5 MyDashboard', () => {
  it('primary action is the customer portfolio; no global New Assessment / Templates', async () => {
    impactFn.mockResolvedValue(quantified);
    const onNavigate = vi.fn();
    render(<MyDashboard username="tester" isAdmin={false} onNavigate={onNavigate} />);
    expect(await screen.findByText('Customer Portfolio')).toBeTruthy();
    expect(screen.queryByText('New Assessment')).toBeNull();
    expect(screen.queryByText('Templates')).toBeNull();
    fireEvent.click(screen.getByLabelText('Go to My Customers'));
    expect(onNavigate).toHaveBeenCalledWith('customers');
    // customer-scoped scoring action is preserved
    fireEvent.click(screen.getByLabelText('Score Acme'));
    expect(onNavigate).toHaveBeenCalledWith('customers', 'Acme', 'bulk-score');
  });
});

describe('gcm-p5 GlobalAdminDashboard', () => {
  it('drops use-case counts, readiness and score bands; keeps customers, impact, users', async () => {
    impactFn.mockResolvedValue(quantified);
    render(<GlobalAdminDashboard userIsAdmin />);
    expect(await screen.findByText('Customer Portfolio')).toBeTruthy();
    for (const gone of ['Total Use Cases', 'Avg Readiness', 'Scored', 'Portfolio Readiness',
      'Portfolio Averages', 'Avg. Readiness Score', 'Strong (70+)']) {
      expect(screen.queryByText(gone)).toBeNull();
    }
    expect(screen.getByText('Total Customers')).toBeTruthy();
    expect(screen.getByText('Third-Party Services')).toBeTruthy();
  });
});
