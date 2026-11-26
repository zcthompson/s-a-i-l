/**
 * Regression tests (long AI operations had no
 * progress, no cancel, no busy state):
 *
 *   (a) the full-screen overlay is named per operation ("Scoring
 *       '<title>'…") with elapsed time instead of the generic
 *       "Loading content…";
 *   (b) the customer-detail scoring buttons are disabled + labelled
 *       "Scoring…" while the fetch is in flight (busy prop on the shared
 *       UseCaseDetail);
 *   (c) the overlay's Cancel aborts the pending fetch (AbortSignal
 *       asserted) — the error banner shows the clear cancel message;
 *   (d) a WS "scoring" event for the selected use case triggers a single
 *       api.get(id) refresh (background score completion lands without a
 *       manual reload).
 *
 * The score stub hangs by design (a real model call takes ~30s+) and
 * rejects with the api-layer cancel message when the signal aborts —
 * mirroring fetch's AbortError behavior.
 */
import { describe, it, expect, vi, afterEach, beforeAll } from 'vitest';
import { render, screen, cleanup, fireEvent, act, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { Home } from '../src/pages/Home';

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
  // UNSCORED (overall_score null) — the "⚡ Score" row action and the
  // detail's "⚡ Run Scoring" button only render for unscored use cases.
  const seededUc = {
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
    estimated_savings: 120000,
    estimated_revenue: 40000,
    timeline_estimate: '2 quarters',
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
    scoreShouldHang: true,
    scoreCalls: [] as number[],
    lastSignal: null as AbortSignal | null,
    getCalls: [] as number[],
    wsHandlers: [] as Array<(m: { type: string; data: unknown; timestamp: string }) => void>,
  };
  return { state, customer, seededUc };
});

const { apiStub } = vi.hoisted(() => {
  const methods: Record<string, (...args: any[]) => Promise<any>> = {
    getWorkspaceActions: (id: number) => Promise.resolve({ customer_id: id, capabilities: { use_case: true, assessment: true }, assignees: [] }),
    listCustomers: () => Promise.resolve([customer]),
    getCustomer: () => Promise.resolve({ ...customer, use_case_count: 1 }),
    getCustomerUseCases: () => Promise.resolve([seededUc]),
    listVerticals: () => Promise.resolve({ verticals: [], departments_by_vertical: {} }),
    listDepartments: () => Promise.resolve([]),
    listAssessments: () => Promise.resolve([]),
    checkAccess: () => Promise.resolve({ has_access: true, permission_level: 'owner' }),
    getNotifications: () => Promise.resolve([]),
    getMyCustomers: () => Promise.resolve([]),
    list: () => Promise.resolve([seededUc]),
    getComments: () => Promise.resolve([]),
    get: (id: number) => {
      state.getCalls.push(id);
      return Promise.resolve({ ...seededUc, overall_score: 73.1, scored_at: '2026-09-01T12:00:00Z' });
    },
    // Hangs until the signal aborts (mirrors a real ~30s+ model call),
    // then rejects with the api-layer cancel message (fetch AbortError).
    score: (id: number, signal?: AbortSignal) => {
      state.scoreCalls.push(id);
      state.lastSignal = signal ?? null;
      return new Promise((resolve, reject) => {
        const onAbort = () => reject(new Error('Operation cancelled — the server may still be finishing the work.'));
        if (signal?.aborted) { onAbort(); return; }
        signal?.addEventListener('abort', onAbort, { once: true });
        if (!state.scoreShouldHang) {
          resolve({
            use_case: seededUc,
            scores: { dimension_scores: [], overall_score: 73.1, reasoning: null, scored_at: '2026-09-01T12:00:00Z', recommendations: [] },
          });
        }
      });
    },
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
  state.scoreShouldHang = true;
  state.scoreCalls = [];
  state.lastSignal = null;
  state.getCalls = [];
  state.wsHandlers = [];
});

function renderApp(entry = '/?view=assessment-list') {
  render(
    <MemoryRouter initialEntries={[entry]}>
      <Home />
    </MemoryRouter>,
  );
}

describe('long-operation feedback', () => {
  it('(a) the overlay names the scoring operation while the fetch is in flight', async () => {
    renderApp();
    const scoreBtn = await screen.findByText('⚡ Score');
    fireEvent.click(scoreBtn);
    // Named label (not the generic "Loading content…") + the Cancel control.
    await screen.findByText(/Scoring 'Improve operational efficiency'/);
    expect(screen.getByRole('button', { name: 'Cancel long operation' })).toBeTruthy();
  });

  it('(c) Cancel aborts the pending fetch (AbortSignal asserted) and shows the cancel message', async () => {
    renderApp();
    const scoreBtn = await screen.findByText('⚡ Score');
    fireEvent.click(scoreBtn);
    await screen.findByText(/Scoring 'Improve operational efficiency'/);
    fireEvent.click(screen.getByRole('button', { name: 'Cancel long operation' }));
    // The abort lands: the banner shows the clear message and the overlay is gone.
    await screen.findByText('Operation cancelled — the server may still be finishing the work.');
    expect(state.lastSignal?.aborted).toBe(true);
    expect(screen.queryByText(/Scoring 'Improve operational efficiency'/)).toBeNull();
  });

  it('(b) the customer-detail Run Scoring button is disabled + labelled while busy', async () => {
    renderApp('/?view=customers');
    const customerRow = await screen.findByRole('button', { name: 'Select customer Energy Test Company' });
    fireEvent.click(customerRow);
    // the use-case table lives under Assessments ▸ Use Cases.
    fireEvent.click(await screen.findByRole('tab', { name: 'Navigate to Discovery & Value' }));
    fireEvent.click(screen.getByRole('tab', { name: 'Navigate to Use Cases' }));
    const row = await screen.findByRole('button', { name: 'Open assessment Improve operational efficiency' });
    fireEvent.click(row);
    const runBtn = await screen.findByRole('button', { name: 'Run scoring assessment' });
    expect(runBtn.hasAttribute('disabled')).toBe(false);
    fireEvent.click(runBtn);
    // Busy surface: the "Scoring…" label + the disabled button (busy prop).
    await screen.findByText('Scoring…');
    expect(screen.getByRole('button', { name: 'Run scoring assessment' }).hasAttribute('disabled')).toBe(true);
  });

  it('(d) a WS scoring event for the selected use case triggers a re-fetch of that use case', async () => {
    renderApp();
    // Select the use case (assessment-list → detail view).
    const row = (await screen.findByText('Improve operational efficiency')).closest('tr')!;
    fireEvent.click(within(row).getByText('📊 View'));
    await screen.findByRole('heading', { level: 1, name: 'Improve operational efficiency' });
    expect(state.getCalls).toHaveLength(0);
    // Fire the scoring event (the deterministic notification-row shape from
    // backend/services/scoring.py) through the captured WS handler.
    await act(async () => {
      state.wsHandlers.forEach((h) => h({
        type: 'scoring',
        data: {
          user_name: 'admin',
          customer_id: 7,
          message: "Use case 'Improve operational efficiency' has been scored with an overall readiness score of 73/100.",
        },
        timestamp: '2026-09-01T12:00:00Z',
      }));
    });
    expect(state.getCalls).toContain(seededUc.id);
  });
});
