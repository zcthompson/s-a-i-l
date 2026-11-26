/**
 * generic customer assessments — frontend.
 *
 *  - Rounds rail: each round shows a type chip (AI / Generic) + its purpose
 *    line when non-empty (an empty/blank purpose renders nothing).
 *  - Create-round flow: an explicit type choice (neither option preselected;
 *    + New Round disabled until chosen); `type` + optional `purpose` sent.
 *  - Template bootstrap is AI-only: generic → the picker is replaced by the
 *    honest label and the blank form.
 *  - Scoring entry points on a generic round's use cases are replaced by
 *    "AI scoring requires an AI assessment" (detail + Bulk Score); AI-round
 *    and legacy (NULL round) use cases keep the enabled controls.
 *  - The backend 422 detail surfaces verbatim if the endpoint is reached.
 *
 * Conventions: repo test pattern (vi.hoisted + vi.mock factory), jsdom.
 */
import { afterEach, beforeAll, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';

const GENERIC_422 = 'AI scoring is not available on generic assessments';

const { state } = vi.hoisted(() => {
  const state: {
    assessments: Array<Record<string, unknown>> | Error;
    useCases: Array<Record<string, unknown>>;
    createCalls: Array<{ customer: string; name: string; opts: unknown }>;
    templateCalls: Array<{ customer: string; templateId: string }>;
    scoreError: Error | null;
  } = { assessments: [], useCases: [], createCalls: [], templateCalls: [], scoreError: null };
  return { state };
});

vi.mock('../src/lib/api', () => ({
  api: new Proxy({}, {
    get: (_t, prop) => {
      switch (prop) {
        case 'getWorkspaceActions': return async (id: number) => ({ customer_id: id, capabilities: { use_case: true, assessment: true }, assignees: [] });
        case 'checkAccess': return async () => ({ has_access: true, permission_level: 'owner' });
        case 'getCustomer': return async (name: string) => ({ id: 1, name, departments: [] });
        case 'listCustomers': return async () => [{ id: 1, name: 'Acme' }];
        case 'listVerticals': return async () => ({ verticals: [], departments_by_vertical: {} });
        case 'listAssessments': return async () => {
          if (state.assessments instanceof Error) throw state.assessments;
          return state.assessments;
        };
        case 'getCustomerUseCases': return async () => state.useCases;
        case 'list': return async () => state.useCases;
        case 'createAssessment': return async (customer: string, name: string, opts?: unknown) => {
          state.createCalls.push({ customer, name, opts });
          return { id: 99, name, status: 'active' };
        };
        case 'startTemplateAssessment': return async (customer: string, templateId: string) => {
          state.templateCalls.push({ customer, templateId });
          return {};
        };
        case 'score': return async () => { if (state.scoreError) throw state.scoreError; return {}; };
        default: return async () => [];
      }
    },
  }),
  getAuthIsAdmin: () => false,
  getAuthSalesRole: () => null,
  getAuthUsername: () => 'owner',
  clearAuth: vi.fn(),
}));
vi.mock('../src/lib/websocket', () => ({ ws: { connect: vi.fn(), disconnect: vi.fn(), subscribe: () => vi.fn() } }));
vi.mock('../src/components/CustomerHeader', () => ({ CustomerHeader: (props: any) => <h1>{props.name}</h1> }));
vi.mock('../src/components/AccountOverview', () => ({ AccountOverview: () => null, IntelligencePanels: () => null }));

import { CustomerDashboard } from '../src/pages/CustomerDashboard';

beforeAll(() => {
  if (typeof Element !== 'undefined' && !Element.prototype.scrollTo) {
    Element.prototype.scrollTo = function () { return undefined; };
  }
});

afterEach(() => {
  cleanup();
  state.assessments = [];
  state.useCases = [];
  state.createCalls = [];
  state.templateCalls = [];
  state.scoreError = null;
});

const round = (over: Record<string, unknown>) => ({
  id: 1, customer_id: 1, name: 'Round', status: 'active', created_by: 'owner',
  created_at: '2026-10-01T00:00:00Z', archived_at: null, use_case_count: 0,
  assessment_type: 'ai', purpose: null, ...over,
});
const useCase = (over: Record<string, unknown>) => ({
  id: 10, title: 'UC', description: '', customer_id: 1, customer_name: 'Acme',
  department: null, status: 'draft', goals: [], challenges: [], pain_points: [],
  scores: null, overall_score: null, scored_at: null,
  created_at: '2026-10-01T00:00:00Z', updated_at: '2026-10-01T00:00:00Z', ...over,
});

const tab = (label: string) => screen.getByRole('tab', { name: `Navigate to ${label}` });

async function openArea(label: string) {
  render(<MemoryRouter><CustomerDashboard onNavigate={vi.fn()} selectedCustomerName="Acme" /></MemoryRouter>);
  await screen.findByRole('heading', { name: 'Acme' });
  fireEvent.click(tab('Discovery & Value'));
  if (label !== 'Rounds') fireEvent.click(tab(label));
  if (label === 'Rounds') { fireEvent.click(await screen.findByText('New assessment round', { selector: 'summary' })); fireEvent.click(screen.getByText('Start a new assessment', { selector: 'summary' })); }
}

describe('round rows: type chip + purpose line', () => {
  it('renders AI / Generic chips and the purpose line', async () => {
    state.assessments = [
      round({ id: 1, name: 'Q3 AI', status: 'archived', assessment_type: 'ai', purpose: 'Baseline readiness' }),
      round({ id: 2, name: 'Discovery', assessment_type: 'generic', purpose: 'Map the ops pain points' }),
    ];
    await openArea('Rounds');
    expect((await screen.findByTestId('round-type-1')).textContent).toBe('AI');
    expect(screen.getByTestId('round-type-2').textContent).toBe('Generic');
    expect(screen.getByTestId('round-purpose-1').textContent).toBe('Baseline readiness');
    expect(screen.getByTestId('round-purpose-2').textContent).toBe('Map the ops pain points');
  });

  it.each([null, '', '   '])('renders no purpose line for purpose=%j', async (purpose) => {
    state.assessments = [round({ id: 3, name: 'Quiet', assessment_type: 'generic', purpose })];
    await openArea('Rounds');
    const chip = await screen.findByTestId('round-type-3');
    expect(screen.queryByTestId('round-purpose-3')).toBeNull();
    // the round cell holds only the name + chip — no empty line / placeholder
    expect(chip.parentElement!.textContent).toBe('QuietGeneric');
  });
});

describe('create flow: explicit type choice', () => {
  it('has two unselected type options and keeps + New Round disabled until one is chosen', async () => {
    await openArea('Rounds');
    const group = await screen.findByRole('radiogroup', { name: 'Round type' });
    const ai = within(group).getByLabelText('AI readiness assessment (dimension scoring, forecasts, readiness insight)') as HTMLInputElement;
    const generic = within(group).getByLabelText('Generic discovery assessment (no AI scoring)') as HTMLInputElement;
    expect(ai.checked).toBe(false);
    expect(generic.checked).toBe(false);
    fireEvent.change(screen.getByLabelText('New round name'), { target: { value: 'Q4' } });
    const create = screen.getByRole('button', { name: 'Create assessment round' }) as HTMLButtonElement;
    expect(create.disabled).toBe(true);
    fireEvent.click(generic);
    expect(create.disabled).toBe(false);
    fireEvent.click(ai);
    expect(ai.checked).toBe(true);
    expect(generic.checked).toBe(false);
  });

  it('generic → blank-only (templates hidden with the honest label) and sends type + purpose', async () => {
    await openArea('Rounds');
    fireEvent.change(await screen.findByLabelText('New round name'), { target: { value: 'Discovery' } });
    fireEvent.click(screen.getByLabelText('Generic discovery assessment (no AI scoring)'));
    expect(screen.getByText('Templates are AI use-case templates — generic rounds start blank')).toBeTruthy();
    expect(screen.queryByRole('button', { name: 'Start blank assessment' })).toBeNull();
    fireEvent.change(screen.getByLabelText('Round purpose (optional)'), { target: { value: '  Ops discovery  ' } });
    fireEvent.click(screen.getByRole('button', { name: 'Create assessment round' }));
    await waitFor(() => expect(state.createCalls).toHaveLength(1));
    expect(state.createCalls[0]).toEqual({ customer: 'Acme', name: 'Discovery', opts: { type: 'generic', purpose: 'Ops discovery' } });
    expect(state.templateCalls).toHaveLength(0);
  });

  it('ai → sends type ai (no purpose key when blank) and keeps the template picker', async () => {
    await openArea('Rounds');
    fireEvent.change(await screen.findByLabelText('New round name'), { target: { value: 'Q4 AI' } });
    fireEvent.click(screen.getByLabelText('AI readiness assessment (dimension scoring, forecasts, readiness insight)'));
    expect(screen.queryByText('Templates are AI use-case templates — generic rounds start blank')).toBeNull();
    expect(screen.getByText(/Pick an AI template/)).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: 'Create assessment round' }));
    await waitFor(() => expect(state.createCalls).toHaveLength(1));
    expect(state.createCalls[0]).toEqual({ customer: 'Acme', name: 'Q4 AI', opts: { type: 'ai' } });
  });

  it('an active generic round hides the template picker too', async () => {
    state.assessments = [round({ id: 4, assessment_type: 'generic' })];
    await openArea('Rounds');
    expect(await screen.findByText('Templates are AI use-case templates — generic rounds start blank')).toBeTruthy();
  });
});

