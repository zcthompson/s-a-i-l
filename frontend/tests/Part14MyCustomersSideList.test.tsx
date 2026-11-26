/**
 * Part 14 B1/B2 — CustomerDashboard "My Customers" side list on the H2 stack:
 * A–Z default (client-side over the full list; payload stays newest-first),
 * no nav params when unfiltered, sort serializes, pager slices the filtered
 * list, alias search. Synthetic names only.
 */
import { describe, it, expect, vi, afterEach, beforeEach, beforeAll } from 'vitest';
import { render, screen, cleanup, fireEvent } from '@testing-library/react';
import { MemoryRouter, useLocation } from 'react-router-dom';

const { apiStub, data } = vi.hoisted(() => {
  const data: { list: any[] } = { list: [] };
  const methods: Record<string, (...a: any[]) => Promise<unknown>> = {
    listCustomers: () => Promise.resolve(data.list),
    listVerticals: () => Promise.resolve({ verticals: [], departments_by_vertical: {} }),
  };
  const stub: any = new Proxy({}, {
    get: (_t, p) => (typeof p === 'string' && methods[p] ? methods[p] : () => Promise.resolve([])),
  });
  return { apiStub: stub, data };
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

import { CustomerDashboard } from '../src/pages/CustomerDashboard';

beforeAll(() => {
  if (typeof Element !== 'undefined' && !Element.prototype.scrollTo) {
    Element.prototype.scrollTo = function () { return undefined; };
  }
});

// 25 customers, payload newest-first: ids 25..1. Names are NOT in A–Z order
// in the payload (the newest row is "Zephyr Holdings").
const N = 25;
function seed() {
  data.list = Array.from({ length: N }, (_, i) => {
    const id = N - i;
    return {
      id, name: id === N ? 'Zephyr Holdings' : id === 1 ? 'Aardvark Labs' : `Account ${String(id).padStart(2, '0')}`,
      description: null, vertical: id % 2 ? 'Energy' : 'Healthcare', branch: null, primary_rep: null, manager_name: null,
      sales_area: null, primary_subsidiary: null, created_at: '', updated_at: '', departments: [], use_case_count: 0,
      aliases: id === 7 ? ['Quillon Group'] : [],
    };
  });
}

function Probe() {
  const loc = useLocation();
  return <span data-testid="url">{loc.search}</span>;
}
const mountAt = (entry = '/?view=customers') => render(
  <MemoryRouter initialEntries={[entry]}>
    <CustomerDashboard onNavigate={() => undefined} />
    <Probe />
  </MemoryRouter>,
);
const rowNames = () => screen.getAllByRole('button', { name: /^Select customer / })
  .map(b => (b.getAttribute('aria-label') ?? '').replace('Select customer ', ''));
const urlParams = () => new URLSearchParams(screen.getByTestId('url').textContent ?? '');
const ready = () => screen.findByLabelText('Search customers');
const azSorted = () => data.list.map(c => c.name).sort((a: string, b: string) => a.toLowerCase().localeCompare(b.toLowerCase()));

beforeEach(seed);
afterEach(cleanup);

describe('Part 14 My Customers side list', () => {
  it('defaults to A–Z over the complete list, with no nav params in the URL', async () => {
    mountAt();
    await ready();
    expect(screen.getByRole('heading', { name: 'My Customers' })).toBeTruthy();
    expect(rowNames()).toEqual(azSorted().slice(0, 20));
    expect(rowNames()[0]).toBe('Aardvark Labs'); // the OLDEST payload row sorts first
    expect((screen.getByLabelText('Sort by') as HTMLSelectElement).value).toBe('name');
    const url = urlParams();
    expect(url.get('sort')).toBeNull();
    expect(url.get('dir')).toBeNull();
    expect(url.get('view')).toBe('customers');
    expect(screen.getByTestId('portfolio-match-count').textContent).toBe('25 of 25 accounts match');
    expect(screen.queryByLabelText('Reset filters')).toBeNull();
  });

  it('selecting a sort serializes it; newest = payload order (never inverted)', async () => {
    mountAt();
    await ready();
    fireEvent.change(screen.getByLabelText('Sort by'), { target: { value: 'newest' } });
    expect(urlParams().get('sort')).toBe('newest');
    expect(rowNames()).toEqual(data.list.slice(0, 20).map(c => c.name));
    fireEvent.change(screen.getByLabelText('Sort by'), { target: { value: 'name' } });
    expect(urlParams().get('sort')).toBeNull();
    fireEvent.click(screen.getByLabelText('Sort direction: ascending'));
    expect(urlParams().get('dir')).toBe('desc');
    expect(rowNames()[0]).toBe('Zephyr Holdings');
  });

  it('restores a deep-linked sort from the URL', async () => {
    mountAt('/?view=customers&sort=newest');
    await ready();
    expect(rowNames()[0]).toBe('Zephyr Holdings');
  });

  it('the pager paginates the filtered + sorted list', async () => {
    mountAt();
    await ready();
    expect(screen.getByText('Showing 1–20 of 25')).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: /next/i }));
    expect(rowNames()).toEqual(azSorted().slice(20));
    expect(urlParams().get('page')).toBe('2');
    fireEvent.change(screen.getByLabelText('Filter by vertical'), { target: { value: 'Energy' } });
    const energy = data.list.filter(c => c.vertical === 'Energy').map(c => c.name)
      .sort((a: string, b: string) => a.toLowerCase().localeCompare(b.toLowerCase()));
    expect(urlParams().get('page')).toBeNull(); // filter change returns to page 1
    expect(rowNames()).toEqual(energy);
    expect(screen.getByTestId('portfolio-match-count').textContent).toBe(`${energy.length} of 25 accounts match`);
  });

  it('search matches an alias', async () => {
    mountAt();
    await ready();
    fireEvent.change(screen.getByLabelText('Search customers'), { target: { value: 'quillon' } });
    expect(rowNames()).toEqual(['Account 07']);
    expect(urlParams().get('q')).toBe('quillon');
  });
});
