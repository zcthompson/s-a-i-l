/** Both dashboard destinations use the same authorized portfolio and actions. */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, within, waitFor } from '@testing-library/react';
import { MemoryRouter, useLocation } from 'react-router-dom';

const { api, portfolio } = vi.hoisted(() => {
  const portfolio = vi.fn();
  return { portfolio, api: {
    getPortfolioAccountImpact: portfolio,
    getCustomersStats: vi.fn(), listCustomers: vi.fn(), myTasks: vi.fn(),
    getMyCustomers: vi.fn(), listVerticals: vi.fn().mockResolvedValue({ verticals: [] }),
  } };
});
vi.mock('../src/lib/api', () => ({ api, getAuthSalesRole: () => null }));
vi.mock('../src/components/AdminConsole', () => ({ AdminConsole: () => null }));
import { HomeDashboard as MyDashboard } from '../src/pages/HomeDashboard';

function Location() { const loc = useLocation(); return <span data-testid="location">{loc.search}</span>; }
const navigate = vi.fn();
function mount() {
  return render(<MemoryRouter initialEntries={['/?view=my-dashboard&q=Team']}>
    <MyDashboard username="fixture" onNavigate={navigate} /><Location />
  </MemoryRouter>);
}
beforeEach(() => {
  vi.clearAllMocks();
  api.getCustomersStats.mockResolvedValue({ total_customers: 2, customers: [
    { customer_id: 1, customer_name: 'Team account', use_case_count: 0 },
    { customer_id: 2, customer_name: 'Read only', use_case_count: 0 },
  ] });
  api.listCustomers.mockResolvedValue([]);
  api.myTasks.mockResolvedValue([]);
  portfolio.mockResolvedValue({ customer_count: 2, coverage: 'not_quantified', scope: 'Authorized customers',
    total_impact: { value: null }, customers: [
      { customer_id: 1, customer_name: 'Team account', coverage: 'not_quantified', total_impact: null, can_score: true, can_manage_customer: true },
      { customer_id: 2, customer_name: 'Read only', coverage: 'not_quantified', total_impact: null, can_score: false, can_manage_customer: false },
    ],
  });
});
afterEach(cleanup);

describe('shared portfolio on the legacy dashboard route', () => {
  it('uses the portfolio rather than the junction list and retains the route and filters', async () => {
    mount();
    expect(await screen.findByText('Team account')).toBeTruthy();
    expect(api.getMyCustomers).not.toHaveBeenCalled();
    expect(screen.getByText('Customer portfolio — 2 customers')).toBeTruthy();
    expect(await screen.findByText('No open tasks assigned to you.')).toBeTruthy();
    expect(screen.getByTestId('location').textContent).toContain('view=my-dashboard');
    fireEvent.change(screen.getByLabelText('Search customers'), { target: { value: 'Read only' } });
    expect(screen.getByText('Read only')).toBeTruthy();
    expect(screen.queryByText('Team account')).toBeNull();
    expect(screen.getByText('Customer portfolio — 2 customers')).toBeTruthy();
  });

  it('shows and dispatches only actions authorized by each portfolio row', async () => {
    mount();
    await screen.findByText('Team account');
    const row = screen.getByText('Team account').closest('tr')!;
    fireEvent.click(within(row).getByRole('button', { name: 'Score Team account' }));
    expect(navigate).toHaveBeenCalledWith('customers', 'Team account', 'bulk-score');
    fireEvent.click(within(row).getByRole('button', { name: 'Edit Team account' }));
    expect(navigate).toHaveBeenCalledWith('customers', 'Team account', 'edit');
    fireEvent.click(within(row).getByRole('button', { name: 'Remove Team account' }));
    expect(navigate).toHaveBeenCalledWith('customers', 'Team account', 'remove');
    fireEvent.change(screen.getByLabelText('Search customers'), { target: { value: 'Read only' } });
    const readonly = screen.getByText('Read only').closest('tr')!;
    expect(within(readonly).queryByRole('button', { name: /Score|Edit|Remove/ })).toBeNull();
  });

  it('keeps assigned tasks independent of an administrator portfolio scope change', async () => {
    api.myTasks.mockResolvedValue([{ id: 41, title: 'Review renewal', customer_name: 'Team account', status: 'open', due_date: '2026-01-01', overdue: true }]);
    render(<MemoryRouter initialEntries={['/?view=dashboard']}><MyDashboard username="fixture" isAdmin onNavigate={navigate} /><Location /></MemoryRouter>);
    expect((await screen.findByTestId('my-tasks-overdue-count')).textContent).toBe('1 overdue');
    fireEvent.click(screen.getByLabelText('Toggle between My View and All View'));
    await waitFor(() => expect(portfolio).toHaveBeenLastCalledWith(true));
    expect(api.myTasks).toHaveBeenCalledTimes(1);
    expect((await screen.findByTestId('my-tasks-overdue-count')).textContent).toBe('1 overdue');
    fireEvent.click(screen.getByTestId('my-task-41'));
    expect(navigate).toHaveBeenCalledWith('customers', 'Team account');
    expect(api.myTasks).toHaveBeenCalledWith();
  });

  it('keeps the portfolio usable if personal tasks fail to load', async () => {
    api.myTasks.mockRejectedValue(new Error('Tasks unavailable'));
    mount();
    expect((await screen.findByTestId('my-tasks-error')).textContent).toContain('Tasks unavailable');
    expect(screen.getByText('Team account')).toBeTruthy();
  });

  it('reports an empty authorized portfolio', async () => {
    portfolio.mockResolvedValue({ customer_count: 0, coverage: 'not_quantified', total_impact: { value: null }, customers: [] });
    mount();
    expect(await screen.findByText('No customers in this portfolio.')).toBeTruthy();
  });
});
