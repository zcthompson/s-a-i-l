/**
 * admin deep links render a fail-closed denied state
 * for non-admins instead of controls that 403 on click.
 *
 *  - `?view=admin*` (AdminPage) and `?view=admin-integrations`
 *    (IntegrationSettings) render "Administrator access required" for
 *    non-admins; admins see the real pages.
 *  - `?view=customer-create` renders the denied state for non-admins
 *    (POST /api/customers/ is admin-only on the server).
 *  - The sidebar hides the 'New Customer' entry from non-admins.
 *
 * Conventions: repo test pattern (vi.hoisted + vi.mock factory), jsdom.
 */
import { describe, it, expect, vi, afterEach, beforeEach } from 'vitest';
import { render, screen, cleanup, within } from '@testing-library/react';

const { authState, apiStub } = vi.hoisted(() => {
  const authState = { isAdmin: false, salesRole: null as string | null };
  const apiMethods: Record<string, (...a: any[]) => Promise<unknown>> = {
    getCustomersStats: () => Promise.resolve({
      total_customers: 0, total_use_cases: 0, total_scored: 0, average_score: 0,
      total_savings: 0, total_revenue: 0, total_impact: 0, customers: [],
    }),
    getPortfolioAccountImpact: () => Promise.resolve({
      customer_count: 0, as_of: null, calculation_version: 'account-impact/2',
      coverage: 'no_data', scope: 'All authorized customers',
      total_impact: null, rollup: { quantified: 0, partial: 0, not_quantified: 0 }, customers: [],
    }),
    getMyCustomers: () => Promise.resolve([]),
    listCustomers: () => Promise.resolve([]),
    getGlobalAdminStats: () => Promise.resolve({ total_customers: 0, total_users: 0, customers: [] }),
    listAllThirdPartyServices: () => Promise.resolve([]),
    listPendingUsers: () => Promise.resolve([]),
    listAllUsers: () => Promise.resolve([]),
    listVerticals: () => Promise.resolve({ verticals: [], departments_by_vertical: {} }),
  };
  const apiStub = new Proxy({}, {
    get: (_t, p) => (typeof p === 'string' && apiMethods[p] ? apiMethods[p] : () => Promise.resolve([])),
  });
  return { authState, apiStub };
});

vi.mock('../src/lib/api', () => ({
  api: apiStub,
  getAuthToken: () => 'test-token',
  clearAuth: () => undefined,
  getAuthUsername: () => 'tester',
  getAuthIsAdmin: () => authState.isAdmin,
  getAuthSalesRole: () => authState.salesRole,
  getAuthRole: () => 'user',
}));
vi.mock('../src/lib/websocket', () => ({
  ws: { subscribe: () => null, connect: () => undefined, disconnect: () => undefined },
}));
vi.mock('../src/components/AppHealthCard', () => ({ AppHealthCard: () => null }));
vi.mock('../src/components/AdminConsole', () => ({ AdminConsole: () => null }));

import { App } from '../src/App';
import { Sidebar } from '../src/components/Sidebar';

const sidebarProps = {
  activeView: 'customers',
  onNavigate: () => undefined,
  username: 'tester',
  onLogout: () => undefined,
  isCollapsed: false,
  onToggle: () => undefined,
};

function renderAt(view: string) {
  window.history.replaceState({}, '', `/?view=${view}`);
  return render(<App />);
}

afterEach(() => {
  cleanup();
  window.history.replaceState({}, '', '/');
});

// jsdom does not implement Element.scrollTo — the app's scroll-restore
// effect calls it on mount; real browsers have it.
beforeEach(() => {
  HTMLElement.prototype.scrollTo = vi.fn();
});

describe('F19 — admin deep links fail closed for non-admins', () => {
  it('non-admin ?view=admin-users -> denied state, no Admin Dashboard', async () => {
    authState.isAdmin = false;
    renderAt('admin-users');
    expect(await screen.findByRole('alert')).toBeTruthy();
    expect(screen.getByText('Administrator access required')).toBeTruthy();
    expect(screen.queryByText('Admin Dashboard')).toBeNull();
  });

  it('non-admin ?view=admin-integrations -> denied state, no settings form', async () => {
    authState.isAdmin = false;
    renderAt('admin-integrations');
    expect(await screen.findByText('Administrator access required')).toBeTruthy();
    expect(screen.queryByText('Admin Dashboard')).toBeNull();
  });

  it('non-admin ?view=customer-create -> denied state, no create form', async () => {
    authState.isAdmin = false;
    renderAt('customer-create');
    expect(await screen.findByText('Administrator access required')).toBeTruthy();
    expect(screen.queryByRole('button', { name: 'Create customer' })).toBeNull();
  });

  it('sales manager ?view=customer-create -> prospect form with the review note', async () => {
    authState.isAdmin = false;
    authState.salesRole = 'sales_manager';
    try {
      renderAt('customer-create');
      expect(await screen.findByRole('heading', { name: 'New Prospect' })).toBeTruthy();
      expect(screen.getByTestId('prospect-review-note').textContent).toContain('administrator reviews new prospects');
      expect(screen.getByRole('button', { name: 'Create customer' })).toBeTruthy();
      expect(screen.queryByText('Administrator access required')).toBeNull();
    } finally {
      authState.salesRole = null;
    }
  });

  it('admin ?view=admin-users -> the real Admin Dashboard renders', async () => {
    authState.isAdmin = true;
    renderAt('admin-users');
    expect(await screen.findByText('Admin Dashboard')).toBeTruthy();
    expect(screen.queryByText('Administrator access required')).toBeNull();
  });

  it('denied state offers a back-to-dashboard action', async () => {
    authState.isAdmin = false;
    renderAt('admin-users');
    expect(await screen.findByRole('button', { name: 'Back to dashboard' })).toBeTruthy();
  });
});

describe('F19 — sidebar hides the admin-only New Customer entry', () => {
  it('non-admin: My Customers visible, New Customer hidden', () => {
    const { container } = render(
      <Sidebar {...sidebarProps} is_admin={false} userRole="rep" />
    );
    const nav = container.querySelector('nav');
    expect(nav).toBeTruthy();
    const navArea = within(nav as HTMLElement);
    expect(navArea.getAllByText('My Customers').length).toBeGreaterThan(0);
    expect(navArea.queryByText('New Customer')).toBeNull();
  });

  it('sales manager: the create entry is labelled New Prospect', () => {
    const { container } = render(
      <Sidebar {...sidebarProps} is_admin={false} userRole="user" canCreateProspects />
    );
    const navArea = within(container.querySelector('nav') as HTMLElement);
    expect(navArea.getByText('New Prospect')).toBeTruthy();
    expect(navArea.queryByText('New Customer')).toBeNull();
  });

  it('admin: both entries visible', () => {
    const { container } = render(
      <Sidebar {...sidebarProps} is_admin={true} userRole="user" />
    );
    const nav = container.querySelector('nav');
    expect(nav).toBeTruthy();
    const navArea = within(nav as HTMLElement);
    expect(navArea.getAllByText('My Customers').length).toBeGreaterThan(0);
    expect(navArea.getByText('New Customer')).toBeTruthy();
  });
});