describe('scoring entry points', () => {
  const openDetail = async (title: string) => {
    await openArea('Use Cases');
    fireEvent.click(await screen.findByRole('button', { name: `Open assessment ${title}` }));
  };

  it('generic-round use case: detail scoring controls replaced by the exact label', async () => {
    state.assessments = [round({ id: 5, assessment_type: 'generic' })];
    state.useCases = [useCase({ id: 11, title: 'Generic UC', assessment_id: 5 })];
    await openDetail('Generic UC');
    expect(await screen.findByText('AI scoring requires an AI assessment')).toBeTruthy();
    expect(screen.queryByRole('button', { name: 'Run scoring assessment' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'Re-score use case' })).toBeNull();
  });

  it.each([
    ['AI-round', 6],
    ['legacy (NULL round)', null],
  ])('%s use case: Run Scoring stays enabled (parity)', async (_label, assessmentId) => {
    state.assessments = [round({ id: 6, assessment_type: 'ai' })];
    state.useCases = [useCase({ id: 12, title: 'AI UC', assessment_id: assessmentId })];
    await openDetail('AI UC');
    const btn = await screen.findByRole('button', { name: 'Run scoring assessment' }) as HTMLButtonElement;
    expect(btn.disabled).toBe(false);
    expect(screen.queryByText('AI scoring requires an AI assessment')).toBeNull();
  });

  it('Bulk Score: generic-round rows are disabled with the label; AI rows stay selectable', async () => {
    state.assessments = [round({ id: 7, assessment_type: 'generic' }), round({ id: 8, status: 'archived' })];
    state.useCases = [
      useCase({ id: 21, title: 'Gen row', assessment_id: 7 }),
      useCase({ id: 22, title: 'AI row', assessment_id: 8 }),
    ];
    await openArea('Bulk Score');
    const gen = await screen.findByLabelText('Select Gen row — AI scoring requires an AI assessment') as HTMLInputElement;
    expect(gen.disabled).toBe(true);
    const ai = screen.getByLabelText('Select AI row') as HTMLInputElement;
    expect(ai.disabled).toBe(false);
    fireEvent.click(screen.getByRole('button', { name: 'Select all use cases' }));
    expect(screen.getByText('1 selected')).toBeTruthy();
    expect(gen.checked).toBe(false);
  });

  it('the backend 422 detail surfaces verbatim when the score endpoint is reached', async () => {
    // Rounds failed to load → no client-side gate; the server is the boundary.
    state.assessments = new Error('rounds unavailable');
    state.useCases = [useCase({ id: 13, title: 'Ungated UC', assessment_id: 9 })];
    state.scoreError = new Error(GENERIC_422);
    await openDetail('Ungated UC');
    fireEvent.click(await screen.findByRole('button', { name: 'Run scoring assessment' }));
    const alert = await screen.findByRole('alert');
    expect(alert.textContent).toContain(GENERIC_422);
  });
});

