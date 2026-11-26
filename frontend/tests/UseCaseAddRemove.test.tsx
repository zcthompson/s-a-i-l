/**
 * Regression tests for direct use-case add/remove in the customer Overview
 * (user report, 2026-09-01):
 *
 * The Overview use-case table was view-only — a use case could be viewed
 * and edited (row click → detail tab → Edit wizard) but NEITHER added NOR
 * removed from the customer view, even though the backend exposes full CRUD
 * at /api/use-cases/ with CustomerUser-junction authorization (create:
 * owner/member; delete: owner/admin — members get 403).
 *
 * The fix (frontend-only; backend untouched):
 *   - api.deleteUseCase → DELETE /api/use-cases/{id}/ (204)
 *   - "➕ Add Use Case" button + inline form in the Overview use-cases
 *     table header (enabled for owner/member/admin; disabled for
 *     auditor/none, matching the backend 403)
 *   - per-row "🗑️ Delete" (owner/admin only — the backend 403s members, so
 *     the affordance is hidden rather than shown-but-failing)
 *   - detail-tab "🗑️ Delete" beside the Edit button (same gate)
 *   - use-case list + customer aggregate refresh after both mutations so
 *     the "Total Use Cases" KPI stays live
 *
 * Mutation check: pre-fix, the "Add use case" and "Delete use case …"
 * affordances do not exist, so the presence/flow assertions below fail.
 */
import { describe, it, expect, vi, afterEach, beforeAll, afterAll } from 'vitest';
import { render, screen, cleanup, fireEvent } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { Home } from '../src/pages/Home';

// jsdom implements window.scrollTo only — Element.scrollTo (used by the
// view-change scroll reset in Home.tsx) is not a function there. Stub a
// no-op so the component is exercisable.
beforeAll(() => {
  if (typeof Element !== 'undefined' && !Element.prototype.scrollTo) {
    Element.prototype.scrollTo = function () { return undefined; };
  }
  // The delete affordance gates on window.confirm (consequence-stated
  // dialog). Auto-accept so the flow runs to the API call.
  vi.stubGlobal('confirm', vi.fn(() => true));
});

afterAll(() => {
  vi.unstubAllGlobals();
});

