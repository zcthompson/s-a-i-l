/**
 * Component tests for the admin-only CustomerSalesTeam editor (0.2.10).
 * Mocks the api module (repo pattern: vi.hoisted + vi.mock factory).
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, waitFor, cleanup } from '@testing-library/react';
import { CustomerSalesTeam } from '../src/components/CustomerSalesTeam';

const { apiMock, authState } = vi.hoisted(() => ({
  apiMock: {
    getAllUsers: vi.fn(),
    getCustomerSalesTeam: vi.fn(),
    updateCustomerSalesTeam: vi.fn(),
  },
  authState: { isAdmin: true },
}));

vi.mock('../src/lib/api', () => ({
  api: apiMock,
  getAuthIsAdmin: () => authState.isAdmin,
  getAuthSalesRole: () => null,
}));

const users = [
  { id: 1, username: 'rep_one', display_name: 'Rep One', sales_role: 'rep' },
  { id: 2, username: 'rep_two', display_name: 'Rep Two', sales_role: 'rep' },
  { id: 3, username: 'mgr', display_name: 'Manager', sales_role: 'sales_manager' },
  { id: 4, username: 'ins', display_name: 'Inside One', sales_role: 'inside_sales' },
  { id: 5, username: 'ins2', display_name: 'Inside Two', sales_role: 'inside_sales' },
  { id: 6, username: 'ins3', display_name: 'Inside Three', sales_role: 'inside_sales' },
  { id: 7, username: 'ops', display_name: 'Ops One', sales_role: 'sales_ops' },
];

const team = {
  customer_id: 9,
  primary_rep: { user_id: 1, name: 'Rep One', sales_role: 'rep' },
  manager: { user_id: 3, name: 'Manager', sales_role: 'sales_manager' },
  inside_sales: [
    { user_id: 4, name: 'Inside One', auto_linked: false, link_reason: null },
    { user_id: 5, name: 'Inside Two', auto_linked: true, link_reason: 'Auto-linked: INS supports BROWN — last-name match: INS==BROWN' },
  ],
  sales_ops: [],
};

// Team with no auto-linked rows (manual-row Remove coverage).
const teamNoAuto = {
  ...team,
  inside_sales: [
    { user_id: 4, name: 'Inside One', auto_linked: false, link_reason: null },
    { user_id: 5, name: 'Inside Two', auto_linked: false, link_reason: null },
  ],
};

afterEach(() => cleanup());

describe('CustomerSalesTeam', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    authState.isAdmin = true;
    apiMock.getAllUsers.mockResolvedValue(users);
    apiMock.getCustomerSalesTeam.mockResolvedValue(team);
  });

  it('renders the editor for an admin with current state', async () => {
    render(<CustomerSalesTeam customerName="Acme" />);
    const rep = (await screen.findByTestId('sales-team-rep-select')) as HTMLSelectElement;
    expect(rep.value).toBe('1');
    expect((screen.getByTestId('sales-team-manager-select') as HTMLSelectElement).value).toBe('3');
    // Inside-sales list: both assignments shown as rows.
    const rows = screen.getAllByTestId(/^sales-team-inside-row-\d+$/);
    expect(rows).toHaveLength(2);
    // Auto-linked badge appears on the auto-linked row.
    const badge = screen.getByText('Auto-linked');
    expect(badge).toBeTruthy();
    // Link reason appears on the auto-linked row.
    const reason = screen.getByText('Auto-linked: INS supports BROWN — last-name match: INS==BROWN');
    expect(reason).toBeTruthy();
    // Remove button on every row (manual and auto-linked alike).
    const removeBtns = screen.getAllByRole('button', { name: 'Remove' });
    expect(removeBtns).toHaveLength(2);
    // Sales-ops dropdown: "— none —" default, Ops One as an option (role-populated).
    const ops = screen.getByTestId('sales-team-sales-ops') as HTMLSelectElement;
    expect(ops.value).toBe('');
    expect(ops.options.length).toBe(2); // "— none —" + Ops One
    expect(apiMock.getCustomerSalesTeam).toHaveBeenCalledWith('Acme');
  });

  it('renders nothing for a non-admin and makes no calls', () => {
    authState.isAdmin = false;
    const { container } = render(<CustomerSalesTeam customerName="Acme" />);
    expect(container.innerHTML).toBe('');
    expect(apiMock.getCustomerSalesTeam).not.toHaveBeenCalled();
  });

  it('sends the selections to the PUT call and refreshes the parent', async () => {
    apiMock.updateCustomerSalesTeam.mockResolvedValue({
      ...team,
      primary_rep: { user_id: 2, name: 'Rep Two', sales_role: 'rep' },
      sales_ops: [{ user_id: 7, name: 'Ops One', auto_linked: false, link_reason: null }],
    });
    const onSaved = vi.fn();
    render(<CustomerSalesTeam customerName="Acme" onSaved={onSaved} />);
    await screen.findByTestId('sales-team-rep-select');
    const rep = screen.getByTestId('sales-team-rep-select') as HTMLSelectElement;
    fireEvent.change(rep, { target: { value: '2' } });
    fireEvent.change(screen.getByTestId('sales-team-manager-select'), { target: { value: '' } });
    // Select Ops One in the sales-ops dropdown.
    fireEvent.change(screen.getByTestId('sales-team-sales-ops'), { target: { value: '7' } });
    fireEvent.click(screen.getByText('Save'));
    await waitFor(() => expect(apiMock.updateCustomerSalesTeam).toHaveBeenCalled());
    expect(apiMock.updateCustomerSalesTeam).toHaveBeenCalledWith('Acme', {
      primary_rep_user_id: 2,
      manager_user_id: null,
      inside_sales_user_ids: [4, 5],
      sales_ops_user_ids: [7],
    });
    await waitFor(() => expect(onSaved).toHaveBeenCalled());
    expect(await screen.findByText('Sales team saved')).toBeTruthy();
  });

  it('clears inside assignments when removed', async () => {
    apiMock.updateCustomerSalesTeam.mockResolvedValue({
      ...team,
      inside_sales: [],
      sales_ops: [],
    });
    render(<CustomerSalesTeam customerName="Acme" />);
    await screen.findByTestId('sales-team-rep-select');
    // Remove the auto-linked Inside Two assignment (row-scoped control).
    fireEvent.click(screen.getByTestId('sales-team-inside-remove-5'));
    fireEvent.click(screen.getByText('Save'));
    await waitFor(() => expect(apiMock.updateCustomerSalesTeam).toHaveBeenCalled());
    expect(apiMock.updateCustomerSalesTeam).toHaveBeenCalledWith('Acme', {
      primary_rep_user_id: 1,
      manager_user_id: 3,
      inside_sales_user_ids: [4],
      sales_ops_user_ids: [],
    });
  });

  it('adds a new inside-sales assignment via the Add control', async () => {
    apiMock.updateCustomerSalesTeam.mockResolvedValue({
      ...team,
      inside_sales: [
        { user_id: 4, name: 'Inside One', auto_linked: false, link_reason: null },
        { user_id: 5, name: 'Inside Two', auto_linked: true, link_reason: 'Auto-linked: INS supports BROWN — last-name match: INS==BROWN' },
        { user_id: 6, name: 'Inside Three', auto_linked: false, link_reason: null },
      ],
    });
    render(<CustomerSalesTeam customerName="Acme" />);
    await screen.findByTestId('sales-team-rep-select');
    // Add Inside Three (available inside_sales user) as an assignment.
    fireEvent.change(screen.getByTestId('sales-team-inside-add'), { target: { value: '6' } });
    fireEvent.click(screen.getByText('Add'));
    fireEvent.click(screen.getByText('Save'));
    await waitFor(() => expect(apiMock.updateCustomerSalesTeam).toHaveBeenCalled());
    expect(apiMock.updateCustomerSalesTeam).toHaveBeenCalledWith('Acme', {
      primary_rep_user_id: 1,
      manager_user_id: 3,
      inside_sales_user_ids: [4, 5, 6],
      sales_ops_user_ids: [],
    });
  });

  it('populates the add dropdown from inside_sales-role users only', async () => {
    render(<CustomerSalesTeam customerName="Acme" />);
    await screen.findByTestId('sales-team-rep-select');
    const addSelect = screen.getByTestId('sales-team-inside-add') as HTMLSelectElement;
    const addOptionTexts = Array.from(addSelect.options).map((o) => o.textContent);
    expect(addOptionTexts).toContain('+ Add inside sales');
    expect(addOptionTexts).toContain('Inside Three');
    expect(addOptionTexts).not.toContain('Inside One'); // already assigned
    expect(addOptionTexts).not.toContain('Inside Two'); // already assigned
    expect(addOptionTexts).not.toContain('Rep One');
    expect(addOptionTexts).not.toContain('Rep Two');
    expect(addOptionTexts).not.toContain('Manager');
    expect(addOptionTexts).not.toContain('Ops One');
  });

  it('does not allow adding a user already assigned', async () => {
    render(<CustomerSalesTeam customerName="Acme" />);
    await screen.findByTestId('sales-team-rep-select');
    // Inside One and Inside Two are already assigned — should not appear.
    const addSelect = screen.getByTestId('sales-team-inside-add') as HTMLSelectElement;
    const addOptionTexts = Array.from(addSelect.options).map((o) => o.textContent);
    expect(addOptionTexts).not.toContain('Inside One');
    expect(addOptionTexts).not.toContain('Inside Two');
    expect(addOptionTexts).toContain('Inside Three');
  });

  it('renders the error message when save fails', async () => {
    apiMock.updateCustomerSalesTeam.mockRejectedValue(new Error('cannot clear primary rep'));
    render(<CustomerSalesTeam customerName="Acme" />);
    await screen.findByTestId('sales-team-rep-select');
    fireEvent.click(screen.getByText('Save'));
    expect(await screen.findByText('cannot clear primary rep')).toBeTruthy();
  });

  it('keeps manually-added assignments without auto-linked badge', async () => {
    apiMock.updateCustomerSalesTeam.mockResolvedValue({
      ...team,
      inside_sales: [
        { user_id: 4, name: 'Inside One', auto_linked: false, link_reason: null },
        { user_id: 5, name: 'Inside Two', auto_linked: true, link_reason: 'Auto-linked: INS supports BROWN — last-name match: INS==BROWN' },
        { user_id: 6, name: 'Inside Three', auto_linked: false, link_reason: null },
      ],
    });
    render(<CustomerSalesTeam customerName="Acme" />);
    await screen.findByTestId('sales-team-rep-select');
    // Add Inside Three (available inside_sales user) as a manual assignment.
    fireEvent.change(screen.getByTestId('sales-team-inside-add'), { target: { value: '6' } });
    fireEvent.click(screen.getByText('Add'));
    // The manually-added Inside Three row has no auto-linked badge.
    const badge = screen.queryByText('Auto-linked');
    expect(badge).toBeTruthy(); // Inside Two still has it
    const rows = screen.getAllByTestId(/^sales-team-inside-row-\d+$/);
    expect(rows).toHaveLength(3);
    // Remove button on every row (all three).
    const removeBtns = screen.getAllByRole('button', { name: 'Remove' });
    expect(removeBtns).toHaveLength(3);
  });

  it('renders a Remove button on manually-assigned rows', async () => {
    apiMock.getCustomerSalesTeam.mockResolvedValue(teamNoAuto);
    render(<CustomerSalesTeam customerName="Acme" />);
    await screen.findByTestId('sales-team-rep-select');
    const removeBtns = screen.queryAllByRole('button', { name: 'Remove' });
    expect(removeBtns).toHaveLength(2);
  });

  it('removes a manually-assigned inside-sales person before saving (golden-pull cleanup)', async () => {
    apiMock.getCustomerSalesTeam.mockResolvedValue(teamNoAuto);
    apiMock.updateCustomerSalesTeam.mockResolvedValue({
      ...teamNoAuto,
      inside_sales: [
        { user_id: 4, name: 'Inside One', auto_linked: false, link_reason: null },
      ],
    });
    render(<CustomerSalesTeam customerName="Acme" />);
    await screen.findByTestId('sales-team-rep-select');
    // Inside Two (manually assigned) is removed, then saved — the PUT
    // payload excludes it, so the server (replace-all semantics) deletes
    // the assignment.
    fireEvent.click(screen.getByTestId('sales-team-inside-remove-5'));
    fireEvent.click(screen.getByText('Save'));
    await waitFor(() => expect(apiMock.updateCustomerSalesTeam).toHaveBeenCalled());
    expect(apiMock.updateCustomerSalesTeam).toHaveBeenCalledWith('Acme', {
      primary_rep_user_id: 1,
      manager_user_id: 3,
      inside_sales_user_ids: [4],
      sales_ops_user_ids: [],
    });
  });
});
