// Regression tests for the admin subview wiring (user report,
// 2026-08-31):
//
// 1. Sidebar navigation between the admin subviews (Pending Approvals /
//    All Users) must switch the AdminPage tab. The old code kept a local
//    tab state in AdminPage seeded from the prop at mount only — Home
//    serves ONE <AdminPage> element for every admin-* view, so the
//    instance survives the view change and the stale tab stuck (the
//    reported bug: sidebar All Users -> Pending stayed on All Users).
//    AdminPage is now a pure function of the parent view.
//
// 2. The in-page tabs must write their view into the URL (?view= param),
// Per the invariant that every in-app navigation is a
//    restorable history step — previously the tabs were local-only, so a
//    refresh restored the URL's tab instead of the visible one.
import { describe, it, expect, vi, afterEach, beforeAll } from 'vitest';
import { render, screen, cleanup, fireEvent } from '@testing-library/react';
import { MemoryRouter, useLocation } from 'react-router-dom';
import { Home } from '../src/pages/Home';

// jsdom implements window.scrollTo only — Element.scrollTo (used by the
// view-change scroll reset in Home.tsx) is not a function there. Stub a
// no-op so the component is exercisable; real browsers implement it.
beforeAll(() => {
  if (typeof Element !== 'undefined' && !Element.prototype.scrollTo) {
    Element.prototype.scrollTo = function () { return undefined; };
  }
});

// Home pulls api/ws at module scope and in mount effects; stub both. The
// api stub resolves every method with [] EXCEPT: the stats endpoints
// (HomeDashboard renders with a full StatsResponse shape) and the two
// admin user endpoints (AdminPage renders the All Users table from
// getAllUsers; getPendingUsers stays empty so the pending tab shows the
// "No pending users" empty state the user's report names).
const { apiStub } = vi.hoisted(() => {
  const statsShape = {
    total_use_cases: 0,
    average_score: 0,
    by_department: {},
    by_status: {},
    impact_summary: { total_impact: 0, total_savings: 0, total_revenue: 0 },
    top_use_cases: [],
  };
  const user = {
    id: 7,
    username: 'cb_member',
    email: 'cb_member@example.com',
    display_name: 'CB Member',
    department: 'Ops',
    role: 'user',
    is_admin: 0,
    approved: 1,
    created_at: '2026-08-01T00:00:00Z',
    is_active: 1,
  };
  const methods: Record<string, () => Promise<unknown>> = {
    aggregateStats: () => Promise.resolve(statsShape),
    getCustomersStats: () => Promise.resolve(null),
    getPendingUsers: () => Promise.resolve([]),
    getAllUsers: () => Promise.resolve([user]),
  };
  const fallback = () => Promise.resolve([]);
  const stub: any = new Proxy({}, {
    get: (_target, prop) => (typeof prop === 'string' && methods[prop] ? methods[prop] : fallback),
  });
  return { apiStub: stub };
});
vi.mock('../src/lib/api', () => ({
  api: apiStub,
  clearAuth: vi.fn(),
  getAuthUsername: () => 'admin',
  getAuthIsAdmin: () => true,
  getAuthSalesRole: () => null,
}));
vi.mock('../src/lib/websocket', () => ({
  ws: { connect: vi.fn(), disconnect: vi.fn(), subscribe: vi.fn() },
}));

afterEach(cleanup);

function UrlProbe() {
  const location = useLocation();
  return <span data-testid="url">{location.search}</span>;
}

const url = () => screen.getByTestId('url').textContent ?? '';

describe('Admin subview wiring', () => {
  it('sidebar Pending after sidebar All Users switches the tab and updates the URL (reported bug)', async () => {
    render(
      <MemoryRouter initialEntries={['/?view=admin-users']}>
        <Home />
        <UrlProbe />
      </MemoryRouter>
    );

    // Deep link seeded the view: the All Users table shows the user row
    // (loads async from the stubbed API).
    await screen.findByText('cb_member');
    expect(url()).toBe('?view=admin-users');

    // The reported sequence: already on All Users, click the sidebar's
    // Pending Approvals. The pending tab (empty state) must show and the
    // URL must track it. With the old local-tab-state code the table
    // stayed visible and the URL never moved.
    fireEvent.click(screen.getByRole('button', { name: 'Pending Approvals' }));
    expect(await screen.findByText('No pending users')).toBeTruthy();
    expect(url()).toBe('?view=admin-pending');

    // In-page tab switches must write the URL too (refresh restores the
    // visible tab, not a stale one).
    fireEvent.click(screen.getByRole('button', { name: 'Switch to All Users tab' }));
    await screen.findByText('cb_member');
    expect(url()).toBe('?view=admin-users');

    fireEvent.click(screen.getByRole('button', { name: 'Switch to Pending Approvals tab' }));
    expect(await screen.findByText('No pending users')).toBeTruthy();
    expect(url()).toBe('?view=admin-pending');
  });

  it('All Users actions render in full, including the Delete button', async () => {
    render(
      <MemoryRouter initialEntries={['/?view=admin-users']}>
        <Home />
        <UrlProbe />
      </MemoryRouter>
    );

    // The user row is not the current user ("admin"), so the full action
    // set renders. Every action button must be present in the DOM (the
    // clipping defect hid Delete behind a horizontal scroll on
    // laptop-sized viewports).
    await screen.findByText('cb_member');
    expect(screen.getByRole('button', { name: 'Edit user cb_member' })).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Reset password for cb_member' })).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Deactivate cb_member' })).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Delete user cb_member' })).toBeTruthy();
  });

  it('fresh entry via the Admin section header lands on Pending and the tab switch reaches All Users', async () => {
    render(
      <MemoryRouter initialEntries={['/']}>
        <Home />
        <UrlProbe />
      </MemoryRouter>
    );

    // Mount baseline on the dashboard.
    expect(url()).toBe('?view=dashboard');

    // Section header click navigates to the section's first child
    // (admin-pending) — the pending empty state shows and the URL tracks.
    fireEvent.click(screen.getByRole('button', { name: 'Admin' }));
    expect(await screen.findByText('No pending users')).toBeTruthy();
    expect(url()).toBe('?view=admin-pending');

    // Tab click reaches the All Users table.
    fireEvent.click(screen.getByRole('button', { name: 'Switch to All Users tab' }));
    await screen.findByText('cb_member');
    expect(url()).toBe('?view=admin-users');
  });
});
