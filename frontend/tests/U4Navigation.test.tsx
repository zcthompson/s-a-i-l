/**
 * customer workspace navigation restructure tests.
 *
 * The 15 top-level tabs are reorganized into the two-level structure:
 * five primary areas (Overview |
 * Intelligence | Assessments | Sales | Team) with per-area secondary
 * rails, a proper SegmentedNav (not buttons-as-pseudo-tabs), no
 * "Quick Actions" row, and breadcrumbs instead of
 * the My Customers / Back to Dashboard pair. These tests drive the
 * real CustomerDashboard through the same Home path as the
 * regression tests.
 */
import { describe, it, expect, vi, afterEach, beforeAll } from 'vitest';
import { render, screen, cleanup, fireEvent, within } from '@testing-library/react';
import { MemoryRouter, useLocation, useNavigate } from 'react-router-dom';
import { Home } from '../src/pages/Home';
import { CustomerDashboard } from '../src/pages/CustomerDashboard';

beforeAll(() => {
  if (typeof Element !== 'undefined' && !Element.prototype.scrollTo) {
    Element.prototype.scrollTo = function () { return undefined; };
  }
});

const { useCase, customer } = vi.hoisted(() => {
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
  return { useCase, customer };
});

// Mutable auth/role state: the default identity is the customer owner; the
// sales-admin pin flips it (reset in afterEach).
const { authState } = vi.hoisted(() => ({ authState: { salesRole: null as string | null, permission: 'owner', caseCustomerId: 7 } }));

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
    aggregateStats: () => Promise.resolve(statsShape),
    getCustomersStats: () => Promise.resolve(null),
    listCustomers: () => Promise.resolve([customer]),
    getCustomer: () => Promise.resolve({ ...customer, use_case_count: 1 }),
    getCustomerUseCases: () => Promise.resolve([{ ...useCase, customer_id: authState.caseCustomerId }]),
    listVerticals: () => Promise.resolve({ verticals: [], departments_by_vertical: {} }),
    listDepartments: () => Promise.resolve([]),
    listAssessments: () => Promise.resolve([]),
    checkAccess: () => Promise.resolve({ has_access: true, permission_level: authState.permission }),
    getNotifications: () => Promise.resolve([]),
    getMyCustomers: () => Promise.resolve([]),
    list: () => Promise.resolve([useCase]),
    getComments: () => Promise.resolve([]),
    // UX audit #10: the Opportunities panel owns its heading and renders
    // NOTHING on empty signals (no invented filler). Stub one opportunity so
    // the Sales ▸ Opportunities heading is asserted against real panel data.
    getAccountWorkspace: () =>
      Promise.resolve({
        customer_id: customer.id,
        generated_at: '2026-09-09T00:00:00Z',
        method: 'deterministic_account_workspace',
        opportunities: [
          {
            id: 'opp-1',
            type: 'growth_opportunity',
            severity: 'medium',
            title: 'Growth opportunity',
            detail: null,
            evidence: { source: 'technology', source_id: 1, source_name: 'vSphere' },
          },
        ],
      }),
    // The Timeline section expects a timeline page (an object, not a list).
    getAccountTimeline: () =>
      Promise.resolve({
        customer_id: customer.id,
        qbr: { last_qbr_date: null, cadence_days: 90, next_qbr_due: null, state: 'not_recorded', days_until: null },
        items: [],
        next_cursor: null,
        more: false,
      }),
    // F4: the constellation fetches a graph projection (an object, not a
    // bare list) — return a valid empty projection so the section renders.
    getCustomerIntelligenceGraph: () =>
      Promise.resolve({
        customer_id: customer.id,
        generated_at: '2026-09-09T00:00:00Z',
        method: 'deterministic_graph_projection',
        customer_label: customer.name || '',
        nodes: [],
        links: [],
        limits: {
          max_per_domain: 8, technology_total: 0, technology_shown: 0,
          use_case_total: 0, use_case_shown: 0, sales_note_total: 0,
          sales_note_shown: 0, dependencies_total: 0, dependencies_shown: 0,
          opportunities_total: 0,
        },
      }),
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
  getAuthSalesRole: () => authState.salesRole,
}));
vi.mock('../src/lib/websocket', () => ({
  ws: { connect: vi.fn(), disconnect: vi.fn(), subscribe: vi.fn() },
}));
// F4: the Intelligence → Summary section renders the Customer Intelligence
// Constellation (three.js Mobius canvas). jsdom has no WebGL, so stub the
// canvas renderer at the module boundary — the dashboard navigation
// behavior under test does not depend on the canvas internals.
vi.mock('../src/components/MobiusGraphCanvas', async () => {
  const React = await import('react');
  return {
    default: React.forwardRef(() => <div data-testid="constellation-canvas-stub" />),
  };
});

