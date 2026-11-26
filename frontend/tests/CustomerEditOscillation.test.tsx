// Regression tests for the view/URL oscillation when opening the edit
// wizard from a customer dashboard (user report, 2026-08-31):
//
// Customer Overview -> click use case -> Edit snapped the app back to
// "My Customers" and (for the test customer "Energy") showed
// "Failed to fetch"; the screen flashed on the Edit press.
//
// Root cause: handleEditFromCustomer changes the view AND the selected
// use case in one commit. The URL->view effect in Home.tsx had
// [searchParams, selectedUseCase] as deps, so it re-ran on the selection
// change, read the PRE-UPDATE URL (the view->URL effect writes the new
// view in the same commit; the URL applies a tick later), and wrote the
// stale view back. The two sync effects then kept "correcting" each
// other: view and URL oscillated at frame rate, the page content
// remounted every frame (the flash), and every remount re-fired the
// mount fetches (customers + verticals) at ~90 req/s. The flood
// exhausted the per-IP rate limit bucket, so every subsequent API call
// (including the actual edit save) 429'd ("Failed to fetch").
//
// The fix: the URL->view effect applies EXTERNAL URL changes only
// (deps: [searchParams]); the selection-required rule is owned by the
// safety-net effect ([view, selectedUseCase]).
import { describe, it, expect, vi, afterEach, beforeAll } from 'vitest';
import { render, screen, cleanup, fireEvent, act, within } from '@testing-library/react';
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

