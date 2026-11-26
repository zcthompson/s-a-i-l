/**
 * Part 14 C2 + C3 — AdminConsole: block order Application Functions →
 * Portfolio → Users Management; the Portfolio summary shows the first 10
 * accounts with H2 controls (search over name + aliases, filter, sort, count
 * line, reset; LOCAL nav state — no URL sync, primary ruling on SR-1) and
 * click-through to the customer; the Users table is capped at the first 10
 * (matching) user accounts with client-side search. Synthetic names only.
 */
import { describe, it, expect, vi, afterEach, beforeEach } from 'vitest';
import { render, screen, cleanup, fireEvent, within } from '@testing-library/react';

const { apiMock, data } = vi.hoisted(() => {
  const data: { users: any[]; accounts: any[] } = { users: [], accounts: [] };
  return {
    data,
    apiMock: {
      getGlobalAdminStats: vi.fn(() => Promise.resolve({ total_users: 0, active_users: 0, pending_users: 0, admin_count: 0, total_customers: 0, total_use_cases: 0 })),
      getAllUsers: vi.fn(() => Promise.resolve(data.users)),
      listCustomers: vi.fn(() => Promise.resolve(data.accounts)),
      listVerticals: vi.fn(() => Promise.resolve({ verticals: [], departments_by_vertical: {} })),
    },
  };
});
vi.mock('../src/lib/api', () => ({ api: apiMock }));

import { AdminConsole } from '../src/components/AdminConsole';

function seed() {
  data.users = Array.from({ length: 14 }, (_, i) => {
    const n = i + 1;
    return {
      id: n, username: `user${String(n).padStart(2, '0')}`, email: n === 13 ? null : `u${n}@example.test`,
      display_name: null, department: n % 2 ? 'Finance' : 'Operations', role: n === 4 ? 'manager' : null,
      is_admin: n === 1 ? 1 : 0, approved: n >= 12 ? 0 : 1, is_active: 1,
    };
  });
  // 12 accounts (payload order = newest-first); the console shows the first 10.
  data.accounts = Array.from({ length: 12 }, (_, i) => {
    const n = i + 1;
    return {
      id: 100 + n, name: `Acct ${String(n).padStart(2, '0')}`, description: null,
      vertical: n % 2 ? 'Technology' : 'Financial Services', branch: n % 3 ? 'BR1' : 'BR2',
      sales_area: null, primary_subsidiary: null, primary_rep: n % 2 ? `rep${n}` : null,
      manager_name: null, created_at: `2026-01-${String(n).padStart(2, '0')}T00:00:00`,
      updated_at: `2026-01-${String(n).padStart(2, '0')}T00:00:00`, use_case_count: 0,
      departments: [], total_impact: 0,
      aliases: n === 2 ? ['Second Acct'] : [],
    };
  });
}
const tableRows = () => within(screen.getByRole('table')).getAllByRole('row').slice(1);
const rowUsers = () => tableRows().map(r => r.querySelector('td')?.textContent);
const search = () => screen.getByLabelText('Search users') as HTMLInputElement;
const count = () => screen.getByTestId('admin-users-match-count').textContent;
const portfolioBlock = () => screen.getByTestId('admin-console-portfolio');
const portfolioRows = () =>
  within(portfolioBlock()).queryAllByRole('button', { name: /^Open / })
    .map((r) => (r.getAttribute('aria-label') || '').replace(/^Open /, ''));

beforeEach(seed);
afterEach(cleanup);