afterEach(() => {
  authState.salesRole = null;
  authState.permission = 'owner';
  authState.caseCustomerId = 7;
  cleanup();
});

function renderApp() {
  render(
    <MemoryRouter initialEntries={['/?view=customers']}>
      <Home />
    </MemoryRouter>,
  );
}

const tab = (label: string) => screen.getByRole('tab', { name: `Navigate to ${label}` });
const primaryTabs = () => screen.getAllByRole('tab').map((t) => t.textContent);

/** Select the stub customer and wait for the workspace header. */
async function selectCustomer() {
  renderApp();
  // 5s wait: the cold first-load of the customer list is the recorded
  // timing-flake class under host load (default 1s was hit at ~1.05s).
  const customerRow = await screen.findByRole('button', { name: 'Select customer Energy Test Company' }, { timeout: 5000 });
  fireEvent.click(customerRow);
  await screen.findByRole('heading', { level: 1, name: /Energy Test Company/ });
}

function HistoryProbe() {
  const location = useLocation();
  const navigate = useNavigate();
  return <><output data-testid="current-route">{location.search}</output><button onClick={() => navigate(-1)}>Browser back</button><button onClick={() => navigate(1)}>Browser forward</button></>;
}

describe('dashboard account actions', () => {
  it.each([['edit', 'Edit customer'], ['remove', 'Remove customer']])('opens %s after the customer loads', async (action, title) => {
    render(<MemoryRouter><CustomerDashboard onNavigate={() => undefined} onEditUseCase={() => undefined} onOpenScoring={() => undefined} onOpenDrilldown={() => undefined} onOpenComments={() => undefined} onCustomerSelect={() => undefined} selectedCustomerName="Energy Test Company" initialAction={action} /></MemoryRouter>);
    expect(await screen.findByRole('dialog', { name: title }, { timeout: 5000 })).toBeTruthy();
  });
});

