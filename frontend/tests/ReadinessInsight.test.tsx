/**
 * WP33 — the persisted, LLM-generated per-customer "Readiness Insight" panel
 * rendered inside the Readiness Insights block (AnalyticsDashboard,
 * section="correlation"), between the deterministic so-what strip and the
 * "Organization Use Case Readiness" heading.
 *
 * Contract locked in here:
 *   (a) a cached insight renders its summary, all three columns (Strengths /
 *       Watch items / Priorities) with their items, and the missing-note
 *       callout when insight_data.missing_note is set;
 *   (b) no insight + state.ready === true  -> "Generate readiness insight"
 *       button enabled;
 *   (c) no insight + state.ready === false -> button disabled + the
 *       "still unscored or not completed" hint;
 *   (d) stale === true -> the regenerate hint + button label
 *       "Regenerate insight";
 *   (e) no customer selected -> no insight panel renders at all (and the
 *       insight endpoint is never called).
 *
 * The deterministic block (so-what strip, readiness bands, dimension
 * profile) is untouched and is not asserted here.
 */
import { describe, it, expect, vi, afterEach } from 'vitest';
import { act, fireEvent, render, screen, cleanup, waitFor } from '@testing-library/react';
import { AnalyticsDashboard } from '../src/components/AnalyticsDashboard';

type InsightResponse = {
  insight: unknown;
  state: {
    total: number; included: number; unscored: number; not_completed: number;
    missing_count: number; ready: boolean; all_scored: boolean; all_completed: boolean;
  };
  stale: boolean;
};

const { state, apiStub, generateInsight } = vi.hoisted(() => {
  const useCases = [
    { id: 1, title: 'Scored UC', department: 'Ops', status: 'completed', overall_score: 72, estimated_savings: 1000, estimated_revenue: 0, scores: {} },
    { id: 2, title: 'Unscored UC', department: 'Ops', status: 'draft', overall_score: null, estimated_savings: 0, estimated_revenue: 0, scores: {} },
  ];
  const state = {
    insightResponse: null as InsightResponse | null,
    insightCalls: 0,
  };
  const generateInsight = vi.fn(() => Promise.resolve(state.insightResponse?.insight));
  const methods: Record<string, (...args: any[]) => Promise<any>> = {
    list: () => Promise.resolve(useCases),
    getMyCustomers: () => Promise.resolve([]),
    listCustomers: () => Promise.resolve([]),
    readinessInsight: () => {
      state.insightCalls += 1;
      return Promise.resolve(state.insightResponse);
    },
    generateReadinessInsight: generateInsight,
  };
  const fallback = () => Promise.resolve([]);
  const apiStub = new Proxy({}, {
    get: (_t, prop) => (typeof prop === 'string' && methods[prop] ? methods[prop] : fallback),
  });
  return { state, apiStub, generateInsight };
});

vi.mock('../src/lib/api', () => ({
  api: apiStub,
  clearAuth: vi.fn(),
  getAuthUsername: () => 'admin',
  getAuthIsAdmin: () => false,
  getAuthSalesRole: () => null,
}));

const CONTEXT = {
  total_use_cases: 2, included_count: 1, missing_count: 1,
  missing_reasons: { unscored: 1, not_completed: 0 },
  missing_titles: ['Unscored UC'],
  average_score: 72, weakest_dimension: null, strongest_dimension: null,
  departments: [], top_use_cases: [], lowest_use_cases: [],
  total_impact: 1000, generated_at: '2026-09-03T10:00:00Z',
};

function makeInsight(overrides: Record<string, unknown> = {}) {
  return {
    id: 5, customer_id: 7, customer_name: 'Acme',
    insight_data: {
      summary: 'Acme is broadly on track with a few gaps.',
      strengths: ['Strong data foundation', 'Executive sponsorship'],
      weaknesses: ['Thin ML ops coverage'],
      priorities: ['Stand up a model registry', 'Backfill unscored use cases'],
      context: CONTEXT,
      missing_note: '1 use case is unscored and was excluded.',
      model_used: true,
      ...overrides,
    },
    data_fingerprint: 'abc123',
    model: 'claude-sonnet-5',
    generated_by: 'admin',
    status: 'completed',
    generated_at: '2026-09-03T10:00:00Z',
  };
}

