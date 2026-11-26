/**
 * Regression tests for WP23a steps 4-5 (CustomerDashboard):
 *
 * F10 [P1]: Bulk Score's Back evicted the customer
 *   (setCustomerUseCases([]) + setSelectedCustomer(null) → "Select a
 *   Customer"). Now: the customer stays selected, the Overview tab shows,
 *   and the use cases are refetched (fresh scores visible on return).
 * F12 [P1]: one transient API failure replaced the WHOLE customer view
 *   with a page-reload Retry (window.location.reload() — selection, tab,
 *   and round input lost). Now: an inline banner with a Retry that
 *   re-runs the same load; round create/archive failures are inline in
 *   the Assessment Rounds card (local roundError state).
 */
import { describe, it, expect, vi, afterEach, beforeAll } from 'vitest';
import { render, screen, cleanup, fireEvent } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { CustomerDashboard } from '../src/pages/CustomerDashboard';

beforeAll(() => {
  if (typeof Element !== 'undefined' && !Element.prototype.scrollTo) {
    Element.prototype.scrollTo = function () { return undefined; };
  }
});

const { state, customer, seededUc } = vi.hoisted(() => {
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
  const state = {
    getCustomerCalls: 0,
    getCustomerShouldFail: false,
    ucListCalls: 0,
    createAssessmentShouldFail: false,
    wsHandlers: [] as Array<(m: { type: string; data: unknown; timestamp: string }) => void>,
  };
  return { state, customer, seededUc };
});

const { apiStub } = vi.hoisted(() => {
  const methods: Record<string, (...args: any[]) => Promise<any>> = {
    getWorkspaceActions: (id: number) => Promise.resolve({ customer_id: id, capabilities: { use_case: true, assessment: true }, assignees: [] }),
    listCustomers: () => Promise.resolve([customer]),
    getCustomer: () => {
      state.getCustomerCalls += 1;
      if (state.getCustomerShouldFail) return Promise.reject(new Error('Customer load failed'));
      return Promise.resolve({ ...customer, use_case_count: 1 });
    },
    getCustomerUseCases: () => {
      state.ucListCalls += 1;
      return Promise.resolve([seededUc]);
    },
    listVerticals: () => Promise.resolve({ verticals: [], departments_by_vertical: {} }),
    listDepartments: () => Promise.resolve([]),
    listAssessments: () => Promise.resolve([]),
    checkAccess: () => Promise.resolve({ has_access: true, permission_level: 'owner' }),
    getNotifications: () => Promise.resolve([]),
    getMyCustomers: () => Promise.resolve([]),
    list: () => Promise.resolve([seededUc]),
    getComments: () => Promise.resolve([]),
    score: () => Promise.resolve({ use_case: seededUc, scores: { dimension_scores: [], overall_score: 0, reasoning: null, scored_at: null, recommendations: [] } }),
    bulkScore: () => Promise.resolve({ scored: 0, failed: 0 }),
    createAssessment: (name: string) => {
      if (state.createAssessmentShouldFail) return Promise.reject(new Error('Round create failed'));
      return Promise.resolve({ id: 10, name: String(name), status: 'active', use_case_count: 0, created_at: '2026-09-01T00:00:00Z' });
    },
    archiveAssessment: () => Promise.resolve({ id: 10, name: 'Q4 2026', status: 'archived', use_case_count: 0, created_at: '2026-09-01T00:00:00Z' }),
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
  ws: {
    connect: vi.fn(),
    disconnect: vi.fn(),
    subscribe: vi.fn((_type: string, handler: (m: { type: string; data: unknown; timestamp: string }) => void) => {
      state.wsHandlers.push(handler);
      return vi.fn();
    }),
  },
}));

afterEach(() => {
  cleanup();
  state.getCustomerCalls = 0;
  state.getCustomerShouldFail = false;
  state.ucListCalls = 0;
  state.createAssessmentShouldFail = false;
  state.wsHandlers = [];
});