// Rich stub: the test drives the real customer-dashboard flow
// (list -> select customer -> Overview use-case table -> detail tab ->
// Edit -> wizard), so the customer/use-case/department endpoints resolve
// with representative shapes (the live "Energy Test Company" fixture).
const { apiStub } = vi.hoisted(() => {
  const statsShape = {
    total_use_cases: 0,
    average_score: 0,
    by_department: {},
    by_status: {},
    impact_summary: { total_impact: 0, total_savings: 0, total_revenue: 0 },
    top_use_cases: [],
  };
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
    score_history: null,
    created_at: '2026-08-29T01:08:50Z',
    updated_at: '2026-08-29T01:08:50Z',
    created_by: 'admin',
    assessment_id: 9,
    assessment_name: 'Energy Test Company — Assessment 1',
  };
  const methods: Record<string, (...args: any[]) => Promise<unknown>> = {
    getWorkspaceActions: (id: number) => Promise.resolve({ customer_id: id, capabilities: { use_case: true, assessment: true }, assignees: [] }),
    aggregateStats: () => Promise.resolve(statsShape),
    getCustomersStats: () => Promise.resolve(null),
    listCustomers: () => Promise.resolve([customer]),
    getCustomer: () => Promise.resolve(customer),
    getCustomerUseCases: () => Promise.resolve([useCase]),
    listVerticals: () => Promise.resolve({ verticals: [], departments_by_vertical: {} }),
    listDepartments: () => Promise.resolve([]),
    listAssessments: () => Promise.resolve([]),
    checkAccess: () => Promise.resolve({ has_access: true, permission_level: 'owner' }),
    getNotifications: () => Promise.resolve([]),
    getMyCustomers: () => Promise.resolve([]),
    list: () => Promise.resolve([useCase]),
  };
  const fallback = () => Promise.resolve([]);
  const stub: any = new Proxy({}, {
    get: (_target, prop) => (typeof prop === 'string' && methods[prop] ? methods[prop] : fallback),
  });
  return { apiStub: stub, customer, useCase };
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

afterEach(cleanup);

// The header <h2> is rendered outside Suspense and shows getViewLabel(view)
// — a deterministic probe for the active view regardless of lazy content.
const headerTitle = () => document.querySelector('main > header h2')?.textContent ?? '';

function UrlProbe() {
  const location = useLocation();
  return <span data-testid="url">{location.search}</span>;
}

describe('Edit a use case from the customer dashboard Overview', () => {
  it('lands on the edit wizard and stays there (no view/URL oscillation)', async () => {
    render(
      <MemoryRouter initialEntries={['/?view=customers']}>
        <Home />
        <UrlProbe />
      </MemoryRouter>
    );

    // The My Customers side list shows the stub customer; select it.
    const customerRow = await screen.findByRole('button', { name: 'Select customer Energy Test Company' }, { timeout: 5000 });
    fireEvent.click(customerRow);

    // Use Cases (Assessments area): click the use case row -> local detail tab.
    // CHANGELOG 0.1.0 U4: the table moved from the Overview to the Assessments ▸
    // Use Cases working view.
    fireEvent.click(await screen.findByRole('tab', { name: 'Navigate to Discovery & Value' }));
    fireEvent.click(screen.getByRole('tab', { name: 'Navigate to Use Cases' }));
    const ucRow = await screen.findByRole('button', { name: 'Open assessment Improve operational efficiency' });
    fireEvent.click(ucRow);

    // Detail tab: press Edit (scoped to the detail header row — the
    // customer "Edit" tab button and the "Edit Customer" quick action
    // share the same wording elsewhere on the page).
    const h1 = await screen.findByRole('heading', { level: 1, name: 'Improve operational efficiency' });
    const headerRow = h1.parentElement!.parentElement!;
    fireEvent.click(within(headerRow).getByText('✏️ Edit'));

    // Must land on the wizard with the URL carrying the new view.
    expect(headerTitle()).toBe('New Assessment');
    expect(screen.getByTestId('url').textContent).toBe('?view=assessment-create');
    // The wizard opened in EDIT mode with the use case pre-filled
    // (lazy import: await Suspense resolution).
    expect(await screen.findByRole('heading', { level: 1, name: 'Edit Assessment' })).toBeTruthy();

    // Settle: any in-flight URL sync/effects must not flip the view or
    // the URL back. (With the oscillation bug this loop is a synchronous
    // view/URL ping-pong that starves the event loop — the test hangs
    // and the runner never settles, i.e. the pre-fix state cannot pass.)
    await act(async () => { await new Promise(r => setTimeout(r, 50)); });
    expect(headerTitle()).toBe('New Assessment');
    expect(screen.getByTestId('url').textContent).toBe('?view=assessment-create');
  });

  it('preserves applied assessment filters when returning from a detail', async () => {
    render(<MemoryRouter initialEntries={['/?view=assessment-list&as_status=active']}><Home /><UrlProbe /></MemoryRouter>);
    const title = await screen.findByText('Improve operational efficiency', {}, { timeout: 5000 });
    fireEvent.click(within(title.closest('tr')!).getByText('📊 View'));
    await screen.findByRole('button', { name: 'Back' });
    fireEvent.click(screen.getByRole('button', { name: 'Back' }));
    await screen.findByText('Improve operational efficiency');
    expect((screen.getByLabelText('Filter by status') as HTMLSelectElement).value).toBe('active');
    expect(new URLSearchParams(screen.getByTestId('url').textContent ?? '').get('as_status')).toBe('active');
  });

  it('viewing a use case from the assessment list opens the detail view and stays there', async () => {
    // Same root cause, second entry point: AssessmentList's per-row View
    // action (onSelect -> handleSelect) changes view + selectedUseCase in
    // one commit while the URL still holds ?view=assessment-list.
    render(
      <MemoryRouter initialEntries={['/?view=assessment-list']}>
        <Home />
        <UrlProbe />
      </MemoryRouter>
    );

    // AssessmentList loads the use cases (stub: one entry) and renders a
    // row with the title and per-row action buttons.
    const title = await screen.findByText('Improve operational efficiency');
    const row = title.closest('tr')!;
    fireEvent.click(within(row).getByText('📊 View'));

    expect(headerTitle()).toBe('Use Case Detail');
    // FE-11: selection-required views carry the selected use-case id in the
    // URL (shareable destination) — the detail view for the viewed row.
    expect(screen.getByTestId('url').textContent).toBe('?view=detail&uc=68');

    // Settle: the view/URL must not oscillate back to the list.
    await act(async () => { await new Promise(r => setTimeout(r, 50)); });
    expect(headerTitle()).toBe('Use Case Detail');
    // FE-11: selection-required views carry the selected use-case id in the
    // URL (shareable destination) — the detail view for the viewed row.
    expect(screen.getByTestId('url').textContent).toBe('?view=detail&uc=68');
  });
});
