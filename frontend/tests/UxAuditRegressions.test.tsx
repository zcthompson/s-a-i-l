/**
 * UX audit (2026-09-13) regression tests.
 *
 * Covers the audit fixes that changed user-facing behavior:
 *   #1  Global error boundary — a render crash degrades to a reload card
 *       instead of unmounting the whole SPA.
 *   #2  Unknown routes render a real 404 (was: silent bounce to dashboard).
 *   #3  Notification count fetch failure surfaces a "may be out of date"
 *       cue (was: silently swallowed).
 *   #7  Sidebar collapsed preference persists through lib/preferences.
 *   #11 ScoringDashboard no longer renders "Invalid Date" when unscored.
 *   #12 HomeDashboard subtitle pluralizes the counts.
 *   #15 UI version comes from package.json (single source of truth).
 *
 * Conventions: repo test pattern (vi.hoisted + vi.mock factory), jsdom,
 * tests/ (excluded from the tsc gate — vitest transforms via esbuild).
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, cleanup } from '@testing-library/react';
import React from 'react';

// jsdom lacks ResizeObserver (recharts' ResponsiveContainer needs it) — the
// same stub class the other recharts-rendering test files use.
beforeEach(() => {
  (globalThis as any).ResizeObserver = (globalThis as any).ResizeObserver || class {
    observe() {}
    unobserve() {}
    disconnect() {}
  };
});

// ── #1: Global error boundary ───────────────────────────────────────────────
import { GlobalErrorBoundary } from '../src/components/GlobalErrorBoundary';

const { apiStub, notifFn } = vi.hoisted(() => {
  const notifFn = vi.fn(() => Promise.resolve([]));
  // Home/other modules pull api at import time; a Proxy that resolves every
  // method with [] keeps them renderable (repo pattern, see HomeUrlSync).
  const methods: Record<string, () => Promise<unknown>> = {
    aggregateStats: () => Promise.resolve({
      total_use_cases: 1,
      average_score: 0,
      by_department: {},
      by_status: {},
      impact_summary: { total_impact: 0, total_savings: 0, total_revenue: 0 },
      top_use_cases: [],
    }),
    getCustomersStats: () => Promise.resolve({
      total_customers: 1,
      total_impact: 0,
      total_savings: 0,
      total_revenue: 0,
      customers: [],
    }),
    getNotifications: () => notifFn(),
    markNotificationRead: () => Promise.resolve(undefined),
  };
  const fallback = () => Promise.resolve([]);
  const stub: any = new Proxy(
    {},
    { get: (_t, prop) => (typeof prop === 'string' && methods[prop] ? methods[prop] : fallback) },
  );
  return { apiStub: stub, notifFn };
});

vi.mock('../src/lib/api', () => ({
  api: apiStub,
  getAuthToken: () => 'test-token',
  clearAuth: () => undefined,
  getAuthUsername: () => 'tester',
  getAuthIsAdmin: () => false,
  getAuthSalesRole: () => null,
}));
vi.mock('../src/lib/websocket', () => ({
  ws: { subscribe: vi.fn(() => null) },
}));

function ThrowingChild() {
  throw new Error('boom — render crash');
}

describe('UX audit #1 — global error boundary', () => {
  afterEach(cleanup);
  it('degrades a render crash to a reload card instead of unmounting the app', async () => {
    const spy = vi.spyOn(console, 'error').mockImplementation(() => undefined);
    render(
      <GlobalErrorBoundary>
        <ThrowingChild />
      </GlobalErrorBoundary>,
    );
    expect(await screen.findByRole('alert')).toBeTruthy();
    expect(screen.getByText('Something went wrong')).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Reload the application' })).toBeTruthy();
    // The crash details are logged (the boundary owns the console.error).
    expect(spy).toHaveBeenCalled();
    spy.mockRestore();
  });
});

// ── #2: Unknown route 404 ───────────────────────────────────────────────────
import { App } from '../src/App';

describe('UX audit #2 — unknown routes render a 404', () => {
  afterEach(cleanup);
  it('catch-all renders the NotFound view with the unmatched path', async () => {
    window.history.replaceState({}, '', '/this-route-does-not-exist');
    render(<App />);
    expect(await screen.findByText('Page not found')).toBeTruthy();
    // The unmatched path is shown in a <code> element (text is split from
    // surrounding copy — assert the code element contains it).
    const code = await screen.findByText(/this-route-does-not-exist/, { selector: 'code' });
    expect(code.textContent).toBe('/this-route-does-not-exist');
    const link = screen.getByRole('link', { name: /Back to dashboard/i });
    expect((link as HTMLAnchorElement).getAttribute('href')).toBe('/');
  });
});

// ── #3: Notification count failure is no longer silent ──────────────────────
import { NotificationsPage } from '../src/pages/NotificationsPage';

describe('UX audit #3 — notification count staleness cue', () => {
  afterEach(() => {
    cleanup();
    // Restore the default resolving impl — mockReset alone leaves it returning
    // undefined, which crashes the NEXT test's Promise.all on .length.
    notifFn.mockReset();
    notifFn.mockImplementation(() => Promise.resolve([]));
  });

  it('shows "counts may be out of date" when the count fetch fails', async () => {
    notifFn.mockReset();
    notifFn.mockRejectedValue(new Error('network'));
    render(<NotificationsPage onBack={() => undefined} username="tester" />);
    expect(await screen.findByText(/counts may be out of date/)).toBeTruthy();
  });

  it('does not show the staleness cue once the count fetch succeeds', async () => {
    // The page fires its count fetch on mount AND again from the WS-sub
    // effect (username dep) — keep every call resolving.
    notifFn.mockReset();
    notifFn.mockResolvedValue([]);
    render(<NotificationsPage onBack={() => undefined} username="tester" />);
    // Wait for the counts effect to resolve (the cue must be absent AFTER the
    // fetch lands — not just in the initial pre-load state). 'All caught up'
    // appears in both the subtitle and the empty state — accept either.
    await screen.findAllByText('All caught up');
    // Let the second (effect-driven) count fetch settle too.
    await new Promise((r) => setTimeout(r, 50));
    expect(notifFn).toHaveBeenCalled();
    expect(screen.queryByText(/counts may be out of date/)).toBeNull();
  });
});

// ── #7: Sidebar collapsed preference persistence ────────────────────────────
import { getPreferences, setPreference, resetPreferences } from '../src/lib/preferences';

describe('UX audit #7 — sidebar collapsed preference persists', () => {
  // Node >= 25 ships a global `localStorage` that is undefined unless
  // --localstorage-file is given, and it shadows jsdom's Storage under
  // vitest. Install an in-memory Storage so the test is independent of the
  // Node version (the preferences module reads the global at call time).
  beforeEach(() => {
    const store = new Map<string, string>();
    vi.stubGlobal('localStorage', {
      getItem: (k: string) => (store.has(k) ? store.get(k)! : null),
      setItem: (k: string, v: string) => { store.set(k, String(v)); },
      removeItem: (k: string) => { store.delete(k); },
      clear: () => { store.clear(); },
    });
    resetPreferences();
  });
  afterEach(() => { resetPreferences(); vi.unstubAllGlobals(); });

  it('round-trips through the preferences module (and localStorage)', () => {
    expect(getPreferences().sidebarCollapsed).toBe(false);
    setPreference('sidebarCollapsed', true);
    expect(getPreferences().sidebarCollapsed).toBe(true);
    expect(localStorage.getItem('sail-sidebar-collapsed')).toBe('true');
    resetPreferences();
    expect(getPreferences().sidebarCollapsed).toBe(false);
  });
});

// ── #11: ScoringDashboard "Invalid Date" guard ──────────────────────────────
import { ScoringDashboard } from '../src/components/ScoringDashboard';

describe('UX audit #11 — ScoringDashboard unscored date guard', () => {
  afterEach(cleanup);
  it('renders "— (not scored)" instead of "Invalid Date" when scored_at is absent', async () => {
    const scoredData: any = {
      use_case: { id: 1, title: 'Test use case' },
      scores: {
        dimension_scores: [{ name: 'Strategy', score: 5, weight: 0.2, description: 'ok' }],
        overall_score: 5.0,
        reasoning: 'reasoning',
        scored_at: undefined,
        recommendations: [],
      },
    };
    render(<ScoringDashboard scoredData={scoredData} onBack={() => undefined} />);
    expect(await screen.findByText(/not scored/)).toBeTruthy();
    expect(screen.queryByText('Invalid Date')).toBeNull();
  });
});

// ── #12: HomeDashboard subtitle pluralization (customer portfolio) ──────────
import { HomeDashboard } from '../src/pages/HomeDashboard';

describe('UX audit #12 — dashboard subtitle pluralization', () => {
  afterEach(cleanup);
  it('singular counts render as "1 customer" with no global use-case KPIs', async () => {
    render(<HomeDashboard onNavigate={() => undefined} />);
    expect(await screen.findByText('Customer portfolio — 1 customer')).toBeTruthy();
    // gcm-p5: global use-case KPIs / assessment quick-actions are retired.
    for (const gone of ['Use Cases', 'Avg Score', 'New Assessment', 'My Assessments',
      'Scoring Dashboard', 'Impact Matrix', 'Predictions', 'Business Impact']) {
      expect(screen.queryByText(gone)).toBeNull();
    }
    expect(screen.getByText('My Customers')).toBeTruthy();
    expect(screen.getByRole('heading', { name: 'Portfolio' })).toBeTruthy();
  });
});

// ── #15: UI version from package.json ───────────────────────────────────────
import { APP_VERSION } from '../src/lib/version';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

describe('UX audit #15 — UI version single source of truth', () => {
  it('APP_VERSION matches package.json (single source of truth)', () => {
    const pkg = JSON.parse(readFileSync(resolve(__dirname, '../package.json'), 'utf8'));
    // The invariant is PARITY, not a literal — pinning a literal here would
    // break every future release bump (the exact drift class audit #15 kills).
    expect(APP_VERSION).toBe(pkg.version);
  });

  it('Sidebar + Settings no longer hardcode the version literal', () => {
    const sidebar = readFileSync(resolve(__dirname, '../src/components/Sidebar.tsx'), 'utf8');
    const settings = readFileSync(resolve(__dirname, '../src/pages/Settings.tsx'), 'utf8');
    expect(sidebar).toContain('APP_VERSION');
    expect(sidebar).not.toContain('v0.1.4');
    expect(settings).toContain('APP_VERSION');
    // No hand-typed version literal may remain in Settings (the value comes
    // from the import — whatever the current release is).
    expect(settings.match(/\d+\.\d+\.\d+/g) ?? []).toHaveLength(0);
  });
});
