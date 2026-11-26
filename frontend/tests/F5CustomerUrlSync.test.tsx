/**
 * Regression tests (F5 — refresh/back lost the customer
 * context; the selection was component-local + a transient Home prop, and
 * the URL carried only ?view=):
 *
 *   - deep link ?view=customers&customer=X restores the customer's
 *     dashboard on load (the reported refresh pain);
 *   - in-page customer selection writes ?customer= (a restorable
 * Back/Forward history step — the invariant);
 *   - an EXTERNAL URL change (browser Back) applies the previous customer
 *     state (the URL→customer direction, guarded against re-applying
 * internal writes per the one-direction rule).
 *
 * The view/URL regression tests (HomeUrlSync,
 * CustomerEditOscillation) are the oscillation guard and must keep
 * passing — they run in the same suite.
 */
import { describe, it, expect, vi, afterEach, beforeAll } from 'vitest';
import { render, screen, cleanup, fireEvent, act } from '@testing-library/react';
import { useEffect } from 'react';
import { MemoryRouter, useLocation, useNavigate } from 'react-router-dom';
import { Home } from '../src/pages/Home';

beforeAll(() => {
  if (typeof Element !== 'undefined' && !Element.prototype.scrollTo) {
    Element.prototype.scrollTo = function () { return undefined; };
  }
});

const { customer, seededUc } = vi.hoisted(() => {
  const customer = {
    id: 7,
    name: 'Energy Test Company',
    description: 'Customer created during testing',
    vertical: 'Energy & Utilities',
    created_at: '2026-08-29T01:08:44Z',
    updated_at: '2026-08-29T01:08:44Z',
    use_case_count: 1,
    departments: ['Operations'],
    total_impact: 0,
  };
  const seededUc = {
    id: 68,
    title: 'Improve operational efficiency',
    description: 'Streamline core operational workflows.',
    customer_id: 7,
    customer_name: 'Energy Test Company',
    department_id: 61,
    department: 'Operations',
    status: 'draft',
    goals: ['x'],
    challenges: [],
    pain_points: [],
    estimated_savings: null,
    estimated_revenue: null,
    timeline_estimate: null,
    scores: null,
    overall_score: null,
    scored_at: null,
    created_at: '2026-08-29T01:08:50Z',
    updated_at: '2026-08-29T01:08:50Z',
    created_by: 'admin',
    assessment_id: 9,
    assessment_name: 'Energy Test Company — Assessment 1',
  };
  return { customer, seededUc };
});

const { apiStub } = vi.hoisted(() => {
  const methods: Record<string, (...args: any[]) => Promise<any>> = {
    listCustomers: () => Promise.resolve([customer]),
    getCustomer: () => Promise.resolve({ ...customer, use_case_count: 1 }),
    getCustomerUseCases: () => Promise.resolve([seededUc]),
    listVerticals: () => Promise.resolve({ verticals: [], departments_by_vertical: {} }),
    listDepartments: () => Promise.resolve([]),
    listAssessments: () => Promise.resolve([]),
    checkAccess: () => Promise.resolve({ has_access: true, permission_level: 'owner' }),
    getNotifications: () => Promise.resolve([]),
    getMyCustomers: () => Promise.resolve([]),
    list: () => Promise.resolve([seededUc]),
    getComments: () => Promise.resolve([]),
    get: (id: number) => Promise.resolve({ ...seededUc, id }),
    score: () => Promise.resolve({ use_case: seededUc, scores: { dimension_scores: [], overall_score: 0, reasoning: null, scored_at: null, recommendations: [] } }),
  };
  const fallback = () => Promise.resolve([]);
  const stub: any = new Proxy({}, {
    get: (_t, prop) => (typeof prop === 'string' && methods[prop] ? methods[prop] : fallback),
  });
  return { apiStub: stub };
});

vi.mock('../src/lib/api', () => ({
  api: apiStub,
  clearAuth: vi.fn(),
  getAuthUsername: () => 'admin',
  getAuthIsAdmin: () => false,
  getAuthSalesRole: () => null,
}));
vi.mock('../src/lib/websocket', () => ({
  ws: { connect: vi.fn(), disconnect: vi.fn(), subscribe: vi.fn(() => vi.fn()) },
}));

afterEach(() => {
  cleanup();
  delete (window as any).__f5Navigate;
});

function UrlProbe() {
  const location = useLocation();
  return <span data-testid="url">{location.search}</span>;
}

function NavProbe() {
  const navigate = useNavigate();
  useEffect(() => {
    (window as any).__f5Navigate = navigate;
  }, [navigate]);
  return null;
}

describe('F5 — customer-selection URL sync', () => {
  it('deep link ?view=customers&customer=X restores the customer dashboard on load', async () => {
    render(
      <MemoryRouter initialEntries={['/?view=customers&customer=Energy%20Test%20Company']}>
        <Home />
        <UrlProbe />
      </MemoryRouter>,
    );
    await screen.findByRole('heading', { level: 1, name: /Energy Test Company/ }, { timeout: 5000 });
    const url = document.querySelector('[data-testid="url"]')!.textContent!;
    expect(url).toContain('customer=Energy%20Test%20Company');
  });

  it('in-page customer selection writes ?customer= (restorable history step)', async () => {
    render(
      <MemoryRouter initialEntries={['/?view=customers']}>
        <Home />
        <UrlProbe />
      </MemoryRouter>,
    );
    const row = await screen.findByRole('button', { name: 'Select customer Energy Test Company' });
    fireEvent.click(row);
    await screen.findByRole('heading', { level: 1, name: /Energy Test Company/ });
    // URLSearchParams serializes spaces as '+' — assert the DECODED values
    // (the param round-trips identically either way).
    const params = new URLSearchParams(document.querySelector('[data-testid="url"]')!.textContent!);
    expect(params.get('view')).toBe('customers');
    expect(params.get('customer')).toBe('Energy Test Company');
  });

  it('browser Back (external URL change) clears the selection back to the list', async () => {
    render(
      <MemoryRouter initialEntries={['/?view=customers']}>
        <Home />
        <UrlProbe />
        <NavProbe />
      </MemoryRouter>,
    );
    const row = await screen.findByRole('button', { name: 'Select customer Energy Test Company' });
    fireEvent.click(row);
    await screen.findByRole('heading', { level: 1, name: /Energy Test Company/ });
    let params = new URLSearchParams(document.querySelector('[data-testid="url"]')!.textContent!);
    expect(params.get('customer')).toBe('Energy Test Company');
    // Browser Back → the previous history entry (?view=customers, no
    // customer) → the external URL change clears the selection: the
    // left panel (customer list) returns.
    await act(async () => {
      (window as any).__f5Navigate(-1);
    });
    await screen.findByText('1 of 1 accounts match');
    params = new URLSearchParams(document.querySelector('[data-testid="url"]')!.textContent!);
    expect(params.get('customer')).toBeNull();
  });
});