const readyState = { total: 2, included: 2, unscored: 0, not_completed: 0, missing_count: 0, ready: true, all_scored: true, all_completed: true };
const notReadyState = { total: 5, included: 3, unscored: 2, not_completed: 0, missing_count: 2, ready: false, all_scored: false, all_completed: false };

afterEach(() => {
  cleanup();
  state.insightResponse = null;
  state.insightCalls = 0;
  generateInsight.mockClear();
});

describe('WP33 — Readiness Insight panel', () => {
  it('(a) renders a cached insight: summary, all three columns, missing-note callout', async () => {
    state.insightResponse = { insight: makeInsight(), state: readyState, stale: false };
    render(<AnalyticsDashboard section="correlation" selectedCustomerId={7} />);

    await screen.findByText('Acme is broadly on track with a few gaps.');
    expect(screen.getByText('Strengths')).toBeTruthy();
    expect(screen.getByText('Watch items')).toBeTruthy();
    expect(screen.getByText('Priorities')).toBeTruthy();
    expect(screen.getByText('Strong data foundation')).toBeTruthy();
    expect(screen.getByText('Thin ML ops coverage')).toBeTruthy();
    expect(screen.getByText('Stand up a model registry')).toBeTruthy();
    expect(screen.getByText('1 use case is unscored and was excluded.')).toBeTruthy();
  });

  it('(b) no insight + state.ready === true -> Generate button enabled', async () => {
    state.insightResponse = { insight: null, state: readyState, stale: false };
    render(<AnalyticsDashboard section="correlation" selectedCustomerId={7} />);

    const btn = await screen.findByRole('button', { name: 'Generate readiness insight' });
    expect(btn.textContent).toBe('Generate readiness insight');
    expect(btn.hasAttribute('disabled')).toBe(false);
  });

  it('(c) no insight + state.ready === false -> Generate button disabled + hint', async () => {
    state.insightResponse = { insight: null, state: notReadyState, stale: false };
    render(<AnalyticsDashboard section="correlation" selectedCustomerId={7} />);

    const btn = await screen.findByRole('button', { name: 'Generate readiness insight' });
    expect(btn.hasAttribute('disabled')).toBe(true);
    expect(screen.getByText('2 of 5 use cases are still unscored or not completed')).toBeTruthy();
  });

  it('(d) stale === true -> regenerate hint + button label "Regenerate insight"', async () => {
    state.insightResponse = { insight: makeInsight(), state: readyState, stale: true };
    render(<AnalyticsDashboard section="correlation" selectedCustomerId={7} />);

    await screen.findByText(/Scores have changed since this insight was generated/);
    const btn = screen.getByRole('button', { name: 'Regenerate insight' });
    expect(btn.textContent).toBe('Regenerate insight');
  });

  it('(e) no customer selected -> no insight panel and the endpoint is never called', async () => {
    state.insightResponse = { insight: makeInsight(), state: readyState, stale: false };
    render(<AnalyticsDashboard section="correlation" />);

    // The deterministic readiness block still renders.
    await screen.findByText('Organization Use Case Readiness');
    expect(screen.queryByText('Readiness Insight')).toBeNull();
    // (UX audit #8: the label is now the dynamic insight action text, so the
    // absence is proven via the visible label instead of the old generic one.)
    expect(screen.queryByRole('button', { name: 'Generate readiness insight' })).toBeNull();
    await waitFor(() => expect(state.insightCalls).toBe(0));
  });
});

it('keeps insight generation named and blocked until a failure is reported', async () => {
  state.insightResponse = { insight: null, state: readyState, stale: false };
  let reject!: (error: Error) => void;
  generateInsight.mockReturnValueOnce(new Promise((_, r) => { reject = r; }));
  render(<AnalyticsDashboard section="correlation" selectedCustomerId={7} />);
  const button = await screen.findByRole('button', { name: 'Generate readiness insight' }) as HTMLButtonElement;
  fireEvent.click(button);
  expect(button.disabled).toBe(true);
  expect(button.getAttribute('aria-busy')).toBe('true');
  expect(button.textContent).toBe('Generate readiness insight');
  fireEvent.click(button);
  expect(generateInsight).toHaveBeenCalledTimes(1);
  await act(async () => reject(new Error('Synthetic inference outage')));
  expect((await screen.findByRole('alert')).textContent).toContain('Synthetic inference outage');
  expect(button.disabled).toBe(false);
});
