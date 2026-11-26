/**
 * CHANGELOG 0.1.0 U5 — AccountOverview / IntelligencePanels component tests.
 *
 * The redesigned executive Overview (directives 16-26, 39-40, 54-55):
 * balanced headline metrics (Business Impact is ONE card with savings +
 * revenue as sub-metrics — directive 20), the Account Snapshot
 * (ownership/departments/activity/assessment — directives 17-18), the
 * four actionable intelligence summaries (directive 22-26), Priority Use
 * Cases (directives 39-40), drill-down navigation (directive 55), and
 * provenance via tooltip instead of a "Derived" label (directive 21).
 *
 * Replaces CustomerIntelligenceOverview.test.tsx — the four sparse
 * numerical cards were the design this slice supersedes (directive 22).
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, cleanup, fireEvent, act } from '@testing-library/react';
import { AccountOverview, IntelligencePanels } from '../src/components/AccountOverview';

vi.mock('../src/components/AccountHealthCard', () => ({
  AccountHealthCard: ({ customerId }: { customerId: number }) => <div data-testid="health-card">Health for {customerId}</div>,
}));

const workspace = {
  customer_id: 5,
  generated_at: '2026-09-08T00:00:00Z',
  method: 'deterministic_aggregation',
  account: {
    id: 5,
    name: 'Acme Manufacturing',
    vertical: 'Manufacturing',
    description: 'Mid-size discrete manufacturer',
    department_count: 4,
    member_count: 3,
    owner: { user_id: 1, display_name: 'Casey Admin', username: 'casey', role: 'owner' },
  },
  technology_landscape: {
    total: 8,
    key_vendors: [{ key: 'VMware', count: 3 }, { key: 'Cisco', count: 2 }],
    key_categories: [{ key: 'virtualization', count: 4 }],
    eol_count: 2,
    unsupported_count: 1,
    at_risk_count: 2,
    critical_tech_at_risk: [
      { id: 1, name: 'VMware vSphere 6.5', vendor: 'VMware', category: 'virtualization', lifecycle_state: 'eol', support_state: 'no_support', business_criticality: 'critical', verification_state: 'verified' },
    ],
    unverified_pct: 37.5,
    important_gaps: ['No network devices recorded', 'No storage tier recorded'],
  },
  knowledge: {
    total: 3,
    sources: { file: 2, csv: 1 },
    by_type: {},
    latest_uploaded: '2026-08-30T00:00:00Z',
    days_since_latest: 9,
    recently_added_count: 2,
    unprocessed_count: 1,
  },
  sales_activity: {
    total_notes: 5,
    last_interaction: { id: 9, title: 'Q3 discovery call', note_date: '2026-08-29', category: 'discovery', verification_state: 'verified' },
    days_since_last_interaction: 10,
    notes_stale: false,
    recent: [{ id: 9, title: 'Q3 discovery call', note_date: '2026-08-29', category: 'discovery', verification_state: 'verified' }],
    active_observations: [{ id: 10, title: 'Consolidation interest', note_date: '2026-08-15', category: 'account_observation', verification_state: 'verified' }],
  },
  assessment: {
    active_assessment: { id: 1, name: 'Assessment 1', status: 'active', total_count: 14, scored_count: 10, progress_pct: 71.4 },
    average_score: 68.5,
    top_use_cases: [
      { id: 41, title: 'VMware vSphere renewal planning', overall_score: 91, status: 'active' },
      { id: 42, title: 'Networking modernization', overall_score: 84, status: 'draft' },
    ],
    unscored_count: 4,
    total_count: 14,
    scored_count: 10,
  },
  business_impact: { total_savings: 420000, total_revenue: 180000, total_impact: 600000, contributing_use_cases: 6 },
  latest_evaluation: null,
  opportunities: [],
  headline: {
    active_use_cases: 3,
    business_impact: { total_savings: 420000, total_revenue: 180000, total_impact: 600000, contributing_use_cases: 6 },
    technologies_known: 8,
    open_opportunities_count: 4,
  },
};

const { apiMock } = vi.hoisted(() => ({
  apiMock: {
    getAccountWorkspace: vi.fn(),
    get: vi.fn(),
  },
}));

vi.mock('../src/lib/api', () => ({
  api: apiMock,
  getAuthUsername: () => 'admin',
  getAuthIsAdmin: () => true,
  getAuthSalesRole: () => null,
}));

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe('AccountOverview (CHANGELOG 0.1.0 U5)', () => {
  beforeEach(() => {
    apiMock.getAccountWorkspace.mockResolvedValue(workspace);
  });

  it('shows account-focused cards in order without discovery content', async () => {
    render(<AccountOverview customerId={5} onNavigate={() => {}} />);
    expect(await screen.findByText('Needs attention')).toBeTruthy();
    expect(screen.queryByText('Active Use Cases')).toBeNull();
    expect(screen.queryByText('Priority Use Cases')).toBeNull();
    expect(screen.queryByText('Assessment & Use Cases')).toBeNull();
    expect(screen.queryByText('$600,000')).toBeNull();
    expect(screen.getByText('Currency and time basis are not recorded')).toBeTruthy();
    expect(screen.getByText(/Latest sales note 10 days ago/)).toBeTruthy();
    const text = document.body.textContent || '';
    expect(text.indexOf('Needs attention')).toBeLessThan(text.indexOf('Technologies Known'));
    expect(text.indexOf('Technologies Known')).toBeLessThan(text.indexOf('Projected business impact'));
  });

  it('labels the departments drill-down by caller capability (Manage for managing roles)', async () => {
    const navigate = vi.fn();
    render(<AccountOverview customerId={5} onNavigate={navigate} userRole="owner" />);
    const manage = await screen.findByRole('button', { name: 'Manage departments' });
    expect(manage.textContent).toBe('Manage');
    fireEvent.click(manage);
    expect(navigate).toHaveBeenCalledWith('departments');
  });

  it('labels the departments drill-down View for auditors and still navigates', async () => {
    const navigate = vi.fn();
    render(<AccountOverview customerId={5} onNavigate={navigate} userRole="auditor" />);
    const view = await screen.findByRole('button', { name: 'View departments' });
    expect(view.textContent).toBe('View');
    fireEvent.click(view);
    expect(navigate).toHaveBeenCalledWith('departments');
  });

  it('treats the none role as read-only for the departments drill-down', async () => {
    render(<AccountOverview customerId={5} onNavigate={() => {}} userRole="none" />);
    expect(await screen.findByRole('button', { name: 'View departments' })).toBeTruthy();
    expect(screen.queryByRole('button', { name: 'Manage departments' })).toBeNull();
  });

  it('routes intelligence actions to their owning areas', async () => {
    const navigate = vi.fn();
    render(<AccountOverview customerId={5} onNavigate={navigate} />);
    fireEvent.click(await screen.findByRole('button', { name: /Technologies Known/ }));
    expect(navigate).toHaveBeenCalledWith('technology-inventory');
    fireEvent.click(screen.getByRole('button', { name: 'View Customer Knowledge' }));
    expect(navigate).toHaveBeenCalledWith('customer-knowledge');
  });

  it('describes missing sources without claiming the account is empty', async () => {
    apiMock.getAccountWorkspace.mockResolvedValue({ ...workspace, knowledge: { ...workspace.knowledge, total: 0 }, sales_activity: { ...workspace.sales_activity, total_notes: 0 } });
    render(<AccountOverview customerId={5} onNavigate={() => {}} />);
    expect(await screen.findByText(/no sales notes, knowledge sources recorded yet/)).toBeTruthy();
    expect(screen.getByRole('button', { name: 'View Sales Activity' })).toBeTruthy();
    expect(screen.queryByText('No account intelligence yet')).toBeNull();
  });

  it('keeps health and actions available when the summary fails', async () => {
    apiMock.getAccountWorkspace.mockRejectedValue(new Error('offline'));
    render(<AccountOverview customerId={5} onNavigate={() => {}} />);
    expect((await screen.findByRole('alert')).textContent).toContain('Account overview unavailable');
    expect(screen.getByTestId('health-card')).toBeTruthy();
    expect(screen.getByRole('button', { name: 'View follow-ups' })).toBeTruthy();
  });

  it('IntelligencePanels renders the dedicated Summary view (directive 51)', async () => {
    render(<IntelligencePanels customerId={5} />);
    expect(await screen.findByText('Customer Intelligence')).toBeTruthy();
    expect(screen.getByText('Technology Landscape')).toBeTruthy();
    expect(screen.getByText('Assessment & Use Cases')).toBeTruthy();
  });

  it('IntelligencePanels header survives a non-object stub response (shape guard)', async () => {
    apiMock.getAccountWorkspace.mockResolvedValue([]);
    render(<IntelligencePanels customerId={5} />);
    expect(await screen.findByText('Customer Intelligence')).toBeTruthy();
  });
});

it('exposes overview loading and retry without leaving the customer', async () => {
  apiMock.getAccountWorkspace.mockRejectedValueOnce(new Error('Overview offline')).mockResolvedValueOnce(workspace);
  render(<AccountOverview customerId={5} />);
  expect(screen.getByRole('status').textContent).toBe('Loading account overview…');
  fireEvent.click(await screen.findByRole('button', { name: 'Retry overview' }));
  expect(await screen.findByText('Needs attention')).toBeTruthy();
});

it('retries the intelligence summary after a failed request', async () => {
  apiMock.getAccountWorkspace.mockRejectedValueOnce(new Error('offline')).mockResolvedValueOnce(workspace);
  render(<IntelligencePanels customerId={5} />);
  fireEvent.click(await screen.findByRole('button', { name: 'Retry intelligence' }));
  expect(await screen.findByText('Assessment & Use Cases')).toBeTruthy();
});

it('does not show an earlier customer after switching while a request is pending', async () => {
  let resolveFirst!: (value: unknown) => void;
  apiMock.getAccountWorkspace.mockReturnValueOnce(new Promise(resolve => { resolveFirst = resolve; })).mockResolvedValueOnce({ ...workspace, customer_id: 6, account: { ...workspace.account, owner: { ...workspace.account.owner, display_name: 'New owner' } } });
  const view = render(<AccountOverview customerId={5} />);
  view.rerender(<AccountOverview customerId={6} />);
  expect(await screen.findByText(/Owner: New owner/)).toBeTruthy();
  resolveFirst(workspace);
  await vi.waitFor(() => expect(screen.queryByText(/Owner: Casey Admin/)).toBeNull());
});

it('reloads the workspace when returning to Overview after an edit in another area', async () => {
  apiMock.getAccountWorkspace.mockResolvedValueOnce(workspace).mockResolvedValueOnce({
    ...workspace,
    sales_activity: { ...workspace.sales_activity, total_notes: 6 },
  });
  const first = render(<AccountOverview customerId={5} />);
  expect(await screen.findByText('5 sales notes')).toBeTruthy();
  first.unmount();
  render(<AccountOverview customerId={5} />);
  expect(await screen.findByText('6 sales notes')).toBeTruthy();
  expect(apiMock.getAccountWorkspace).toHaveBeenCalledTimes(2);
});

it.each([['overview', AccountOverview], ['intelligence', IntelligencePanels]] as const)('%s offers retry for a mismatched customer response', async (name, Component) => {
  apiMock.getAccountWorkspace.mockResolvedValue({ ...workspace, customer_id: 99 });
  render(<Component customerId={5} />);
  expect(await screen.findByRole('alert')).toBeTruthy();
  expect(screen.getByRole('button', { name: name === 'overview' ? 'Retry overview' : 'Retry intelligence' })).toBeTruthy();
  expect(screen.queryByText(/Owner: Casey Admin/)).toBeNull();
});

it('keeps health available and offers retry for an incomplete workspace response', async () => {
  apiMock.getAccountWorkspace.mockResolvedValue({ ...workspace, headline: {} });
  render(<AccountOverview customerId={5} />);
  expect(await screen.findByRole('alert')).toBeTruthy();
  expect(screen.getByTestId('health-card')).toBeTruthy();
  expect(screen.getByRole('button', { name: 'Retry overview' })).toBeTruthy();
});

it('exposes summary provenance without hover and preserves missing assessment progress', async () => {
  apiMock.getAccountWorkspace.mockResolvedValue({ ...workspace, assessment: { ...workspace.assessment, active_assessment: { ...workspace.assessment.active_assessment, progress_pct: null } } });
  render(<IntelligencePanels customerId={5} />);
  expect(await screen.findByText(/Assessment 1 · progress unavailable/)).toBeTruthy();
  expect(screen.getByText('About these summaries').closest('details')).toBeTruthy();
});

it('preserves focus on customer actions when a late workspace resolves', async () => {
  let resolveWorkspace!: (value: typeof workspace) => void;
  apiMock.getAccountWorkspace.mockReturnValueOnce(new Promise(resolve => { resolveWorkspace = resolve; }));
  render(<AccountOverview customerId={5} onNavigate={() => {}} />);
  const action = screen.getByRole('button', { name: 'View follow-ups' });
  action.focus();
  expect(document.activeElement).toBe(action);
  await act(async () => { resolveWorkspace(workspace); });
  expect(document.activeElement).toBe(action);
});