describe('customer workspace route restoration', () => {
  it('restores a linked section and preserves history across section changes', async () => {
    render(<MemoryRouter initialEntries={['/?view=customers&customer=Energy%20Test%20Company&area=intelligence-summary']}><HistoryProbe /><Home /></MemoryRouter>);
    await screen.findByRole('heading', { level: 1, name: /Energy Test Company/ }, { timeout: 5000 });
    expect(tab('Summary').getAttribute('aria-selected')).toBe('true');
    fireEvent.click(tab('Technology'));
    expect(screen.getByTestId('current-route').textContent).toContain('area=technology-inventory');
    fireEvent.click(screen.getByText('Browser back'));
    await screen.findByRole('tab', { name: 'Navigate to Summary', selected: true });
    fireEvent.click(screen.getByText('Browser forward'));
    await screen.findByRole('tab', { name: 'Navigate to Technology', selected: true });
  });

  it('opens Timeline from the rail, keeps it in history and restores its direct link', async () => {
    render(<MemoryRouter initialEntries={['/?view=customers&customer=Energy%20Test%20Company&area=intelligence-summary']}><HistoryProbe /><Home /></MemoryRouter>);
    await screen.findByRole('heading', { level: 1, name: /Energy Test Company/ }, { timeout: 5000 });
    fireEvent.click(tab('Timeline'));
    expect(screen.getByTestId('current-route').textContent).toContain('area=account-timeline');
    expect(tab('Timeline').getAttribute('aria-selected')).toBe('true');
    fireEvent.click(screen.getByText('Browser back'));
    await screen.findByRole('tab', { name: 'Navigate to Summary', selected: true });
    fireEvent.click(screen.getByText('Browser forward'));
    await screen.findByRole('tab', { name: 'Navigate to Timeline', selected: true });
    cleanup();
    render(<MemoryRouter initialEntries={['/?view=customers&customer=Energy%20Test%20Company&area=account-timeline']}><Home /></MemoryRouter>);
    await screen.findByRole('heading', { level: 1, name: /Energy Test Company/ }, { timeout: 5000 });
    expect(tab('Intelligence').getAttribute('aria-selected')).toBe('true');
    expect(tab('Timeline').getAttribute('aria-selected')).toBe('true');
  });

  it('opens a customer use case, returns with history and restores a direct link', async () => {
    render(<MemoryRouter initialEntries={['/?view=customers&customer=Energy%20Test%20Company&area=use-cases']}><HistoryProbe /><Home /></MemoryRouter>);
    const row = await screen.findByRole('button', { name: 'Open assessment Improve operational efficiency' }, { timeout: 5000 });
    fireEvent.click(row);
    await screen.findByRole('heading', { level: 1, name: 'Improve operational efficiency' });
    fireEvent.click(tab('Improve operational efficiency'));
    expect(screen.getByRole('heading', { level: 1, name: 'Improve operational efficiency' })).toBeTruthy();
    const params = new URLSearchParams(screen.getByTestId('current-route').textContent ?? '');
    expect(params.get('area')).toBe('detail');
    expect(params.get('customer_uc')).toBe('68');
    fireEvent.click(screen.getByText('Browser back'));
    await screen.findByRole('button', { name: 'Open assessment Improve operational efficiency' });
    fireEvent.click(screen.getByText('Browser forward'));
    await screen.findByRole('heading', { level: 1, name: 'Improve operational efficiency' });
    cleanup();
    render(<MemoryRouter initialEntries={['/?view=customers&customer=Energy%20Test%20Company&area=detail&customer_uc=68']}><Home /></MemoryRouter>);
    await screen.findByRole('heading', { level: 1, name: 'Improve operational efficiency' });
  });

  it('does not expose a missing or foreign use case and offers recovery', async () => {
    render(<MemoryRouter initialEntries={['/?view=customers&customer=Energy%20Test%20Company&area=detail&customer_uc=999']}><Home /></MemoryRouter>);
    expect(await screen.findByText('Use case not found or unavailable.', {}, { timeout: 5000 })).toBeTruthy();
    expect(screen.queryByRole('heading', { level: 1, name: 'Improve operational efficiency' })).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: 'Return to use cases' }));
    await screen.findByRole('button', { name: 'Open assessment Improve operational efficiency' });
  });

  it('rejects an otherwise visible use case belonging to a different customer', async () => {
    authState.caseCustomerId = 999;
    render(<MemoryRouter initialEntries={['/?view=customers&customer=Energy%20Test%20Company&area=detail&customer_uc=68']}><Home /></MemoryRouter>);
    expect(await screen.findByText('Use case not found or unavailable.', {}, { timeout: 5000 })).toBeTruthy();
    expect(screen.queryByRole('heading', { level: 1, name: 'Improve operational efficiency' })).toBeNull();
  });

  it('falls back to overview for invalid and transient area links', async () => {
    render(<MemoryRouter initialEntries={['/?view=customers&customer=Energy%20Test%20Company&area=remove']}><Home /></MemoryRouter>);
    await screen.findByRole('heading', { level: 1, name: /Energy Test Company/ });
    expect(tab('Overview').getAttribute('aria-selected')).toBe('true');
    expect(screen.queryByRole('dialog')).toBeNull();
  });
});