function renderDashboard() {
  // The selectedCustomerName prop drives the mount-time load (the
  // MyDashboard deep-link path) — the same refetch Retry re-runs.
  render(
    <MemoryRouter initialEntries={['/?view=customers']}>
      <CustomerDashboard onNavigate={vi.fn()} selectedCustomerName="Energy Test Company" />
    </MemoryRouter>,
  );
}

describe('F10 + F12 — customer view resiliency (WP23a steps 4-5)', () => {
  it('F10: Bulk Score Back keeps the customer and refetches the use cases', async () => {
    renderDashboard();
    await screen.findByRole('heading', { level: 1, name: /Energy Test Company/ });
    const ucCallsBeforeMount = state.ucListCalls;
    // Open the bulk-score section via the two-level navigation (CHANGELOG 0.1.0
    // U4): Assessments primary area, then the Bulk Score secondary.
    fireEvent.click(screen.getByRole('tab', { name: 'Navigate to Discovery & Value' }));
    fireEvent.click(screen.getByRole('tab', { name: 'Navigate to Bulk Score' }));
    await screen.findByText('← Back');
    // BulkScore fetches the use cases itself on mount — capture AFTER that
    // so the assertion isolates the onBack refetch (the F10 behavior).
    const ucCallsAfterBulkMount = state.ucListCalls;
    expect(ucCallsAfterBulkMount).toBeGreaterThan(ucCallsBeforeMount);
    fireEvent.click(screen.getByText('← Back'));
    // The customer is still selected (back on the Assessments area) and the
    // use-case list was refetched (fresh scores visible on return).
    // CHANGELOG 0.1.0 U7: the emoji is dropped and the Rounds area is one
    // consolidated card — the heading is the deterministic probe.
    await screen.findByText('Assessment Rounds', { selector: 'h2' });
    expect(screen.getByRole('heading', { level: 1, name: /Energy Test Company/ })).toBeTruthy();
    expect(state.ucListCalls).toBe(ucCallsAfterBulkMount + 1);
  });

  it('F12: a load failure is an inline banner with Retry (the view stays mounted)', async () => {
    state.getCustomerShouldFail = true;
    renderDashboard();
    // The banner shows the real reason, and the view is NOT unmounted
    // (pre-fix the whole component was replaced by the reload banner).
    await screen.findByText('Customer load failed');
    expect(screen.getByText('Select a Customer')).toBeTruthy();
    // Retry re-runs the same load (2nd call) and recovers.
    const callsBeforeRetry = state.getCustomerCalls;
    state.getCustomerShouldFail = false; // the retry succeeds
    fireEvent.click(screen.getByRole('button', { name: 'Retry loading customer dashboard' }));
    await screen.findByRole('heading', { level: 1, name: /Energy Test Company/ });
    expect(state.getCustomerCalls).toBe(callsBeforeRetry + 1);
  });

  it('F12: a round-create failure is inline in the rounds card (the view stays mounted)', async () => {
    state.createAssessmentShouldFail = true;
    renderDashboard();
    await screen.findByRole('heading', { level: 1, name: /Energy Test Company/ });
    // Navigate the two-level nav (CHANGELOG 0.1.0 U4): Assessments area, then the
    // Rounds secondary (it is the default rail item).
    fireEvent.click(screen.getByRole('tab', { name: 'Navigate to Discovery & Value' }));
    await screen.findByText("No assessment rounds yet. Create a discovery or AI readiness round to organize this customer's needs and use cases.");
    fireEvent.click(screen.getByText('New assessment round', { selector: 'summary' }));
    fireEvent.change(screen.getByPlaceholderText('Round name (e.g. Q4 2026)'), { target: { value: 'Q4 2026' } });
    // Part 13 WS5 (R8): the round type is an explicit choice (no silent default).
    fireEvent.click(screen.getByLabelText('AI readiness assessment (dimension scoring, forecasts, readiness insight)'));
    fireEvent.click(screen.getByText('+ New Round'));
    // Inline error in the rounds card — no full-view reload banner.
    await screen.findByText('Round create failed');
    expect(screen.getByRole('heading', { level: 1, name: /Energy Test Company/ })).toBeTruthy();
  });
});
