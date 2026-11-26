/**
 * OpportunitiesPanel tests.
 *
 * Verifies the Opportunities & Attention panel on the redesigned Overview:
 * typed opportunity cards with visible evidence/"why",
 * severity semantics, the Generate Sales
 * Evaluation call to action, and defensive behavior —
 * no signals → nothing rendered (no invented filler), non-object stub
 * response → no crash (same convention as CustomerIntelligenceOverview),
 * API error → inline error surface.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, cleanup } from '@testing-library/react';
import { OpportunitiesPanel } from '../src/components/OpportunitiesPanel';

const { apiMock } = vi.hoisted(() => ({
  apiMock: {
    getAccountWorkspace: vi.fn(),
    promoteTask: vi.fn(),
  },
}));

vi.mock('../src/lib/api', () => ({
  api: apiMock,
}));

const workspace = {
  customer_id: 1,
  generated_at: '2026-09-08T00:00:00',
  method: 'deterministic_aggregation',
  account: { id: 1, name: 'Acme', vertical: 'Manufacturing', description: null, department_count: 2, member_count: 2, owner: null },
  technology_landscape: {
    total: 8, key_vendors: [{ key: 'VMware', count: 4 }], key_categories: [], eol_count: 2, unsupported_count: 2,
    at_risk_count: 2, critical_tech_at_risk: [], unverified_pct: 12.5, important_gaps: ['2 item(s) at end-of-life'],
  },
  knowledge: { total: 3, sources: { processed: 2, pending: 1 }, by_type: {}, latest_uploaded: null, days_since_latest: 9, recently_added_count: 3, unprocessed_count: 1 },
  sales_activity: { total_notes: 5, last_interaction: null, days_since_last_interaction: 5, notes_stale: false, recent: [], active_observations: [] },
  assessment: { active_assessment: null, average_score: 62.5, top_use_cases: [], unscored_count: 2, total_count: 14, scored_count: 12 },
  business_impact: { total_savings: 4700000, total_revenue: 750000, total_impact: 5450000, contributing_use_cases: 14 },
  latest_evaluation: null,
  opportunities: [
    {
      id: 'lifecycle-risk-tech-2',
      type: 'lifecycle_risk',
      severity: 'high',
      title: 'VMware vSphere 6.5 — eol/no_support',
      detail: 'Core virtualization platform',
      evidence: { source: 'technology', source_id: 2, source_name: 'VMware vSphere 6.5' },
    },
    {
      id: 'discovery-needed-knowledge',
      type: 'discovery_needed',
      severity: 'low',
      title: '1 knowledge source(s) awaiting processing',
      detail: 'Process uploaded knowledge so it feeds assessments and evaluations.',
      evidence: { source: 'customer_knowledge', source_id: null, source_name: 'Customer Knowledge' },
    },
    {
      id: 'growth-opportunity-uc-9',
      type: 'growth_opportunity',
      severity: 'medium',
      title: 'AI Production Schedule Optimizer',
      detail: 'Readiness score 82 — advance this initiative.',
      evidence: { source: 'use_case', source_id: 9, source_name: 'AI Production Schedule Optimizer' },
    },
  ],
  headline: { active_use_cases: 14, business_impact: { total_savings: 4700000, total_revenue: 750000, total_impact: 5450000, contributing_use_cases: 14 }, technologies_known: 8, open_opportunities_count: 3 },
};

afterEach(() => { cleanup(); });

describe('OpportunitiesPanel', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('renders typed cards with labels, severity, and the supporting evidence ("why")', async () => {
    apiMock.getAccountWorkspace.mockResolvedValue(workspace);
    render(<OpportunitiesPanel customerId={1} />);

    expect(await screen.findByText('Attention')).toBeTruthy();
    // Typed cards, not generic AI recommendations.
    expect(screen.getByText('Lifecycle Risk')).toBeTruthy();
    expect(screen.getByText('Discovery Needed')).toBeTruthy();
    expect(screen.getByText('Growth Opportunity')).toBeTruthy();
    // Severity is surfaced (high first, per the backend ordering).
    expect(screen.getByText('HIGH')).toBeTruthy();
    // The "why" — supporting evidence is visible on the lifecycle card.
    expect(screen.getByText(/VMware vSphere 6.5 · Technology Inventory/)).toBeTruthy();
  });

  it('the Generate Sales Evaluation CTA navigates to the Sales workflow', async () => {
    apiMock.getAccountWorkspace.mockResolvedValue(workspace);
    const onExplore = vi.fn();
    render(<OpportunitiesPanel customerId={1} onExplore={onExplore} />);
    const cta = await screen.findByRole('button', { name: 'Generate a persona-driven sales evaluation for this customer' });
    fireEvent.click(cta);
    expect(onExplore).toHaveBeenCalled();
  });

  it('per-card Explore actions route to the Sales workflow too', async () => {
    apiMock.getAccountWorkspace.mockResolvedValue(workspace);
    const onExplore = vi.fn();
    render(<OpportunitiesPanel customerId={1} onExplore={onExplore} />);
    const explore = await screen.findByRole('button', { name: 'Explore opportunity VMware vSphere 6.5 — eol/no_support' });
    fireEvent.click(explore);
    expect(onExplore).toHaveBeenCalled();
  });

  it('renders nothing when the customer has no opportunity signals (no invented filler)', async () => {
    apiMock.getAccountWorkspace.mockResolvedValue({ ...workspace, opportunities: [] });
    const { container } = render(<OpportunitiesPanel customerId={1} />);
    await vi.waitFor(() => expect(apiMock.getAccountWorkspace).toHaveBeenCalled());
    expect(container.querySelector('h3')).toBeNull();
    expect(screen.queryByText('Attention')).toBeNull();
  });

  it('guards against a non-object response (stub resolving [] must not crash the Overview)', async () => {
    apiMock.getAccountWorkspace.mockResolvedValue([]);
    const { container } = render(<OpportunitiesPanel customerId={1} />);
    await vi.waitFor(() => expect(apiMock.getAccountWorkspace).toHaveBeenCalled());
    expect(container.innerHTML).toBe('');
  });

  it('surfaces an inline error when the endpoint fails', async () => {
    apiMock.getAccountWorkspace.mockRejectedValue(new Error('workspace unavailable'));
    render(<OpportunitiesPanel customerId={1} />);
    expect(await screen.findByText('workspace unavailable')).toBeTruthy();
  });
});

describe('OpportunitiesPanel — renewal_attention (H3)', () => {
  beforeEach(() => { vi.clearAllMocks(); });
  it('renders the Renewal Attention label, severity and the Partner Pipeline source', async () => {
    apiMock.getAccountWorkspace.mockResolvedValue({
      ...workspace,
      opportunities: [{
        id: 'renewal-attention-123', type: 'renewal_attention', severity: 'high',
        title: 'Renewal — 123: current contract ends in 20 days',
        detail: 'Vendor-reported current contract end 2026-11-16 (snapshot import #2, imported 2026-10-25).',
        evidence: { source: 'partner_pipeline', source_id: 2, source_name: '123' },
      }],
    });
    render(<OpportunitiesPanel customerId={1} />);
    expect(await screen.findByText('Renewal Attention')).toBeTruthy();
    expect(screen.getByText('HIGH')).toBeTruthy();
    expect(screen.getByText('Renewal — 123: current contract ends in 20 days')).toBeTruthy();
    expect(screen.getByText(/123 · Partner Pipeline/)).toBeTruthy();
  });
});

describe('OpportunitiesPanel — contact_coverage (H4)', () => {
  beforeEach(() => { vi.clearAllMocks(); });
  it('renders the backend title/detail/evidence verbatim with the Contact Coverage label', async () => {
    apiMock.getAccountWorkspace.mockResolvedValue({
      ...workspace,
      opportunities: [{
        id: 'contact-coverage-1', type: 'contact_coverage', severity: 'high',
        title: 'No contacts recorded; No economic buyer recorded; No champion recorded',
        detail: '0 contacts recorded; 0 buying role(s) recorded',
        evidence: { source: 'customer_contacts', source_id: 1, source_name: 'Account contact coverage' },
      }],
    });
    render(<OpportunitiesPanel customerId={1} />);
    expect(await screen.findByText('Contact Coverage')).toBeTruthy();
    expect(screen.getByText('HIGH')).toBeTruthy();
    expect(screen.getByText('No contacts recorded; No economic buyer recorded; No champion recorded')).toBeTruthy();
    expect(screen.getByText('0 contacts recorded; 0 buying role(s) recorded')).toBeTruthy();
    expect(screen.getByText(/Account contact coverage · Customer Contacts/)).toBeTruthy();
  });
});


it('promotes dated EOL evidence to an account task', async () => {
  apiMock.getAccountWorkspace.mockResolvedValue({ ...workspace, opportunities: [{
    id: 'eol-attention-12', type: 'eol_attention', severity: 'medium',
    title: 'End-of-support: Synthetic platform', detail: 'Dated end of support 2027-01-31; source: Synthetic notice.',
    evidence: { source: 'technology', source_id: 12, source_name: 'Synthetic platform' },
  }] });
  apiMock.promoteTask.mockResolvedValue({ created: true, task: { id: 23 } });
  render(<OpportunitiesPanel customerId={1} userRole="owner" />);
  expect(await screen.findByText('End-of-support Attention')).toBeTruthy();
  fireEvent.click(screen.getByRole('button', { name: 'Create follow-up task from End-of-support: Synthetic platform' }));
  expect(await screen.findByText('Follow-up task created')).toBeTruthy();
  expect(apiMock.promoteTask).toHaveBeenCalledWith(1, { source_type: 'eol_attention', source_id: 12 });
});