// Mutable stub state, hoisted so the vi.mock factory can reference it
// (same pattern as CustomerEditOscillation.test.tsx).
const { state, useCase, customer } = vi.hoisted(() => {
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
  const useCase = {
    id: 68,
    title: 'Improve operational efficiency',
    description: 'Streamline core operational workflows.',
    customer_id: 7,
    customer_name: 'Energy Test Company',
    department_id: 61,
    department: 'Operations',
    status: 'draft',
    goals: ['Improve operational efficiency'],
    challenges: ['Manual hand-offs between teams'],
    pain_points: ['Bottlenecks cascade'],
    impact_category: null,
    impact_description: null,
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
  const state: {
    role: string;
    denyWrites: boolean;
    useCases: Array<Record<string, unknown>>;
    deleteCalls: number[];
    createPayload: Record<string, unknown> | null;
  } = {
    role: 'owner',
    denyWrites: false,
    useCases: [useCase as unknown as Record<string, unknown>],
    deleteCalls: [],
    createPayload: null,
  };
  return { state, useCase, customer };
});

const { apiStub } = vi.hoisted(() => {
  const statsShape = {
    total_use_cases: 0,
    average_score: 0,
    by_department: {},
    by_status: {},
    impact_summary: { total_impact: 0, total_savings: 0, total_revenue: 0 },
    top_use_cases: [],
  };
  const methods: Record<string, (...args: any[]) => Promise<any>> = {
    getWorkspaceActions: (id: number) => Promise.resolve({ customer_id: id, capabilities: { use_case: !state.denyWrites && !['auditor', 'none'].includes(state.role), assessment: !state.denyWrites && !['auditor', 'none'].includes(state.role) }, assignees: [] }),
    aggregateStats: () => Promise.resolve(statsShape),
    getCustomersStats: () => Promise.resolve(null),
    listCustomers: () => Promise.resolve([customer]),
    getCustomer: () => Promise.resolve({ ...customer, use_case_count: state.useCases.length }),
    getCustomerUseCases: () => Promise.resolve(state.useCases),
    listVerticals: () => Promise.resolve({ verticals: [], departments_by_vertical: {} }),
    listDepartments: () => Promise.resolve([]),
    listAssessments: () => Promise.resolve([]),
    checkAccess: () => Promise.resolve({ has_access: true, permission_level: state.role }),
    getNotifications: () => Promise.resolve([]),
    getMyCustomers: () => Promise.resolve([]),
    list: () => Promise.resolve(state.useCases),
    create: (data: Record<string, unknown>) => {
      state.createPayload = data;
      const created = {
        ...useCase,
        id: 999,
        title: String(data.title),
        description: (data.description as string) ?? null,
        department: (data.department as string) ?? null,
        status: (data.status as string) ?? 'draft',
        created_at: '2026-09-01T12:00:00Z',
        updated_at: '2026-09-01T12:00:00Z',
      };
      state.useCases = [...state.useCases, created];
      return Promise.resolve(created);
    },
    deleteUseCase: (id: number) => {
      state.deleteCalls.push(id);
      state.useCases = state.useCases.filter((u) => u.id !== id);
      return Promise.resolve(undefined);
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
  state.denyWrites = false;
  cleanup();
  // Reset the mutable stub state between tests (fresh role + one seeded use case).
  state.role = 'owner';
  state.useCases = [useCase as unknown as Record<string, unknown>];
  state.deleteCalls = [];
  state.createPayload = null;
});

// Drive the real app path: My Customers → select the stub customer →
// Overview. Resolves once the Overview use-cases surface is up (the Add
// button in the table header is the deterministic probe).
async function openOverview() {
  const customerRow = await screen.findByRole('button', { name: 'Select customer Energy Test Company' }, { timeout: 5000 });
  fireEvent.click(customerRow);
  // the use-case working table lives under
  // Assessments ▸ Use Cases (it was removed from the Overview proper).
  // the primary tabs render only after the fail-closed access
  // check resolves — await the tab instead of asserting it synchronously.
  fireEvent.click(await screen.findByRole('tab', { name: 'Navigate to Discovery & Value' }));
  fireEvent.click(screen.getByRole('tab', { name: 'Navigate to Use Cases' }));
  await screen.findByText('Use Cases (1)');
  return screen.findByRole('button', { name: /Add use case/ });
}

describe('Use-case add/remove in the customer Overview', () => {
  it('owner sees the Add affordance and a per-row Delete (in an overflow menu, with an Actions column)', async () => {
    state.role = 'owner';
    render(
      <MemoryRouter initialEntries={['/?view=customers']}>
        <Home />
      </MemoryRouter>,
    );
    const addButton = await openOverview();
    expect(addButton).toBeTruthy();
    expect(addButton.hasAttribute('disabled')).toBe(false);
    // the per-row Delete is no longer a bare
    // button — it lives in a compact per-row overflow (RowActions) menu.
    expect(screen.getByRole('button', { name: `Actions for use case ${useCase.title}` })).toBeTruthy();
    expect(screen.getByRole('columnheader', { name: 'Actions' })).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: `Actions for use case ${useCase.title}` }));
    expect(screen.getByRole('menuitem', { name: `Delete use case ${useCase.title}` })).toBeTruthy();
  });

  it('member sees Add but NOT Delete (the backend 403s members on delete)', async () => {
    state.role = 'member';
    render(
      <MemoryRouter initialEntries={['/?view=customers']}>
        <Home />
      </MemoryRouter>,
    );
    const addButton = await openOverview();
    expect(addButton.hasAttribute('disabled')).toBe(false);
    // No per-row Delete affordance for members (backend 403s delete).
    expect(screen.queryByRole('button', { name: `Actions for use case ${useCase.title}` })).toBeNull();
    expect(screen.queryByRole('columnheader', { name: 'Actions' })).toBeNull();
  });

  it('auditor sees Add disabled and no Delete (read-only role)', async () => {
    state.role = 'auditor';
    render(
      <MemoryRouter initialEntries={['/?view=customers']}>
        <Home />
      </MemoryRouter>,
    );
    const addButton = await openOverview();
    expect(addButton.hasAttribute('disabled')).toBe(true);
    expect(screen.queryByRole('button', { name: `Actions for use case ${useCase.title}` })).toBeNull();
  });

  it('deleting a use case calls the API, removes the row, and reports the outcome', async () => {
    state.role = 'owner';
    render(
      <MemoryRouter initialEntries={['/?view=customers']}>
        <Home />
      </MemoryRouter>,
    );
    await openOverview();
    fireEvent.click(screen.getByRole('button', { name: `Actions for use case ${useCase.title}` }));
    fireEvent.click(screen.getByRole('menuitem', { name: `Delete use case ${useCase.title}` }));
    // The list refresh lands on the empty state (the customer has the one
    // seeded use case only) — proves the state was updated, not just the DOM.
    await screen.findByText('No use cases for this customer yet.');
    expect(state.deleteCalls).toEqual([useCase.id]);
    expect(screen.getByText('Use case deleted.')).toBeTruthy();
  });

  it('adding a use case calls the API with the customer id and renders the new row', async () => {
    state.role = 'owner';
    render(
      <MemoryRouter initialEntries={['/?view=customers']}>
        <Home />
      </MemoryRouter>,
    );
    const addButton = await openOverview();
    fireEvent.click(addButton);
    // Inline form appears under the table header.
    const titleInput = screen.getByLabelText('New use case title');
    fireEvent.change(titleInput, { target: { value: 'New efficiency use case' } });
    fireEvent.click(screen.getByRole('button', { name: 'Create use case' }));
    await screen.findByText('New efficiency use case');
    expect(state.createPayload).toMatchObject({
      title: 'New efficiency use case',
      customer_id: 7,
      status: 'draft',
    });
    expect(state.useCases).toHaveLength(2);
    expect(screen.getByText('Use case created.')).toBeTruthy();
  });

  it('the empty state keeps the Add affordance available (not a dead end)', async () => {
    state.role = 'member';
    state.useCases = [];
    render(
      <MemoryRouter initialEntries={['/?view=customers']}>
        <Home />
      </MemoryRouter>,
    );
    const customerRow = await screen.findByRole('button', { name: 'Select customer Energy Test Company' }, { timeout: 5000 });
    fireEvent.click(customerRow);
    // the table (and its empty state) live under
    // Assessments ▸ Use Cases.
    // await the tab — it renders after the access check resolves.
    fireEvent.click(await screen.findByRole('tab', { name: 'Navigate to Discovery & Value' }));
    fireEvent.click(screen.getByRole('tab', { name: 'Navigate to Use Cases' }));
    const emptyState = await screen.findByText('No use cases for this customer yet.');
    expect(emptyState).toBeTruthy();
    // The table-header Add button renders even with an empty list — the
    // empty state is not a dead end (F22 pattern).
    const addButton = screen.getByRole('button', { name: 'Add use case' });
    expect(addButton).toBeTruthy();
    expect(addButton.hasAttribute('disabled')).toBe(false);
  });
});


it('a legacy member cannot add or score when the account capability denies writes', async () => {
  state.role = 'member';
  state.denyWrites = true;
  render(<MemoryRouter initialEntries={['/?view=customers']}><Home /></MemoryRouter>);
  const add = await openOverview();
  expect(add.hasAttribute('disabled')).toBe(true);
  fireEvent.click(screen.getByRole('button', { name: `Open assessment ${useCase.title}` }));
  expect((await screen.findByRole('button', { name: 'Edit use case' })).hasAttribute('disabled')).toBe(true);
  const score = screen.queryByRole('button', { name: /Run Scoring/ });
  if (score) expect(score.hasAttribute('disabled')).toBe(true);
});
