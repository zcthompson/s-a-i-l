/**
 * Regression tests for F1 (WP23 [P0]): customer-detail cross-view buttons
 * dead-end or open the WRONG use case (WP23a step 0 — RED-first).
 *
 * Reported behavior (pre-fix, captured by these tests):
 * Customer Overview → click a use case → detail tab:
 *   - "📊 View Scoring Breakdown" → onNavigate('scoring-dashboard') WITHOUT
 *     handing the locally-selected use case up to Home → Home renders the
 *     dead-end "Please select a use case from the list to view scoring results."
 *   - "🔍 Score Drill-Down" → onNavigate('scoring-drilldown') without a
 *     selection → falls through to "Select a section from the sidebar".
 *   - "💬 Open Comments" → onNavigate('collab-comments') without a selection
 *     → Home auto-selects the FIRST globally accessible use case — possibly
 *     a different use case (even a different customer's) than the one the
 *     user was just looking at.
 *
 * The fix (WP23a step 0): the shared UseCaseDetail component's callbacks hand
 * the use case up to Home (setSelectedUseCase + setView) before/with the view
 * change, so each surface renders FOR THAT use case.
 *
 * RED proof: these tests are written BEFORE the fix and fail on current code.
 * Mutation note: the "other" use case (id 90) is returned FIRST by api.list,
 * so the auto-select bug lands on a DIFFERENT title — the assertion is a real
 * handoff check, not a tautology.
 */
import { describe, it, expect, vi, afterEach, beforeAll, afterAll } from 'vitest';
import { render, screen, cleanup, fireEvent, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { Home } from '../src/pages/Home';

beforeAll(() => {
  if (typeof Element !== 'undefined' && !Element.prototype.scrollTo) {
    Element.prototype.scrollTo = function () { return undefined; };
  }
});

// Two use cases: the one the user selects in the customer Overview (id 68)
// and a DIFFERENT one (id 90, another customer) that api.list returns FIRST —
// the pre-fix auto-select bug lands on id 90, which is how the test proves
// the thread/surface shown is the one the user actually selected.
const { state, customer, seededUc, otherUc } = vi.hoisted(() => {
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
    status: 'active',
    goals: ['Improve operational efficiency'],
    challenges: ['Manual hand-offs between teams'],
    pain_points: ['Bottlenecks cascade'],
    impact_category: null,
    impact_description: null,
    estimated_savings: 120000,
    estimated_revenue: 40000,
    timeline_estimate: '2 quarters',
    scores: null,
    overall_score: 72.5,
    scored_at: '2026-08-30T10:00:00Z',
    created_at: '2026-08-29T01:08:50Z',
    updated_at: '2026-08-29T01:08:50Z',
    created_by: 'admin',
    assessment_id: 9,
    assessment_name: 'Energy Test Company — Assessment 1',
  };
  const otherUc = {
    ...seededUc,
    id: 90,
    title: 'Other customer use case',
    customer_id: 3,
    customer_name: 'Acme Corp',
    department: 'Logistics',
    department_id: 12,
    overall_score: 41.0,
  };
  const state = { drillDownCalls: [] as number[] };
  return { state, customer, seededUc, otherUc };
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
    // FIRST accessible use case is the OTHER customer's — the pre-fix
    // auto-select (collab-comments with no selection) lands on id 90.
    list: () => Promise.resolve([otherUc, seededUc]),
    getComments: () => Promise.resolve([]),
    // Keep the drill-down fetch pending: the "Loading drill-down..." surface
    // is the deterministic proof the drill-down view was reached, and the
    // recorded id proves WHICH use case was handed over.
    drillDown: (id: number) => {
      state.drillDownCalls.push(id);
      return new Promise(() => {});
    },
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
  getAuthIsAdmin: () => false,
  getAuthSalesRole: () => null,
}));
vi.mock('../src/lib/websocket', () => ({
  ws: { connect: vi.fn(), disconnect: vi.fn(), subscribe: vi.fn() },
}));

afterEach(() => {
  cleanup();
  state.drillDownCalls = [];
});

afterAll(() => {
  vi.unstubAllGlobals();
});

// Drive the real app path to the customer detail tab: My Customers → select
// the stub customer → Overview → click the use case row (detail tab).
// NOTE: the detail-tab buttons carry the generic aria-label
// "Customer dashboard action" (WP23 F11 — fixed in WP23g), so the visible
// text (not the accessible name) is the probe, scoped to the section that
// contains them.
// CHANGELOG 0.1.0 U4 — navigation is now two-level (primary areas + per-area
// secondary rail). Helpers drive the real SegmentedNav tabs.
const primaryTab = (label: string) => screen.getByRole('tab', { name: `Navigate to ${label}` });

async function openUseCaseDetail() {
  const customerRow = await screen.findByRole('button', { name: 'Select customer Energy Test Company' });
  fireEvent.click(customerRow);
  fireEvent.click(await screen.findByRole('tab', { name: 'Navigate to Discovery & Value' }));
  fireEvent.click(primaryTab('Use Cases'));
  const row = await screen.findByRole('button', { name: 'Open assessment Improve operational efficiency' });
  fireEvent.click(row);
  // The detail tab's h1 is the deterministic probe (the tab renders on the
  // selected use case).
  const h1 = await screen.findByRole('heading', { level: 1, name: 'Improve operational efficiency' });
  void h1;
  // The Scoring section (rendered because the stub use case has a score).
  const scoringSection = screen.getByText('Scoring').closest('div')!;
  return scoringSection;
}

function renderApp() {
  render(
    <MemoryRouter initialEntries={['/?view=customers']}>
      <Home />
    </MemoryRouter>,
  );
}

describe('F1 — customer-detail cross-view handoff (WP23a step 0)', () => {
  it('View Scoring Breakdown reaches the scoring surface for that use case (no dead-end)', async () => {
    renderApp();
    const section = await openUseCaseDetail();
    fireEvent.click(within(section).getByText('📊 View Scoring Breakdown'));
    // Post-fix: the scoring-dashboard surface for the selected use case
    // renders (the unscored-by-AI "unavailable" state is the honest surface
    // for a case without stored dimension scores — the dead-end must be gone).
    expect(await screen.findByText(/Scoring results are unavailable\.|Scoring Results/)).toBeTruthy();
    expect(screen.queryByText('Please select a use case from the list to view scoring results.')).toBeNull();
  });

  it('Open Comments shows THAT use case thread, not the first accessible use case', async () => {
    renderApp();
    await openUseCaseDetail();
    // The 💬 comment button lives in the detail tab's Comments section
    // (below Scoring); its visible text is unique on the page.
    fireEvent.click(screen.getByText('💬 Open Comments'));
    // Post-fix: the thread is the selected use case's (id 68). Pre-fix the
    // auto-select effect picks api.list[0] (id 90, "Other customer use case").
    await screen.findByText('💬 Comments & Collaboration — Improve operational efficiency');
    expect(screen.queryByText('💬 Comments & Collaboration — Other customer use case')).toBeNull();
  });

  it('Score Drill-Down drills into THAT use case', async () => {
    renderApp();
    const section = await openUseCaseDetail();
    fireEvent.click(within(section).getByText('🔍 Score Drill-Down'));
    // Post-fix: the drill-down view is reached with the selected use case's id.
    await screen.findByText('Loading drill-down...');
    expect(state.drillDownCalls).toEqual([seededUc.id]);
    expect(screen.queryByText('Select a section from the sidebar')).toBeNull();
  });
});