describe('two-level customer workspace navigation', () => {
  it('keeps Overview concise and opens grouped sales information', async () => {
    await selectCustomer();
    expect(screen.queryByRole('heading', { name: /^Attention/ })).toBeNull();
    expect(screen.getByRole('button', { name: 'View deals' })).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: 'View attention' }));
    expect(await screen.findByRole('heading', { name: /^Attention/ })).toBeTruthy();
    expect(tab('Sales').getAttribute('aria-selected')).toBe('true');
    expect(tab('Partner Pipeline')).toBeTruthy();
    expect(tab('Vendor Intelligence')).toBeTruthy();
  });

  it.each(['sales-pipeline', 'sales-vendor-intelligence'])('restores the %s destination from its URL', async (area) => {
    render(<MemoryRouter initialEntries={[`/?view=customers&customer=Energy%20Test%20Company&area=${area}`]}><Home /></MemoryRouter>);
    await screen.findByRole('heading', { level: 1, name: /Energy Test Company/ });
    expect(tab('Sales').getAttribute('aria-selected')).toBe('true');
    expect(tab(area === 'sales-pipeline' ? 'Partner Pipeline' : 'Vendor Intelligence').getAttribute('aria-selected')).toBe('true');
  });

  it('shows the five primary areas (no emoji, no 15-button pseudo-tab row)', async () => {
    await selectCustomer();
    const primary = primaryTabs();
    expect(primary).toEqual(['Overview', 'Sales', 'Intelligence', 'Discovery & Value', 'Team']);
    // The old flat tab labels are gone from the nav (only the secondary
    // rail of the active area would ever show them).
    for (const gone of ['📊 Overview', '📝 Assessments', '📤 Export', '🎯 Sales Evaluations']) {
      expect(screen.queryByText(gone)).toBeNull();
    }
  });

  it('the secondary rail follows the active primary area', async () => {
    await selectCustomer();
    // Default area: Overview — no secondary rail.
    expect(screen.queryByRole('tab', { name: 'Navigate to Rounds' })).toBeNull();

    fireEvent.click(tab('Intelligence'));
    // The Intelligence rail includes the professional-services intelligence panel.
    // (H5 adds Activities + Tasks after Contacts; Timeline follows
    // Brief — the Account 360 derived feed).
    expect(primaryTabs()).toEqual([
      'Overview', 'Sales', 'Intelligence', 'Discovery & Value', 'Team',
      'Summary', 'Technology', 'Knowledge', 'Sales Notes', 'Contacts', 'Activities', 'Tasks', 'Brief', 'Timeline', 'Third-Party Services',
    ]);

    fireEvent.click(tab('Discovery & Value'));
    // (Rounds is the default rail item on entry)
    expect(primaryTabs()).toEqual([
      'Overview', 'Sales', 'Intelligence', 'Discovery & Value', 'Team',
      'Summary', 'Use Cases', 'Bulk Score', 'Analytics', 'Business Impact', 'Forecasting', 'Export',
    ]);

    fireEvent.click(tab('Sales'));
    // Deals | Attention | Partner Pipeline | Vendor Intelligence | Evaluations | Account Strategy
    expect(primaryTabs()).toEqual([
      'Overview', 'Sales', 'Intelligence', 'Discovery & Value', 'Team',
      'Deals', 'Attention', 'Partner Pipeline', 'Vendor Intelligence', 'Evaluations', 'Account Strategy',
    ]);

    fireEvent.click(tab('Team'));
    expect(primaryTabs()).toEqual([
      'Overview', 'Sales', 'Intelligence', 'Discovery & Value', 'Team',
      'Team', 'Departments',
    ]);
  });

  it('clicking a primary area lands on its default section', async () => {
    await selectCustomer();
    fireEvent.click(tab('Discovery & Value'));
    // the emoji is dropped and the Rounds area is
    // a single consolidated card (the duplicated report table is gone).
    await screen.findByText('Assessment Rounds', { selector: 'h2' });

    fireEvent.click(tab('Intelligence'));
    await screen.findByRole('tab', { name: 'Navigate to Summary' });
    // Intelligence ▸ Summary is the customer-intelligence summary
    await screen.findByText('Customer Intelligence');

    fireEvent.click(tab('Sales'));
    // Sales ▸ Deals is the default (rep-owned records come first).
    await screen.findByRole('heading', { level: 3, name: /^Deals/ });
  });

  it('technology, knowledge, sales notes, and third-party services live under Intelligence', async () => {
    await selectCustomer();
    fireEvent.click(tab('Intelligence'));
    fireEvent.click(tab('Technology'));
    // TechnologyInventory mounts (its own fetch resolves from the stub).
    await screen.findByRole('heading', { level: 2, name: 'Technology Inventory' });
    fireEvent.click(tab('Third-Party Services'));
    await screen.findByRole('heading', { level: 2, name: 'Third-Party Professional Services' });
    expect(tab('Sales Notes')).toBeTruthy();
  });

  it('the old flat controls are gone: Quick Actions row and top-level Edit/Remove tabs', async () => {
    await selectCustomer();
    expect(screen.queryByText('Quick Actions')).toBeNull();
    expect(screen.queryByRole('tab', { name: 'Navigate to Edit' })).toBeNull();
    expect(screen.queryByRole('tab', { name: 'Navigate to Remove' })).toBeNull();
    expect(screen.queryByText('✏️ Edit Customer')).toBeNull();
    expect(screen.queryByText('🗑️ Remove Customer')).toBeNull();
    // The account-management actions still exist in the header's
    // settings overflow (never as primary buttons).
    fireEvent.click(screen.getByRole('button', { name: 'Customer settings' }));
    expect(screen.getByRole('menuitem', { name: 'Edit Customer' })).toBeTruthy();
    expect(screen.getByRole('menuitem', { name: 'Remove Customer' })).toBeTruthy();
    // picking Edit Customer opens the
    // account-management surface as a transient dialog overlay (not a nav
    // area, not a full-screen view switch), and Cancel closes it.
    fireEvent.click(screen.getByRole('menuitem', { name: 'Edit Customer' }));
    const editDialog = await screen.findByRole('dialog', { name: 'Edit customer' });
    expect(editDialog).toBeTruthy();
    // UX audit #8: the buttons carry specific labels — Cancel is the
    // "Cancel customer settings" button; closing the dialog is what we're
    // proving here.
    // aliases are edited in this dialog,
    // below Description and Vertical.
    const field = within(editDialog).getByTestId('customer-aliases-field');
    expect(within(field).getByLabelText('New alias')).toBeTruthy();
    expect(within(editDialog).getByRole('button', { name: 'Save customer settings' })).toBeTruthy();
    const order = Array.from(editDialog.querySelectorAll('label, [data-testid="customer-aliases-field"]')).map((el) => el.textContent?.slice(0, 11));
    expect(order).toEqual(['Description', 'Vertical', 'AliasesOthe']);
    fireEvent.click(within(editDialog).getByRole('button', { name: 'Cancel customer settings' }));
    // The workspace nav is intact underneath (still on the same area).
    expect(screen.getByRole('tab', { name: 'Navigate to Overview' })).toBeTruthy();
    expect(screen.queryByRole('dialog', { name: 'Edit customer' })).toBeNull();
    fireEvent.keyDown(document, { key: 'Escape' });
  });

  it('breadcrumbs replace the Back to Dashboard / My Customers button pair', async () => {
    await selectCustomer();
    const crumbs = screen.getByRole('navigation', { name: 'Breadcrumb' });
    expect(within(crumbs).getByText('Dashboard')).toBeTruthy();
    expect(within(crumbs).getByText('Customers')).toBeTruthy();
    expect(within(crumbs).getByText('Energy Test Company').getAttribute('aria-current')).toBe('page');
    expect(screen.queryByRole('button', { name: 'Back to Dashboard' })).toBeNull();
  });
});

