/**
 * HomeDashboard portfolio table: search / filter / sort / count / reset /
 * URL state, My/All toggle interplay, full-scope KPI cards. Synthetic names only.
 */
import { describe, it, expect, vi, afterEach, beforeEach, beforeAll } from 'vitest';
import { render, screen, cleanup, fireEvent, within, waitFor, act } from '@testing-library/react';
import { MemoryRouter, useLocation, useNavigate } from 'react-router-dom';

const { apiStub, data, impactFn } = vi.hoisted(() => {
  const impactFn = vi.fn();
  const data: { list: any[]; impact: any } = { list: [], impact: null };
  const methods: Record<string, (...a: any[]) => Promise<unknown>> = {
    getCustomersStats: () => Promise.resolve({
      total_customers: data.impact?.customers.length ?? 0, total_use_cases: 0, total_scored: 0, average_score: 0,
      total_savings: 0, total_revenue: 0, total_impact: 0,
      customers: (data.impact?.customers ?? []).map((c: any) => ({ customer_id: c.customer_id, customer_name: c.customer_name, use_case_count: 0, user_count: 2 })),
    }),
    getPortfolioAccountImpact: (...a) => impactFn(...a),
    listCustomers: () => Promise.resolve(data.list),
    listVerticals: () => Promise.resolve({ verticals: ['Energy', 'Healthcare'], departments_by_vertical: {} }),
    aggregateStats: () => Promise.resolve({ total_use_cases: 0, average_score: 0, by_department: {}, by_status: {}, impact_summary: { total_impact: 0, total_savings: 0, total_revenue: 0 }, top_use_cases: [] }),
  };
  const stub: any = new Proxy({}, {
    get: (_t, p) => (typeof p === 'string' && methods[p] ? methods[p] : () => Promise.resolve([])),
  });
  return { apiStub: stub, data, impactFn };
});
vi.mock('../src/lib/api', () => ({
  api: apiStub,
  getAuthToken: () => 'tok',
  clearAuth: () => undefined,
  getAuthUsername: () => 'tester',
  getAuthIsAdmin: () => false,
  getAuthSalesRole: () => null,
}));
vi.mock('../src/lib/websocket', () => ({ ws: { connect: vi.fn(), disconnect: vi.fn(), subscribe: vi.fn() } }));
vi.mock('../src/components/AppHealthCard', () => ({ AppHealthCard: () => null }));
vi.mock('../src/components/AdminConsole', () => ({ AdminConsole: () => null }));

import { HomeDashboard } from '../src/pages/HomeDashboard';
import { Home, LoadingFallback } from '../src/pages/Home';
import { Sidebar } from '../src/components/Sidebar';

beforeAll(() => {
  if (typeof Element !== 'undefined' && !Element.prototype.scrollTo) {
    Element.prototype.scrollTo = function () { return undefined; };
  }
});

const N = 24; // ids 1..24 are in the /customers/ list; id 25 is impact-only
function seed() {
  data.list = Array.from({ length: N }, (_, i) => {
    const n = i + 1;
    return {
      id: n, name: n === N ? 'Zephyr Holdings' : `Account ${String(n).padStart(2, '0')}`, description: null,
      vertical: n % 2 ? 'Energy' : 'Healthcare', branch: n % 3 === 0 ? 'North' : 'South',
      primary_rep: n % 5 === 0 ? null : (n % 2 ? 'Rep Alpha' : 'Rep Bravo'), manager_name: null,
      created_at: '', updated_at: '', departments: [],
    };
  });
  data.impact = {
    customer_count: 25, as_of: 'x', calculation_version: 'account-impact/2', coverage: 'quantified', scope: 'All authorized customers',
    total_impact: { value: 7777, perspective: 'customer_benefit', realization_basis: 'estimated', currency: null },
    rollup: { quantified: 25, partial: 0, not_quantified: 0 },
    customers: [
      ...data.list.map(c => ({ customer_id: c.id, customer_name: c.name, coverage: 'quantified', total_impact: c.id * 10 })),
      // Join miss: own impact-row metadata is the fallback.
      { customer_id: 25, customer_name: 'Fallback Co', coverage: 'quantified', total_impact: 5, vertical: 'Retail', branch: 'West', primary_rep: 'Rep Delta' },
    ],
  };
  impactFn.mockReset();
  impactFn.mockImplementation(() => Promise.resolve(data.impact));
}