describe('Part 14 AdminConsole Portfolio (C2)', () => {
  it('omits its duplicate portfolio and request inside the shared dashboard', async () => {
    apiMock.listCustomers.mockClear();
    render(<AdminConsole onNavigate={() => undefined} showPortfolio={false} />);
    expect(await screen.findByText('👥 Users Management')).toBeTruthy();
    expect(screen.queryByTestId('admin-console-portfolio')).toBeNull();
    expect(apiMock.listCustomers).not.toHaveBeenCalled();
  });

  it('blocks stay in order: Application Functions → Portfolio → Users Management', async () => {
    render(<AdminConsole onNavigate={() => undefined} />);
    await screen.findByTestId('admin-console-portfolio');
    const h2 = screen.getAllByRole('heading', { level: 2 }).map(h => h.textContent);
    expect(h2).toEqual(['⚙️ Application Functions', '📊 Portfolio', '👥 Users Management']);
  });

  it('shows the first 10 accounts by default with an honest count line', async () => {
    render(<AdminConsole onNavigate={() => undefined} />);
    await screen.findByTestId('admin-console-portfolio');
    // payload order (newest first) — the console default is NOT A–Z.
    expect(portfolioRows()).toEqual(data.accounts.slice(0, 10).map((a: any) => a.name));
    // H2 count line = filtered matches over the full list (not the page slice).
    expect(screen.getByTestId('portfolio-match-count').textContent).toBe('12 of 12 accounts match');
  });

  it('searches over name OR alias; filter/sort/reset round-trip; row click navigates', async () => {
    const onNavigate = vi.fn();
    render(<AdminConsole onNavigate={onNavigate} />);
    const block = await screen.findByTestId('admin-console-portfolio');
    // alias search (A7/C2): "Second Acct" is an alias of "Acct 02" (payload row 2).
    const q = within(block).getByLabelText('Search customers') as HTMLInputElement;
    fireEvent.change(q, { target: { value: 'second' } });
    expect(screen.getByTestId('portfolio-match-count').textContent).toBe('1 of 12 accounts match');
    fireEvent.change(q, { target: { value: 'acct 03' } });
    expect(portfolioRows()).toEqual(['Acct 03']);
    // name search on a first-page account.
    fireEvent.change(q, { target: { value: 'acct 01' } });
    expect(portfolioRows()).toEqual(['Acct 01']);
    // reset restores the first-10 payload view.
    fireEvent.click(within(block).getByRole('button', { name: 'Reset filters' }));
    expect(portfolioRows()).toEqual(data.accounts.slice(0, 10).map((a: any) => a.name));
    // click-through: the existing admin deep-link convention.
    fireEvent.click(within(block).getByRole('button', { name: 'Open Acct 01' }));
    expect(onNavigate).toHaveBeenCalledWith('customers', 'Acct 01');
  });

  it('sorts A–Z on request (first page of the sorted list)', async () => {
    render(<AdminConsole onNavigate={() => undefined} />);
    const block = await screen.findByTestId('admin-console-portfolio');
    const sortSelect = within(block).getByLabelText('Sort by') as HTMLSelectElement;
    fireEvent.change(sortSelect, { target: { value: 'name' } });
    expect(portfolioRows()).toEqual(
      ['Acct 01', 'Acct 02', 'Acct 03', 'Acct 04', 'Acct 05', 'Acct 06', 'Acct 07', 'Acct 08', 'Acct 09', 'Acct 10'],
    );
  });
});

describe('Part 14 AdminConsole Users (C3)', () => {
  it('caps the table at the first 10 users with an honest count line', async () => {
    render(<AdminConsole onNavigate={() => undefined} />);
    await screen.findByLabelText('Search users');
    expect(rowUsers()).toEqual(data.users.slice(0, 10).map(u => u.username));
    expect(count()).toBe('Showing the first 10 of 14 users');
    expect(screen.queryByLabelText('Reset user search')).toBeNull();
  });

  it('search narrows (status / role / department / email) and reset restores', async () => {
    render(<AdminConsole onNavigate={() => undefined} />);
    await screen.findByLabelText('Search users');
    fireEvent.change(search(), { target: { value: 'pending' } });
    expect(rowUsers()).toEqual(['user12', 'user13', 'user14']);
    expect(count()).toBe('3 of 14 users match');
    fireEvent.change(search(), { target: { value: 'ADMIN' } });
    expect(rowUsers()).toEqual(['user01']);
    fireEvent.change(search(), { target: { value: 'manager' } });
    expect(rowUsers()).toEqual(['user04']);
    fireEvent.change(search(), { target: { value: 'u7@example' } });
    expect(rowUsers()).toEqual(['user07']);
    fireEvent.change(search(), { target: { value: 'member' } });
    expect(count()).toBe('12 of 14 users match — showing the first 10');
    expect(tableRows()).toHaveLength(10);
    fireEvent.change(search(), { target: { value: 'operations' } });
    expect(count()).toBe('7 of 14 users match');
    fireEvent.click(screen.getByLabelText('Reset user search'));
    expect(search().value).toBe('');
    expect(rowUsers()).toEqual(data.users.slice(0, 10).map(u => u.username));
  });

  it('Approve stays on visible pending rows; View all users navigates', async () => {
    const onNavigate = vi.fn();
    render(<AdminConsole onNavigate={onNavigate} />);
    await screen.findByLabelText('Search users');
    fireEvent.change(search(), { target: { value: 'pending' } });
    expect(screen.getAllByRole('button', { name: 'Approve' })).toHaveLength(3);
    fireEvent.click(screen.getByLabelText('View all users'));
    expect(onNavigate).toHaveBeenCalledWith('admin-users');
  });
});