describe('Edit Customer — aliases', () => {
  it('the Overview has no Aliases card', async () => {
    await selectCustomer();
    expect(screen.getByRole('tab', { name: 'Navigate to Overview' }).getAttribute('aria-selected')).toBe('true');
    expect(screen.queryByTestId('customer-aliases-card')).toBeNull();
    expect(screen.queryByTestId('customer-aliases-field')).toBeNull();
    expect(screen.queryByLabelText('New alias')).toBeNull();
  });

  it('a sales admin (not owner) opens Edit Customer for the Aliases only', async () => {
    authState.salesRole = 'sales_admin';
    authState.permission = 'member';
    await selectCustomer();
    fireEvent.click(screen.getByRole('button', { name: 'Customer settings' }));
    expect(screen.queryByRole('menuitem', { name: 'Remove Customer' })).toBeNull();
    expect(screen.queryByRole('menuitem', { name: 'Departments' })).toBeNull();
    fireEvent.click(screen.getByRole('menuitem', { name: 'Edit Customer' }));
    const dialog = await screen.findByRole('dialog', { name: 'Edit customer' });
    expect(within(dialog).getByLabelText('New alias')).toBeTruthy();
    expect(within(dialog).queryByText('Description')).toBeNull();
    expect(within(dialog).queryByRole('button', { name: 'Save customer settings' })).toBeNull();
    fireEvent.click(within(dialog).getByRole('button', { name: 'Cancel customer settings' }));
    expect(screen.queryByRole('dialog', { name: 'Edit customer' })).toBeNull();
  });

  it('a plain member sees no Edit Customer entry', async () => {
    authState.permission = 'member';
    await selectCustomer();
    fireEvent.click(screen.getByRole('button', { name: 'Customer settings' }));
    expect(screen.queryByRole('menuitem', { name: 'Edit Customer' })).toBeNull();
  });
});
