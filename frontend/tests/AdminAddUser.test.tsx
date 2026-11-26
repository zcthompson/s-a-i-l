import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { AdminPage } from '../src/pages/AdminPage';

const { apiMock } = vi.hoisted(() => ({
  apiMock: {
    getPendingUsers: vi.fn(), getAllUsers: vi.fn(), createUser: vi.fn(), approveUser: vi.fn(),
    updateUser: vi.fn(), resetUserPassword: vi.fn(), activateUser: vi.fn(), deactivateUser: vi.fn(), deleteUser: vi.fn(),
  },
}));

vi.mock('../src/lib/api', () => ({ api: apiMock }));
vi.mock('../src/lib/auth', () => ({ getAuthUsername: () => 'admin' }));

beforeEach(() => {
  Object.values(apiMock).forEach(mock => mock.mockReset());
  apiMock.getPendingUsers.mockResolvedValue([]);
  apiMock.getAllUsers.mockResolvedValue([]);
  apiMock.createUser.mockResolvedValue({ id: 2, username: 'new.user' });
});
afterEach(cleanup);

async function openModal() {
  render(<AdminPage activeView="all-users" />);
  await screen.findByText('No users found');
  fireEvent.click(screen.getByRole('button', { name: 'Add user' }));
  return screen.getByRole('dialog', { name: 'Add user' });
}

function fillRequired(username = 'new.user') {
  fireEvent.change(screen.getByLabelText('New user username'), { target: { value: username } });
  fireEvent.change(screen.getByLabelText('New user password'), { target: { value: 'StrongPassword12!' } });
}

describe('Admin Add User', () => {
  it('renders the portaled admin modal with every control', async () => {
    const dialog = await openModal();
    expect(dialog.parentElement).toBe(document.body);
    for (const label of ['New user username', 'New user display name', 'New user email', 'New user password', 'New user department', 'New user role', 'New user sales role', 'Create active']) {
      expect(screen.getByLabelText(label)).toBeTruthy();
    }
  });

  it('posts pending and inactive by default, omitting blank optional values', async () => {
    await openModal();
    fillRequired();
    fireEvent.click(screen.getByRole('button', { name: 'Create user' }));
    await waitFor(() => expect(apiMock.createUser).toHaveBeenCalledTimes(1));
    expect(apiMock.createUser).toHaveBeenCalledWith({
      username: 'new.user', password: 'StrongPassword12!', role: 'user', approved: false, is_active: false,
    });
    expect(await screen.findByText('Created new.user.')).toBeTruthy();
  });

  it('sends approved and active when Create active is checked', async () => {
    await openModal();
    fillRequired('active.user');
    fireEvent.click(screen.getByLabelText('Create active'));
    fireEvent.change(screen.getByLabelText('New user role'), { target: { value: 'auditor' } });
    fireEvent.click(screen.getByRole('button', { name: 'Create user' }));
    await waitFor(() => expect(apiMock.createUser).toHaveBeenCalledWith(expect.objectContaining({
      username: 'active.user', role: 'auditor', approved: true, is_active: true,
    })));
  });

  it('keeps the modal open and displays backend detail errors inline', async () => {
    apiMock.createUser.mockRejectedValueOnce(new Error('Username or email already in use'));
    await openModal();
    fillRequired();
    fireEvent.click(screen.getByRole('button', { name: 'Create user' }));
    expect((await screen.findByRole('alert')).textContent).toContain('Username or email already in use');
    expect(screen.getByRole('dialog', { name: 'Add user' })).toBeTruthy();
  });
});

it('contains modal keyboard focus and returns it to Add user on Escape', async () => {
  render(<AdminPage activeView="all-users" />);
  const opener = await screen.findByRole('button', { name: 'Add user' });
  opener.focus();
  fireEvent.click(opener);
  const first = screen.getByLabelText('New user username');
  const cancel = screen.getByRole('button', { name: 'Cancel adding user' });
  expect(document.activeElement).toBe(first);
  fireEvent.keyDown(first, { key: 'Tab', shiftKey: true });
  expect(document.activeElement).toBe(cancel); // Create is disabled until fields are valid.
  fireEvent.keyDown(cancel, { key: 'Tab' });
  expect(document.activeElement).toBe(first);
  fireEvent.keyDown(first, { key: 'Escape' });
  expect(screen.queryByRole('dialog')).toBeNull();
  expect(document.activeElement).toBe(opener);
});
