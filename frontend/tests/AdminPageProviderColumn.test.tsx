import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen } from '@testing-library/react';
import { AdminPage } from '../src/pages/AdminPage';

const { apiMock } = vi.hoisted(() => ({
  apiMock: {
    getPendingUsers: vi.fn(),
    getAllUsers: vi.fn(),
    approveUser: vi.fn(),
    updateUser: vi.fn(),
    resetUserPassword: vi.fn(),
    activateUser: vi.fn(),
    deactivateUser: vi.fn(),
    deleteUser: vi.fn(),
  },
}));

vi.mock('../src/lib/api', () => ({ api: apiMock }));
vi.mock('../src/lib/auth', () => ({ getAuthUsername: () => 'admin' }));

const users = [
  {
    id: 11, username: 'local.user', email: 'local@example.com', display_name: 'Local User',
    department: 'IT', role: 'user', is_admin: 0, approved: 1,
    created_at: '2026-09-01T00:00:00Z', is_active: 1, auth_provider: 'local',
  },
  {
    id: 12, username: 'directory.user', email: 'directory@example.com', display_name: 'Directory User',
    department: 'Sales', role: 'auditor', is_admin: 0, approved: 1,
    created_at: '2026-09-02T00:00:00Z', is_active: 1, auth_provider: 'ldap',
  },
];

beforeEach(() => {
  Object.values(apiMock).forEach((mock) => mock.mockReset());
  apiMock.getPendingUsers.mockResolvedValue([]);
  apiMock.getAllUsers.mockResolvedValue(users);
});

afterEach(cleanup);

describe('Admin user provider column', () => {
  it('labels local and directory users and prevents directory password resets', async () => {
    render(<AdminPage activeView="all-users" />);
    await screen.findByText('local.user');

    // Role and sign-in provider share the Access column.
    expect(screen.getByText('Access')).toBeTruthy();
    expect(screen.getByText('Local').getAttribute('title')).toBe('Sign-in provider');
    expect(screen.getByText('Directory').getAttribute('title')).toBe('Sign-in provider');

    const localReset = screen.getByRole('button', { name: 'Reset password for local.user' }) as HTMLButtonElement;
    const directoryReset = screen.getByRole('button', { name: 'Reset password for directory.user' }) as HTMLButtonElement;
    expect(localReset.disabled).toBe(false);
    expect(directoryReset.disabled).toBe(true);
    expect(directoryReset.title).toBe('Managed by the corporate directory');
  });
});