describe('api layer', () => {
  afterEach(() => vi.unstubAllGlobals());
  const fakeResponse = (status: number, body: string) => ({
    ok: status >= 200 && status < 400, status, statusText: '', text: async () => body,
  });

  it('a 422 string detail from the score endpoint is thrown verbatim', async () => {
    const { api } = await vi.importActual<typeof import('../src/lib/api')>('../src/lib/api');
    vi.stubGlobal('fetch', vi.fn(async () => fakeResponse(422, JSON.stringify({ detail: GENERIC_422 }))));
    await expect(api.score(1)).rejects.toThrow(GENERIC_422);
  });

  it('createAssessment sends type/purpose only when given (existing callers byte-identical)', async () => {
    const { api } = await vi.importActual<typeof import('../src/lib/api')>('../src/lib/api');
    const fetchMock = vi.fn(async () => fakeResponse(201, JSON.stringify({ id: 1 })));
    vi.stubGlobal('fetch', fetchMock);
    await api.createAssessment('Acme', 'R1');
    await api.createAssessment('Acme', 'R2', { type: 'generic', purpose: 'Why' });
    const bodies = (fetchMock.mock.calls as unknown as Array<[string, RequestInit]>).map((c) => c[1].body);
    expect(bodies).toEqual([
      JSON.stringify({ name: 'R1' }),
      JSON.stringify({ name: 'R2', type: 'generic', purpose: 'Why' }),
    ]);
  });
});
