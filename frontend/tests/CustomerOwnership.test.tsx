/**
 * Component tests for the admin-only Customer Ownership queue (0.2.13).
 * Covers the Ownership Review → Customer Ownership rename, the 10/20/50/100
 * per-page control, page slicing, and the resolve (audited transfer) flow.
 * Mocks the api module (repo pattern: vi.hoisted + vi.mock factory).
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, waitFor, cleanup } from '@testing-library/react';
import { CustomerOwnership } from '../src/components/CustomerOwnership';
import type { OwnershipReviewItem, UserResponse } from '../src/types/use_case';

const { apiMock, authState } = vi.hoisted(() => ({
  apiMock: {
    getOwnershipReview: vi.fn(),
    resolveOwnershipReview: vi.fn(),
    getAllUsers: vi.fn(),
  },
  authState: { isAdmin: true },
}));

vi.mock('../src/lib/api', () => ({
  api: apiMock,
  getAuthIsAdmin: () => authState.isAdmin,
  getAuthSalesRole: () => null,
}));

const users: UserResponse[] = [
  { id: 101, username: 'admin', display_name: 'Administrator', email: 'user3@sail.example', department: 'Global Administrator', role: 'admin', sales_role: null, is_admin: 1, approved: 1, created_at: '2026-10-01T00:00:00Z', is_active: 1, auth_provider: 'local' },
  { id: 201, username: 'rep_one', display_name: 'Rep One', email: 'rep1@sail.example', department: 'Sales', role: 'user', sales_role: 'rep', is_admin: 0, approved: 1, created_at: '2026-10-01T00:00:00Z', is_active: 1, auth_provider: 'local' },
  { id: 202, username: 'rep_two', display_name: 'Rep Two', email: 'rep2@sail.example', department: 'Sales', role: 'user', sales_role: 'rep', is_admin: 0, approved: 1, created_at: '2026-10-01T00:00:00Z', is_active: 1, auth_provider: 'local' },
];

// 25 placeholder accounts → forces a second page at the default size of 20.
const items: OwnershipReviewItem[] = Array.from({ length: 25 }, (_, i) => ({
  customer_id: 1000 + i + 1,
  name: `Acme ${i + 1}`,
  current_owner: 'Administrator',
  current_owner_user_id: 101,
  placeholder: true,
}));

afterEach(() => cleanup());

describe('CustomerOwnership', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    authState.isAdmin = true;
    apiMock.getOwnershipReview.mockResolvedValue({ items });
    apiMock.getAllUsers.mockResolvedValue(users);
    apiMock.resolveOwnershipReview.mockResolvedValue({ ok: true });
  });

  it('keeps hook order stable when admin status changes while mounted', async () => {
    authState.isAdmin = false;
    const { container, rerender } = render(<CustomerOwnership />);
    expect(container.innerHTML).toBe('');
    authState.isAdmin = true;
    rerender(<CustomerOwnership />);
    await screen.findByRole('heading', { name: 'Customer Ownership' });
    expect(screen.getByText(/Showing 1–20 of 25/)).toBeTruthy();
    authState.isAdmin = false;
    rerender(<CustomerOwnership />);
    expect(container.innerHTML).toBe('');
  });

  it('renders the renamed queue with the default 20/page slice', async () => {
    render(<CustomerOwnership />);
    await screen.findByRole('heading', { name: 'Customer Ownership' });
    expect(screen.queryByText('Ownership Review Queue')).toBeNull();
    expect(screen.getByText(/Showing 1–20 of 25/)).toBeTruthy();
    // Default page size is 20; the page-size select offers 10/20/50/100.
    const sizeSelect = screen.getByLabelText('Accounts per page') as HTMLSelectElement;
    expect(sizeSelect.value).toBe('20');
    expect(Array.from(sizeSelect.options).map(o => o.value)).toEqual(['10', '20', '50', '100']);
    // First and last rows of page 1, none from page 2.
    expect(screen.getByText('Acme 1')).toBeTruthy();
    expect(screen.getByText('Acme 20')).toBeTruthy();
    expect(screen.queryByText('Acme 21')).toBeNull();
    expect(apiMock.getOwnershipReview).toHaveBeenCalledTimes(1);
  });

  it('paginates: Next reaches page 2, the size select reslices and resets to page 1', async () => {
    render(<CustomerOwnership />);
    await screen.findByRole('heading', { name: 'Customer Ownership' });
    fireEvent.click(screen.getByRole('button', { name: 'Next page' }));
    expect(screen.getByText(/Showing 21–25 of 25/)).toBeTruthy();
    expect(screen.getByText('Acme 25')).toBeTruthy();
    expect(screen.queryByText('Acme 1')).toBeNull();
    // Pick 10 per page: back to page 1 with a 10-row slice.
    const sizeSelect = screen.getByLabelText('Accounts per page');
    fireEvent.change(sizeSelect, { target: { value: '10' } });
    expect(screen.getByText(/Showing 1–10 of 25/)).toBeTruthy();
    expect(screen.queryByText('Acme 11')).toBeNull();
    // 10 × 3 = 30 ≥ 25 → three pages at this size, so page 1 has Next enabled.
    expect((screen.getByRole('button', { name: 'Next page' }) as HTMLButtonElement).disabled).toBe(false);
  });

  it('resolves an account with the standard audited transfer call', async () => {
    render(<CustomerOwnership />);
    await screen.findByRole('heading', { name: 'Customer Ownership' });
    const select = screen.getByLabelText('New primary owner for Acme 1') as HTMLSelectElement;
    const resolveBtn = screen.getByRole('button', { name: 'Resolve ownership for Acme 1' }) as HTMLButtonElement;
    // Disabled until an owner is chosen.
    expect(resolveBtn.disabled).toBe(true);
    fireEvent.change(select, { target: { value: '201' } });
    expect(resolveBtn.disabled).toBe(false);
    fireEvent.click(resolveBtn);
    await waitFor(() => expect(apiMock.resolveOwnershipReview).toHaveBeenCalledTimes(1));
    expect(apiMock.resolveOwnershipReview).toHaveBeenCalledWith(1001, 201);
    await screen.findByText(/Acme 1 resolved — ownership transferred and audited\./);
  });

  it('deep-links the account to its customer dashboard', async () => {
    const onOpenCustomer = vi.fn();
    render(<CustomerOwnership onOpenCustomer={onOpenCustomer} />);
    await screen.findByRole('heading', { name: 'Customer Ownership' });
    fireEvent.click(screen.getByRole('button', { name: 'Open Acme 3' }));
    expect(onOpenCustomer).toHaveBeenCalledWith('Acme 3');
  });

  it('shows the empty state when the queue is clear', async () => {
    apiMock.getOwnershipReview.mockResolvedValue({ items: [] });
    render(<CustomerOwnership />);
    await screen.findByRole('heading', { name: 'Customer Ownership' });
    expect(screen.getByText('No accounts awaiting ownership review.')).toBeTruthy();
    expect(screen.queryByLabelText('Accounts per page')).toBeNull();
  });

  it('renders nothing for a non-admin and makes no calls', () => {
    authState.isAdmin = false;
    const { container } = render(<CustomerOwnership />);
    expect(container.innerHTML).toBe('');
    expect(apiMock.getOwnershipReview).not.toHaveBeenCalled();
    expect(apiMock.getAllUsers).not.toHaveBeenCalled();
  });

  it('surfaces a load failure in the error banner', async () => {
    apiMock.getOwnershipReview.mockRejectedValue(new Error('boom'));
    render(<CustomerOwnership />);
    const alert = await screen.findByRole('alert');
    expect(alert.textContent).toContain('boom');
  });
});
