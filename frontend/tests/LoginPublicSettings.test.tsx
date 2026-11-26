import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { LoginPage } from '../src/pages/Login';

const { apiMock } = vi.hoisted(() => ({
  apiMock: {
    getAuthPublicSettings: vi.fn(),
    getPendingUsers: vi.fn(),
    approveUser: vi.fn(),
    login: vi.fn(),
    register: vi.fn(),
  },
}));

vi.mock('../src/lib/api', () => ({
  api: apiMock,
  setAuth: vi.fn(),
  clearAuth: vi.fn(),
  getAuthToken: () => null,
  getAuthUsername: () => null,
  getAuthIsAdmin: () => false,
  getAuthSalesRole: () => null,
}));

beforeEach(() => {
  Object.values(apiMock).forEach((mock) => mock.mockReset());
});

afterEach(cleanup);

function mount(settings: { local_register_enabled: boolean; ldap_enabled: boolean; login_hint: string }) {
  apiMock.getAuthPublicSettings.mockResolvedValue(settings);
  return render(<MemoryRouter><LoginPage /></MemoryRouter>);
}

describe('Login public auth settings', () => {
  it('renders the directory login hint when LDAP is enabled', async () => {
    mount({ local_register_enabled: true, ldap_enabled: true, login_hint: 'Use your corporate AD credentials.' });
    expect(await screen.findByText('Use your corporate AD credentials.')).toBeTruthy();
  });

  it('hides Register and explains when local self-registration is disabled', async () => {
    mount({ local_register_enabled: false, ldap_enabled: false, login_hint: '' });
    expect(await screen.findByText('Self-registration is disabled — contact an administrator.')).toBeTruthy();
    expect(screen.queryByRole('button', { name: 'Switch to registration' })).toBeNull();
  });

  it('preserves the default registration experience without a directory hint', async () => {
    mount({ local_register_enabled: true, ldap_enabled: false, login_hint: '' });
    expect(await screen.findByRole('button', { name: 'Switch to registration' })).toBeTruthy();
    expect(screen.queryByText('Self-registration is disabled — contact an administrator.')).toBeNull();
    expect(screen.queryByText('Use your corporate AD credentials.')).toBeNull();
  });
});
