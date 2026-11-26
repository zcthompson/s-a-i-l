// Regression tests for the WP22 two-way view<->URL sync in Home.tsx.
// The key scenario is browser Back/Forward: the view must FOLLOW the URL.
// (The original implementation re-ran its view->URL effect on searchParams
// changes, so a Back press re-ran it in the same commit with the
// PRE-UPDATE view and pushed the stale view back into the URL — the
// URL->view effect then flipped the view back, oscillating view and URL.
// Caught in review (Codex P1, 2026-08-30); these tests pin the behavior.)
import { describe, it, expect, vi, afterEach, beforeAll } from 'vitest';
import { render, screen, cleanup, fireEvent, waitFor } from '@testing-library/react';
import { MemoryRouter, useNavigate, useLocation } from 'react-router-dom';
import { Home } from '../src/pages/Home';

// jsdom implements window.scrollTo only — Element.scrollTo (used by the
// view-change scroll reset in Home.tsx) is not a function there. Stub a
// no-op so the component is exercisable; real browsers implement it.
beforeAll(() => {
  if (typeof Element !== 'undefined' && !Element.prototype.scrollTo) {
    Element.prototype.scrollTo = function () { return undefined; };
  }
});

// Home pulls api/ws at module scope and in mount effects; stub both. The
// api stub resolves every method with [] EXCEPT the stats endpoints, which
// HomeDashboard (static import, dashboard view) renders with a full
// StatsResponse shape — the header title and ?view= URL are the assertions,
// but the rendered content must not crash mid-test.
const { apiStub } = vi.hoisted(() => {
  const statsShape = {
    total_use_cases: 0,
    average_score: 0,
    by_department: {},
    by_status: {},
    impact_summary: { total_impact: 0, total_savings: 0, total_revenue: 0 },
    top_use_cases: [],
  };
  const methods: Record<string, () => Promise<unknown>> = {
    aggregateStats: () => Promise.resolve(statsShape),
    getCustomersStats: () => Promise.resolve(null),
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
  getAuthUsername: () => 'tester',
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

function BackButton() {
  const navigate = useNavigate();
  return <button type="button" onClick={() => navigate(-1)}>go-back</button>;
}

function UrlProbe() {
  const location = useLocation();
  return <span data-testid="url">{location.search}</span>;
}

describe('Home view<->URL sync', () => {
  it('browser Back follows the URL instead of the stale view being written back', () => {
    // History: /?view=dashboard  ->  /?view=customers (start on the last).
    render(
      <MemoryRouter initialEntries={['/?view=dashboard', '/?view=customers']}>
        <Home />
        <BackButton />
      </MemoryRouter>
    );

    // Deep link seeded the view state: header shows the customers label.
    expect(headerTitle()).toBe('My Customers');

    // Back pops to /?view=dashboard. The view must follow the URL.
    fireEvent.click(screen.getByRole('button', { name: 'go-back' }));
    expect(headerTitle()).toBe('Dashboard');
  });

  it('back through a legacy dashboard bookmark does not create a new history entry', async () => {
    function ForwardButton() { const navigate = useNavigate(); return <button onClick={() => navigate(1)}>go-forward</button>; }
    render(<MemoryRouter initialEntries={['/?view=my-dashboard&q=acme', '/?view=customers']}><Home /><BackButton /><ForwardButton /><UrlProbe /></MemoryRouter>);
    fireEvent.click(screen.getByText('go-back'));
    await waitFor(() => expect(headerTitle()).toBe('Dashboard'));
    const params = new URLSearchParams(screen.getByTestId('url').textContent ?? '');
    expect(params.get('q')).toBe('acme');
    fireEvent.click(screen.getByText('go-forward'));
    await waitFor(() => expect(headerTitle()).toBe('My Customers'));
  });

  it('preserves import source when navigating away and back', async () => {
    render(<MemoryRouter initialEntries={['/?view=gi-import&extra=1']}><Home /><BackButton /><UrlProbe /></MemoryRouter>);
    const select = await screen.findByTestId('intelligence-import-source-select', {}, { timeout: 5000 });
    fireEvent.change(select, { target: { value: 'vmware' } });
    expect(new URLSearchParams(screen.getByTestId('url').textContent ?? '').get('source')).toBe('vmware');
    fireEvent.click(screen.getByRole('button', { name: 'Dashboard' }));
    await waitFor(() => expect(headerTitle()).toBe('Dashboard'));
    expect(new URLSearchParams(screen.getByTestId('url').textContent ?? '').get('source')).toBe('vmware');
    fireEvent.click(screen.getByText('go-back'));
    await waitFor(() => expect(headerTitle()).toBe('Intelligence Import'));
    expect((await screen.findByTestId('intelligence-import-source-select') as HTMLSelectElement).value).toBe('vmware');
    expect(new URLSearchParams(screen.getByTestId('url').textContent ?? '').get('extra')).toBe('1');
  });

  it('opens Appearance from the sidebar even after viewing another Settings tab', async () => {
    render(<MemoryRouter initialEntries={['/?view=settings-appearance&settings_tab=notifications']}><Home /><UrlProbe /></MemoryRouter>);
    await screen.findByRole('button', { name: 'Show Notifications settings' }, { timeout: 5000 });
    expect(screen.getByRole('button', { name: 'Show Notifications settings' }).getAttribute('aria-pressed')).toBe('true');
    fireEvent.click(screen.getByRole('button', { name: 'Appearance', exact: true }));
    await waitFor(() => expect(screen.getByRole('button', { name: 'Show Appearance settings' }).getAttribute('aria-pressed')).toBe('true'));
    expect(new URLSearchParams(screen.getByTestId('url').textContent ?? '').get('settings_tab')).toBe('appearance');
    fireEvent.click(screen.getByRole('button', { name: 'Show Notifications settings' }));
    fireEvent.click(screen.getByRole('button', { name: 'Dashboard' }));
    await waitFor(() => expect(headerTitle()).toBe('Dashboard'));
    expect(new URLSearchParams(screen.getByTestId('url').textContent ?? '').has('settings_tab')).toBe(false);
    fireEvent.click(screen.getByRole('button', { name: 'Settings', exact: true }));
    await waitFor(() => expect(screen.getByRole('button', { name: 'Show Appearance settings' }).getAttribute('aria-pressed')).toBe('true'));
  });

  it('restores the prior Settings tab on browser Back after leaving', async () => {
    render(<MemoryRouter initialEntries={['/?view=settings-appearance&settings_tab=notifications&extra=1']}><Home /><BackButton /><UrlProbe /></MemoryRouter>);
    await screen.findByRole('button', { name: 'Show Notifications settings' }, { timeout: 5000 });
    fireEvent.click(screen.getByRole('button', { name: 'Dashboard' }));
    await waitFor(() => expect(headerTitle()).toBe('Dashboard'));
    fireEvent.click(screen.getByText('go-back'));
    await waitFor(() => expect(screen.getByRole('button', { name: 'Show Notifications settings' }).getAttribute('aria-pressed')).toBe('true'));
    expect(new URLSearchParams(screen.getByTestId('url').textContent ?? '').get('extra')).toBe('1');
  });

  it('sidebar navigation writes the active view into the URL (?view= param)', () => {
    render(
      <MemoryRouter initialEntries={['/']}>
        <Home />
        <UrlProbe />
      </MemoryRouter>
    );

    // Mount baseline: the view is established in the URL (replace).
    expect(screen.getByTestId('url').textContent).toBe('?view=dashboard');

    // Click the Customers section header: navigates to its first child and
    // pushes ?view=customers into the URL.
    fireEvent.click(screen.getByRole('button', { name: 'Customers' }));
    expect(headerTitle()).toBe('My Customers');
    expect(screen.getByTestId('url').textContent).toBe('?view=customers');
  });
});
