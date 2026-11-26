/**
 * Component tests for SalesEvaluation (Phase 3 — cross-domain sales
 * evaluations UI, extended with persona selection + pre-generation
 * preview + persona-section rendering). Mocks the api module (repo pattern:
 * vi.hoisted + vi.mock factory, cf. CustomerUrlSync.test.tsx). Plain
 * assertions — the project has no @testing-library/jest-dom setup.
 *
 * NOTE (jsdom): native <select> has no resolvable implicit ARIA role here, so
 * selects are queried via aria-label / wrapping <label> (getByLabelText).
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, cleanup, within } from '@testing-library/react';
import { SalesEvaluation } from '../src/components/SalesEvaluation';

afterEach(() => {
  cleanup();
});

const mockEvaluations = [
  {
    id: 1,
    customer_id: 5,
    evaluation_name: 'Q3 Technical Review',
    status: 'completed',
    readiness_overall: 72,
    readiness_dimensions: {
      strategic_fit: 80,
      technical_feasibility: 75,
      financial_viability: 70,
      operational_readiness: 65,
      risk_tolerance: 80,
      resource_availability: 60,
    },
    environment_score: 78,
    environment_factors: {
      software_completeness: 82,
      hardware_currency: 75,
      process_documentation: 70,
      vendor_diversity: 85,
    },
    growth_opportunities: [
      { category: 'Expansion', description: 'Enter new markets' },
    ],
    risk_factors: [
      { category: 'Security', description: 'Potential vulnerability', mitigation: 'Pen test scheduled' },
    ],
    sales_approach: {
      approach: 'consultative',
      urgency: 'medium',
      focus: 'technical evaluation',
      talking_points: ['ROI', 'timeline'],
      timing: 'Q4',
      next_steps: ['proposal', 'signature'],
    },
    created_at: '2026-01-15T10:00:00Z',
    updated_at: '2026-03-20T14:30:00Z',
  },
  {
    id: 2,
    customer_id: 5,
    evaluation_name: 'Q4 Compliance Review',
    status: 'in_progress',
    readiness_overall: 55,
    readiness_dimensions: {
      strategic_fit: 50,
      technical_feasibility: 60,
      financial_viability: 50,
      operational_readiness: 50,
      risk_tolerance: 55,
      resource_availability: 45,
    },
    environment_score: 42,
    environment_factors: {
      software_completeness: 30,
      hardware_currency: 40,
      process_documentation: 55,
      vendor_diversity: 45,
    },
    growth_opportunities: [],
    risk_factors: [
      { category: 'Compliance', description: 'Missing certifications' },
    ],
    sales_approach: {
      approach: 'direct',
      urgency: 'high',
      focus: 'compliance',
      talking_points: ['audit', 'deadline'],
      timing: 'ASAP',
      next_steps: ['remediate', 'verify'],
    },
    created_at: '2026-02-10T08:00:00Z',
    updated_at: '2026-03-25T11:00:00Z',
  },
];

const mockPreview = {
  customer: { id: 5, name: 'Acme Corp', vertical: 'Manufacturing' },
  persona: { id: null, label: 'Generic (no persona selected)' },
  available_intelligence: {
    technology_items: 2, sales_notes: 1, knowledge_entries: 0,
    use_cases: { total: 2, scored: 1 }, eol_tech_count: 1,
    critical_tech_at_risk_count: 1, notes_stale: false,
  },
  generation_intent: 'Deterministic, rule-based sales evaluation for Acme Corp, framed for Generic; no LLM inference.',
  sections: {},
  discovery_gaps: [{ area: 'technology_inventory', gap: 'No technology inventory recorded', action: 'Run an inventory discovery session' }],
  source_context: {},
};

const { apiMock } = vi.hoisted(() => ({
  apiMock: {
    listSalesEvaluations: vi.fn(),
    createSalesEvaluation: vi.fn(),
    createSalesEvaluationWithPersona: vi.fn(),
    updateSalesEvaluation: vi.fn(),
    deleteSalesEvaluation: vi.fn(),
    listSalesPersonas: vi.fn(),
    previewSalesEvaluation: vi.fn(),
    getAccountWorkspace: vi.fn(),
  },
}));

vi.mock('../src/lib/api', () => ({
  api: apiMock,
  getAuthUsername: () => 'admin',
  getAuthIsAdmin: () => true,
  getAuthSalesRole: () => null,
}));

describe('SalesEvaluation component', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    apiMock.listSalesEvaluations.mockResolvedValue(mockEvaluations);
    apiMock.createSalesEvaluation.mockResolvedValue(undefined);
    apiMock.createSalesEvaluationWithPersona.mockResolvedValue(mockEvaluations[0]);
    apiMock.deleteSalesEvaluation.mockResolvedValue(undefined);
    apiMock.listSalesPersonas.mockResolvedValue([{ id: 'security', label: 'Security Leader' }]);
    apiMock.previewSalesEvaluation.mockResolvedValue(mockPreview);
    // the generation panel surfaces the available intelligence
    // from the account-workspace endpoint (advisory — the component guards
    // against non-object responses).
    apiMock.getAccountWorkspace.mockResolvedValue({
      technology_landscape: { total: 2, eol_count: 1, unsupported_count: 0, at_risk_count: 1, key_vendors: [], important_gaps: [] },
      knowledge: { total: 0, unprocessed_count: 0, days_since_latest: null, latest_uploaded: null, recently_added_count: 0 },
      sales_activity: { total_notes: 1, notes_stale: false, days_since_last_interaction: 3, last_interaction: null, recent: [], active_observations: [] },
      assessment: { total_count: 2, scored_count: 1, unscored_count: 1, average_score: 72, active_assessment: null, top_use_cases: [] },
    });
  });

  it('renders the evaluations list once the api resolves', async () => {
    render(<SalesEvaluation customerId={5} />);

    // Loading state first, then the list after the mocked fetch resolves.
    const select = await screen.findByLabelText('Select evaluation');
    expect(select).not.toBeNull();
    expect(screen.getByText('2 found')).toBeTruthy();
    expect(screen.getByRole('button', { name: /generate evaluation/i })).toBeTruthy();
    // persona select + Refresh-Preview button are present
    // (the preview is auto-computed on load/persona-change; the button
    // remains as an explicit re-run, labeled "Refresh Preview").
    expect(screen.getByLabelText('Select persona')).toBeTruthy();
    expect(screen.getByRole('button', { name: /Refresh Preview/i })).toBeTruthy();
  });

  it('renders evaluation sections after selecting an evaluation', async () => {
    render(<SalesEvaluation customerId={5} />);

    const select = await screen.findByLabelText('Select evaluation');
    // Option values are the list index (0 = first evaluation; -1 = placeholder).
    fireEvent.change(select, { target: { value: '0' } });

    expect(await screen.findByText('72.0')).toBeTruthy();
    // Each appears exactly twice: once in the per-dimension bars block,
    // once as a row label in the embedded GapAnalysis matrix.
    expect(screen.getAllByText('technical_feasibility').length).toBe(2);
    expect(screen.getAllByText('software_completeness').length).toBe(2);
    expect(screen.getByText('Risk Factors')).toBeTruthy();
    expect(screen.getByText('Growth Opportunities')).toBeTruthy();
    expect(screen.getByText(/Urgency:/i)).toBeTruthy();
    expect(screen.getByText(/Gap Analysis/)).toBeTruthy();
  });

  it('calls createSalesEvaluationWithPersona with (customerId, name, null) when generate is clicked', async () => {
    render(<SalesEvaluation customerId={5} />);

    const nameInput = await screen.findByPlaceholderText(/Evaluation name/i);
    fireEvent.change(nameInput, { target: { value: 'Test Evaluation' } });

    const generateBtn = screen.getByRole('button', { name: /Generate Evaluation/i });
    expect((generateBtn as HTMLButtonElement).disabled).toBe(false);
    await fireEvent.click(generateBtn);

    // Default persona is '' -> passed as null.
    expect(apiMock.createSalesEvaluationWithPersona).toHaveBeenCalledWith(5, 'Test Evaluation', null);
  });

  it('passes the selected persona to createSalesEvaluationWithPersona', async () => {
    render(<SalesEvaluation customerId={5} />);

    const personaSelect = await screen.findByLabelText('Select persona');
    fireEvent.change(personaSelect, { target: { value: 'security' } });
    const nameInput = screen.getByPlaceholderText(/Evaluation name/i);
    fireEvent.change(nameInput, { target: { value: 'Persona Eval' } });

    await fireEvent.click(screen.getByRole('button', { name: /Generate Evaluation/i }));

    expect(apiMock.createSalesEvaluationWithPersona).toHaveBeenCalledWith(5, 'Persona Eval', 'security');
  });

  it('auto-computes the pre-generation preview on load (no manual click required)', async () => {
    render(<SalesEvaluation customerId={5} />);
    await screen.findByPlaceholderText(/Evaluation name/i);

    // The preview is fetched on mount (persona null) and rendered
    // automatically — the "Refresh Preview" button is only an explicit
    // re-run, not a prerequisite.
    expect(apiMock.previewSalesEvaluation).toHaveBeenCalledWith(5, null);
    expect(await screen.findByText(/Pre-generation preview/)).toBeTruthy();
    expect(screen.getByText('Discovery gaps (missing knowledge):')).toBeTruthy();
  });

  it('refreshes the preview when the persona changes and passes the persona', async () => {
    render(<SalesEvaluation customerId={5} />);
    await screen.findByPlaceholderText(/Evaluation name/i);
    expect(apiMock.previewSalesEvaluation).toHaveBeenCalledTimes(1);
    expect(apiMock.previewSalesEvaluation).toHaveBeenNthCalledWith(1, 5, null);

    const personaSelect = screen.getByLabelText('Select persona');
    fireEvent.change(personaSelect, { target: { value: 'security' } });
    // The effect re-runs with the selected persona.
    await vi.waitFor(() => expect(apiMock.previewSalesEvaluation).toHaveBeenCalledTimes(2));
    expect(apiMock.previewSalesEvaluation).toHaveBeenLastCalledWith(5, 'security');
  });

  it('surfaces the available customer intelligence in the generation panel', async () => {
    render(<SalesEvaluation customerId={5} />);
    // The context block renders once the workspace resolves (the mock
    // resolves with non-zero counts). Scope to the block's container so the
    // assertions are unambiguous — the pre-generation preview block also
    // lists some of the same domain labels.
    const heading = await screen.findByText('Customer intelligence feeding this evaluation');
    const section = heading.closest('div')!.parentElement!;
    expect(within(section).getByText('Technologies known')).toBeTruthy();
    expect(within(section).getByText('Sales notes')).toBeTruthy();
    expect(within(section).getByText('Knowledge sources')).toBeTruthy();
    expect(within(section).getByText('Use cases (scored/total)')).toBeTruthy();
    expect(within(section).getByText('EOL technology')).toBeTruthy();
  });

  it('shows the selected persona context (description, technical depth, concerns) in the generation panel', async () => {
    apiMock.listSalesPersonas.mockResolvedValue([
      {
        id: 'security',
        label: 'Security Leader',
        description: 'CISO — owns risk, compliance, and the security stack.',
        technical_depth: 'high',
        business_framing: 'risk reduction and audit readiness',
        concerns: ['compliance gaps', 'vendor lock-in'],
        focus_dimensions: [],
        question_base: [],
        priority_angles: [],
        next_action_angles: [],
      },
    ]);
    render(<SalesEvaluation customerId={5} />);
    const personaSelect = await screen.findByLabelText('Select persona');
    fireEvent.change(personaSelect, { target: { value: 'security' } });

    // The persona's lens is visible — not just a dropdown label.
    expect(await screen.findByText('CISO — owns risk, compliance, and the security stack.')).toBeTruthy();
    expect(screen.getByText(/Technical depth: high · Framing: risk reduction and audit readiness/)).toBeTruthy();
    expect(screen.getByText(/Concerns: compliance gaps, vendor lock-in/)).toBeTruthy();
  });

  it('shows an error message when the create call fails', async () => {
    apiMock.createSalesEvaluationWithPersona.mockRejectedValue(new Error('API error'));
    render(<SalesEvaluation customerId={5} />);

    const nameInput = await screen.findByPlaceholderText(/Evaluation name/i);
    fireEvent.change(nameInput, { target: { value: 'Test Evaluation' } });

    const generateBtn = screen.getByRole('button', { name: /Generate Evaluation/i });
    await fireEvent.click(generateBtn);

    expect(await screen.findByText(/API error/)).toBeTruthy();
  });

  it('renders a Delete button when an evaluation is selected', async () => {
    render(<SalesEvaluation customerId={5} />);

    const select = await screen.findByLabelText('Select evaluation');
    fireEvent.change(select, { target: { value: '0' } });

    expect(await screen.findByRole('button', { name: /^Delete$/i })).toBeTruthy();
  });

  it('renders persona sections when an evaluation has persona_sections', async () => {
    const withPersona = {
      ...mockEvaluations[0],
      persona: 'security',
      persona_sections: {
        persona: 'security',
        sections: {
          account_snapshot: {
            label: 'derived — deterministic aggregation',
            content: { customer: 'Acme Corp', readiness_overall: 72 },
          },
          observed_gaps: {
            label: 'evidence-based',
            content: [{ category: 'eol', description: 'EOL tech', persona_relevant: true }],
          },
        },
        discovery_gaps: [],
      },
    };
    apiMock.listSalesEvaluations.mockResolvedValue([withPersona]);
    render(<SalesEvaluation customerId={5} />);

    const select = await screen.findByLabelText('Select evaluation');
    fireEvent.change(select, { target: { value: '0' } });

    expect(await screen.findByText(/Persona Sections/)).toBeTruthy();
    expect(screen.getByText(/derived — deterministic aggregation/)).toBeTruthy();
  });
});