function Probe() {
  const loc = useLocation();
  return <span data-testid="url">{loc.search}</span>;
}
const mountAt = (entry = '/?view=dashboard', isAdmin = false) => render(
  <MemoryRouter initialEntries={[entry]}>
    <HomeDashboard onNavigate={() => undefined} isAdmin={isAdmin} />
    <Probe />
  </MemoryRouter>,
);
const search = () => screen.getByLabelText('Search customers') as HTMLInputElement;
const ready = () => screen.findByLabelText('Search customers');
const bodyNames = () => within(screen.getByRole('table')).getAllByRole('row').slice(1).map(r => r.querySelector('td')?.textContent);
const urlParams = () => new URLSearchParams(screen.getByTestId('url').textContent ?? '');

beforeEach(seed);
afterEach(cleanup);

describe('HomeDashboard navigation', () => {
  it('keeps quick actions ahead of the portfolio and opens the selected destination', async () => {
    const navigate = vi.fn();
    render(<MemoryRouter><HomeDashboard username="tester" onNavigate={navigate} /></MemoryRouter>);
    const quickActions = screen.getByRole('heading', { name: 'Quick Actions' });
    const portfolio = screen.getByRole('heading', { name: 'Portfolio' });
    expect(quickActions.compareDocumentPosition(portfolio) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: 'Go to My Customers' }));
    fireEvent.click(screen.getByRole('button', { name: 'Go to Export PDF' }));
    expect(navigate).toHaveBeenNthCalledWith(1, 'customers');
    expect(navigate).toHaveBeenNthCalledWith(2, 'export-pdf');
    await ready();
  });

  it('honors motion preference changes for quick actions, navigation and loading feedback', async () => {
    let reduced = false;
    const listeners = new Set<() => void>();
    vi.stubGlobal('matchMedia', vi.fn(() => ({
      get matches() { return reduced; },
      addEventListener: (_type: string, listener: () => void) => listeners.add(listener),
      removeEventListener: (_type: string, listener: () => void) => listeners.delete(listener),
    })));
    try {
      render(<MemoryRouter><HomeDashboard onNavigate={() => undefined} /><Sidebar activeView="dashboard" onNavigate={() => undefined} username="tester" onLogout={() => undefined} isCollapsed={false} onToggle={() => undefined} /><LoadingFallback /></MemoryRouter>);
      await ready();
      const action = screen.getByLabelText('Go to My Customers');
      const chevron = screen.getByLabelText('Collapse Customers');
      const spinner = screen.getByText('Loading…').nextElementSibling as HTMLElement;
      fireEvent.mouseEnter(action);
      expect(action.style.transform).toBe('translateY(-1px)');
      expect(action.style.transition).toBe('all 0.2s');
      expect(chevron.style.transition).toBe('transform 0.2s');
      expect(spinner.style.animation).toContain('spin');
      act(() => { reduced = true; listeners.forEach(listener => listener()); });
      expect(action.style.transform).toBe('none');
      expect(action.style.transition).toBe('none');
      expect(chevron.style.transition).toBe('none');
      expect(spinner.style.animation).toBe('none');
      fireEvent.mouseEnter(action);
      expect(action.style.transform).toBe('none');
      fireEvent.click(chevron);
      expect(screen.getByLabelText('Expand Customers').style.transform).toBe('rotate(0deg)');
      act(() => { reduced = false; listeners.forEach(listener => listener()); });
      fireEvent.mouseEnter(action);
      expect(action.style.transform).toBe('translateY(-1px)');
      expect(spinner.style.animation).toContain('spin');
      cleanup();
      reduced = true;
      render(<MemoryRouter><HomeDashboard onNavigate={() => undefined} /><LoadingFallback /></MemoryRouter>);
      await ready();
      expect(screen.getByLabelText('Go to My Customers').style.transition).toBe('none');
      expect((screen.getByText('Loading…').nextElementSibling as HTMLElement).style.animation).toBe('none');
    } finally {
      cleanup();
      vi.unstubAllGlobals();
    }
  });

  it('shows Owner / Vertical / Branch columns from the /customers/ join; unknown renders "—"', async () => {
    mountAt('/?view=dashboard&q=account 01');
    await ready();
    const row = within(screen.getByRole('table')).getAllByRole('row')[1];
    const cells = within(row).getAllByRole('cell').map(c => c.textContent);
    expect(cells.slice(0, 4)).toEqual(['Account 01', 'Rep Alpha', 'Energy', 'South']);
    cleanup();
    // Impact-metadata fallback for the join miss; rows with nothing show "—".
    mountAt('/?view=dashboard&q=fallback');
    await ready();
    const fb = within(within(screen.getByRole('table')).getAllByRole('row')[1]).getAllByRole('cell').map(c => c.textContent);
    expect(fb.slice(0, 4)).toEqual(['Fallback Co', 'Rep Delta', 'Retail', 'West']);
  });

  it('search finds an account beyond page 1 and counts against the authorized total', async () => {
    mountAt();
    await ready();
    expect(screen.getByText('Showing 1–20 of 25')).toBeTruthy();
    expect(bodyNames()).not.toContain('Zephyr Holdings');
    fireEvent.change(search(), { target: { value: 'zephyr' } });
    expect(bodyNames()).toEqual(['Zephyr Holdings']);
    expect(screen.getByTestId('portfolio-match-count').textContent).toBe('1 of 25 accounts match');
  });

  it('KPI cards stay full-scope while the table is filtered', async () => {
    mountAt();
    await ready();
    expect(screen.getByText('Customer portfolio — 25 customers')).toBeTruthy();
    fireEvent.change(search(), { target: { value: 'zephyr' } });
    expect(screen.getByText('Customer portfolio — 25 customers')).toBeTruthy();
    expect(screen.getAllByText('7,777 (currency not recorded)').length).toBeGreaterThan(0);
  });

  it('shows source coverage and unrecorded currency without treating mixed evidence as complete', async () => {
    data.impact = { ...data.impact, as_of: '2026-11-01T10:00:00Z', rollup: { quantified: 1, partial: 2, not_quantified: 22 } };
    mountAt();
    await ready();
    expect(screen.getByText('7,777 (currency not recorded)')).toBeTruthy();
    expect(screen.getByText(/1 of 25 accounts quantified · 2 partial · 22 not quantified/)).toBeTruthy();
    fireEvent.change(search(), { target: { value: 'zephyr' } });
    expect(screen.getByText(/1 of 25 accounts quantified · 2 partial · 22 not quantified/)).toBeTruthy();
  });

  it('keeps focus in the mobile drawer and restores it on close', async () => {
    const rects = vi.spyOn(HTMLElement.prototype, 'getClientRects').mockImplementation(() => [{ } as DOMRect] as unknown as DOMRectList);
    try {
      render(<MemoryRouter><Home /></MemoryRouter>);
      const toggle = document.getElementById('mobile-nav-toggle') as HTMLButtonElement;
      fireEvent.click(toggle);
      const close = document.getElementById('mobile-nav-close') as HTMLButtonElement;
      await waitFor(() => expect(document.activeElement).toBe(close));
      const drawer = document.getElementById('navigation-shell')!;
      expect(drawer.getAttribute('aria-modal')).toBe('true');
      fireEvent.keyDown(close, { key: 'Tab', shiftKey: true });
      expect(drawer.contains(document.activeElement)).toBe(true);
      fireEvent.keyDown(document.activeElement!, { key: 'Tab' });
      expect(document.activeElement).toBe(close);
      fireEvent.keyDown(close, { key: 'Escape' });
      await waitFor(() => expect(document.activeElement).toBe(toggle));
      expect(drawer.getAttribute('data-open')).toBe('false');
    } finally { rects.mockRestore(); }
  });

  it('lets Tab escape the desktop sidebar when the drawer is closed (no focus trap)', () => {
    const rects = vi.spyOn(HTMLElement.prototype, 'getClientRects').mockImplementation(() => [{} as DOMRect] as unknown as DOMRectList);
    try {
      render(<MemoryRouter><Home /></MemoryRouter>);
      const drawer = document.getElementById('navigation-shell')!;
      expect(drawer.getAttribute('aria-modal')).toBeNull();
      expect(drawer.getAttribute('data-open')).toBe('false');
      const close = document.getElementById('mobile-nav-close') as HTMLElement;
      const sidebarControls = Array.from(drawer.querySelectorAll<HTMLElement>('button:not([disabled]), a[href], input:not([disabled]), select:not([disabled]), [tabindex="0"]')).filter(el => el !== close && el.getClientRects().length > 0);
      expect(sidebarControls.length).toBeGreaterThan(1);
      const last = sidebarControls[sidebarControls.length - 1];
      last.focus();
      const event = new KeyboardEvent('keydown', { key: 'Tab', bubbles: true, cancelable: true });
      last.dispatchEvent(event);
      // The shell must not wrap focus on desktop: no preventDefault, no jump.
      expect(event.defaultPrevented).toBe(false);
      expect(document.activeElement).toBe(last);
      const esc = new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true });
      last.dispatchEvent(esc);
      expect(esc.defaultPrevented).toBe(false);
    } finally { rects.mockRestore(); }
  });

  it('vertical filter + count + URL; reset restores defaults and keeps page size', async () => {
    mountAt('/?view=dashboard&ps=10');
    await ready();
    fireEvent.change(screen.getByLabelText('Filter by vertical'), { target: { value: 'Healthcare' } });
    const hc = data.list.filter(c => c.vertical === 'Healthcare').length;
    expect(screen.getByTestId('portfolio-match-count').textContent).toBe(`${hc} of 25 accounts match`);
    expect(urlParams().get('vertical')).toBe('Healthcare');
    expect(urlParams().get('view')).toBe('dashboard');
    fireEvent.click(screen.getByLabelText('Reset filters'));
    expect(screen.queryByLabelText('Reset filters')).toBeNull();
    expect(urlParams().has('vertical')).toBe(false);
    expect(urlParams().get('ps')).toBe('10');
    expect(screen.getByText('Showing 1–10 of 25')).toBeTruthy();
  });

  it('keeps every sortable header keyboard focusable with its accessible name and sort state', async () => {
    mountAt();
    await ready();
    for (const name of ['Customer', 'Owner', 'Vertical', 'Branch', 'Account Impact']) {
      const button = screen.getByRole('button', { name: `Sort by ${name}` });
      expect(button.tabIndex).toBe(0);
      button.focus();
      expect(document.activeElement).toBe(button);
      fireEvent.click(button);
      expect(button.closest('th')?.getAttribute('aria-sort')).toBe('ascending');
    }
  });

  it('scrolls the focused sort header and its outline into the table viewport', async () => {
    mountAt();
    await ready();
    const button = screen.getByRole('button', { name: 'Sort by Customer' });
    const scroller = button.closest('table')!.parentElement!;
    const viewport = vi.spyOn(scroller, 'getBoundingClientRect').mockReturnValue({ left: 0, right: 200 } as DOMRect);
    const target = vi.spyOn(button, 'getBoundingClientRect').mockReturnValue({ left: 180, right: 260 } as DOMRect);
    button.focus();
    expect(scroller.scrollLeft).toBe(65);
    button.blur();
    scroller.scrollLeft = 100;
    target.mockReturnValue({ left: -20, right: 60 } as DOMRect);
    button.focus();
    expect(scroller.scrollLeft).toBe(75);
    viewport.mockRestore();
    target.mockRestore();
  });

  it('column headers sort with aria-sort and stay in sync with the sort select', async () => {
    mountAt();
    await ready();
    const header = (name: string) => screen.getByRole('columnheader', { name: new RegExp(name) });
    expect(header('Customer').getAttribute('aria-sort')).toBe('none');
    fireEvent.click(screen.getByLabelText('Sort by Customer'));
    expect(header('Customer').getAttribute('aria-sort')).toBe('ascending');
    expect((screen.getByLabelText('Sort by') as HTMLSelectElement).value).toBe('name');
    expect(bodyNames()[0]).toBe('Account 01');
    fireEvent.click(screen.getByLabelText('Sort by Customer'));
    expect(header('Customer').getAttribute('aria-sort')).toBe('descending');
    expect(bodyNames()[0]).toBe('Zephyr Holdings');
    fireEvent.click(screen.getByLabelText('Sort by Account Impact'));
    expect(header('Customer').getAttribute('aria-sort')).toBe('none');
    expect(header('Account Impact').getAttribute('aria-sort')).toBe('ascending');
    expect(bodyNames()[0]).toBe('Fallback Co'); // impact 5 is the smallest
  });

  it('the sort select does not offer "Added" on the dashboard', async () => {
    mountAt();
    await ready();
    const opts = within(screen.getByLabelText('Sort by')).getAllByRole('option').map(o => o.textContent);
    expect(opts).toContain('Pipeline');
    expect(opts).not.toContain('Added');
  });

  it('deep link restores the exact filtered/sorted page', async () => {
    mountAt('/?view=dashboard&q=account&vertical=Energy&sort=name&dir=asc&page=2&ps=10');
    await ready();
    const energyAccounts = data.list.filter(c => c.vertical === 'Energy' && c.name.startsWith('Account')).length;
    expect(search().value).toBe('account');
    expect((screen.getByLabelText('Filter by vertical') as HTMLSelectElement).value).toBe('Energy');
    expect(screen.getByText(`Showing 11–${energyAccounts} of ${energyAccounts}`)).toBeTruthy();
    expect(bodyNames()[0]).toBe('Account 21');
  });

  it('does not offer a scope switch when the role has only one portfolio', async () => {
    mountAt();
    await ready();
    expect(screen.queryByLabelText('Toggle between My View and All View')).toBeNull();
  });

  it('shows unavailable financial values when the portfolio request fails', async () => {
    impactFn.mockRejectedValue(new Error('offline'));
    mountAt();
    expect((await screen.findByRole('alert')).textContent).toContain('Portfolio impact is unavailable');
    expect(screen.getAllByText('Unavailable').length).toBeGreaterThan(0);
  });

  it('scope changes reset portfolio filters and keep the route', async () => {
    mountAt('/?view=dashboard&q=account&sort=name&ps=10&page=2', true);
    await ready();
    expect(urlParams().get('page')).toBe('2');
    fireEvent.click(screen.getByLabelText('Toggle between My View and All View'));
    await ready();
    expect(impactFn).toHaveBeenLastCalledWith(true);
    expect(screen.getByLabelText('Toggle between My View and All View').getAttribute('aria-pressed')).toBe('true');
    expect(screen.getByText('Current portfolio scope: My customers')).toBeTruthy();
    expect(search().value).toBe('');
    const p = urlParams();
    expect(p.has('page')).toBe(false);
    expect(p.get('view')).toBe('dashboard');
    expect(p.has('q')).toBe(false);
    expect(p.get('portfolio_scope')).toBe('my');
  });

  it('restores a scoped admin link and falls back safely on an invalid scope', async () => {
    mountAt('/?view=dashboard&portfolio_scope=my', true);
    await ready();
    expect(impactFn).toHaveBeenLastCalledWith(true);
    expect(screen.getByText(/My View/)).toBeTruthy();
    cleanup();
    mountAt('/?view=dashboard&portfolio_scope=obsolete', true);
    await ready();
    expect(impactFn).toHaveBeenLastCalledWith(true);
    expect(screen.getByText(/requested portfolio scope is unavailable/)).toBeTruthy();
  });

  it('ignores a scoped link for a non-admin and explains the fallback', async () => {
    mountAt('/?view=dashboard&portfolio_scope=my');
    await ready();
    expect(impactFn).toHaveBeenLastCalledWith(false);
    expect(screen.getByText(/your authorized portfolio/)).toBeTruthy();
    expect(screen.queryByLabelText('Toggle between My View and All View')).toBeNull();
  });

  it('keeps the focused scope control mounted and hides old data until the new scope resolves', async () => {
    let finish!: (value: any) => void;
    impactFn.mockImplementation((my: boolean) => my ? new Promise(resolve => { finish = resolve; }) : Promise.resolve(data.impact));
    mountAt('/?view=dashboard', true);
    await ready();
    const toggle = screen.getByLabelText('Toggle between My View and All View');
    toggle.focus();
    fireEvent.click(toggle);
    await waitFor(() => expect(impactFn).toHaveBeenLastCalledWith(true));
    expect(screen.getByLabelText('Toggle between My View and All View')).toBe(toggle);
    expect(document.activeElement).toBe(toggle);
    expect(screen.getByText('Loading portfolio…')).toBeTruthy();
    expect(screen.queryByText('Customer portfolio — 25 customers')).toBeNull();
    expect(screen.queryByRole('table')).toBeNull();
    await act(async () => finish({ ...data.impact, customer_count: 1, customers: [data.impact.customers[0]] }));
    expect(await screen.findByText('Customer portfolio — 1 customer')).toBeTruthy();
    expect(document.activeElement).toBe(toggle);
  });

  it('retains focus when scoped portfolio data fails', async () => {
    impactFn.mockImplementation((my: boolean) => my ? Promise.reject(new Error('offline')) : Promise.resolve(data.impact));
    mountAt('/?view=dashboard', true);
    await ready();
    const toggle = screen.getByLabelText('Toggle between My View and All View');
    toggle.focus();
    fireEvent.click(toggle);
    expect((await screen.findByRole('alert')).textContent).toContain('Portfolio impact is unavailable');
    expect(document.activeElement).toBe(toggle);
    expect(toggle.getAttribute('aria-pressed')).toBe('true');
  });

  it('discards a late response after rapid scope changes without moving focus', async () => {
    let finishMy!: (value: any) => void;
    impactFn.mockImplementation((my: boolean) => my ? new Promise(resolve => { finishMy = resolve; }) : Promise.resolve(data.impact));
    mountAt('/?view=dashboard', true);
    await ready();
    const toggle = screen.getByLabelText('Toggle between My View and All View');
    toggle.focus();
    fireEvent.click(toggle);
    await waitFor(() => expect(impactFn).toHaveBeenLastCalledWith(true));
    fireEvent.click(toggle);
    await waitFor(() => expect(impactFn).toHaveBeenLastCalledWith(false));
    expect(await screen.findByText('Customer portfolio — 25 customers')).toBeTruthy();
    await act(async () => finishMy({ ...data.impact, customer_count: 1, customers: [data.impact.customers[0]] }));
    expect(screen.getByText('Customer portfolio — 25 customers')).toBeTruthy();
    expect(document.activeElement).toBe(toggle);
  });

  it('does not steal focus when history changes scope from another control', async () => {
    function History() { const navigate = useNavigate(); return <button onClick={() => navigate(-1)}>Back externally</button>; }
    render(<MemoryRouter initialEntries={['/?view=dashboard&portfolio_scope=all', '/?view=dashboard&portfolio_scope=my']}><HomeDashboard onNavigate={() => undefined} isAdmin /><History /></MemoryRouter>);
    await ready();
    const back = screen.getByText('Back externally');
    back.focus();
    fireEvent.click(back);
    await waitFor(() => expect(impactFn).toHaveBeenLastCalledWith(false));
    await ready();
    expect(document.activeElement).toBe(back);
  });

  it('scope changes participate in back and forward history', async () => {
    function History() { const navigate = useNavigate(); return <><button onClick={() => navigate(-1)}>Back</button><button onClick={() => navigate(1)}>Forward</button></>; }
    render(<MemoryRouter initialEntries={['/?view=dashboard&portfolio_scope=all']}><HomeDashboard onNavigate={() => undefined} isAdmin /><Probe /><History /></MemoryRouter>);
    await ready();
    const toggle = screen.getByLabelText('Toggle between My View and All View');
    toggle.focus();
    fireEvent.click(toggle);
    await ready();
    expect(urlParams().get('portfolio_scope')).toBe('my');
    fireEvent.click(screen.getByText('Back'));
    await ready();
    expect(urlParams().get('portfolio_scope')).toBe('all');
    expect(document.activeElement).toBe(toggle);
    fireEvent.click(screen.getByText('Forward'));
    await ready();
    expect(urlParams().get('portfolio_scope')).toBe('my');
    expect(document.activeElement).toBe(toggle);
  });

  it('no-match state is distinct from the no-accounts state and offers Reset', async () => {
    mountAt();
    await ready();
    fireEvent.change(search(), { target: { value: 'nothing-like-this' } });
    expect(screen.getByTestId('no-matches').textContent).toContain('No matches');
    expect(screen.queryByRole('table')).toBeNull();
    fireEvent.click(within(screen.getByTestId('no-matches')).getByLabelText('Reset filters'));
    expect(screen.getByRole('table')).toBeTruthy();
    cleanup();

    data.impact = { ...data.impact, customer_count: 0, customers: [] };
    mountAt();
    await screen.findByText('Customer portfolio — 0 customers');
    expect(screen.queryByRole('table')).toBeNull();
    expect(screen.queryByLabelText('Search customers')).toBeNull();
    expect(screen.queryByTestId('no-matches')).toBeNull();
  });

  it('falls back visibly when a legacy added-date sort is no longer available', async () => {
    mountAt('/?view=my-dashboard&sort=granted&dir=desc');
    await ready();
    expect(screen.getByText(/previous added-date sort is unavailable/)).toBeTruthy();
    expect(urlParams().get('sort')).toBe('name');
  });

  it('does not carry customer-list filters into a newly opened dashboard', async () => {
    render(<MemoryRouter initialEntries={['/?view=customers&q=private&vertical=Energy']}><Home /><Probe /></MemoryRouter>);
    const nav = screen.getByRole('navigation', { name: 'Primary' });
    fireEvent.click(within(nav).getByRole('button', { name: 'Dashboard' }));
    await ready();
    expect(search().value).toBe('');
    expect(urlParams().has('vertical')).toBe(false);
  });

  it('through Home: legacy dashboard links keep filters and select the sole sidebar entry', async () => {
    render(<MemoryRouter initialEntries={['/?view=my-dashboard&q=zephyr']}><Home /><Probe /></MemoryRouter>);
    await ready();
    expect(search().value).toBe('zephyr');
    expect(bodyNames()).toEqual(['Zephyr Holdings']);
    expect(document.querySelector('main > header h2')?.textContent).toBe('Dashboard');
    const nav = screen.getByRole('navigation', { name: 'Primary' });
    expect(within(nav).getByRole('button', { name: 'Dashboard' })).toBeTruthy();
    expect(within(nav).queryByRole('button', { name: 'My Dashboard' })).toBeNull();
    expect(urlParams().get('view')).toBe('dashboard');
  });

  it('through Home: ?view=dashboard deep link keeps its filters and the view', async () => {
    render(
      <MemoryRouter initialEntries={['/?view=dashboard&q=zephyr&sort=name&dir=desc']}>
        <Home />
        <Probe />
      </MemoryRouter>,
    );
    await ready();
    expect(search().value).toBe('zephyr');
    expect(bodyNames()).toEqual(['Zephyr Holdings']);
    expect(document.querySelector('main > header h2')?.textContent).toBe('Dashboard');
    fireEvent.change(search(), { target: { value: 'account 02' } });
    const p = urlParams();
    expect([p.get('view'), p.get('q'), p.get('sort'), p.get('dir')]).toEqual(['dashboard', 'account 02', 'name', 'desc']);
    expect(document.querySelector('main > header h2')?.textContent).toBe('Dashboard');
  });
});
