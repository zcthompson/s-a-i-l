/**
 * FE-08 — session-redirect dedup + Login return-to-destination.
 *
 * Complements SessionRedirect.test.ts (destination-safety helpers):
 *   - beginSessionRedirect() lets only the first of several simultaneous
 *     401 handlers perform the redirect.
 *   - Login navigates to the stored internal destination after a
 *     successful login and clears it.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';

const { navigate, setParams, params, apiStub } = vi.hoisted(() => ({
  navigate: vi.fn(),
  setParams: vi.fn(),
  params: new URLSearchParams(),
  apiStub: new Proxy({}, {
    get: (_t, p) => {
      if (p === 'login') return () => Promise.resolve({ token: 'tok', is_admin: false, role: 'member' });
      return () => Promise.reject(new Error('unexpected api call ' + String(p)));
    },
  }) as any,
}));

vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual<any>('react-router-dom');
  return { ...actual, useNavigate: () => navigate, useSearchParams: () => [params, setParams] };
});
vi.mock('../src/lib/api', () => ({
  api: apiStub, clearAuth: vi.fn(), setAuth: vi.fn(),
  getAuthUsername: () => '', getAuthIsAdmin: () => false, getAuthRole: () => 'member',
  getAuthToken: () => null,
}));
vi.mock('../src/lib/websocket', () => ({
  ws: { connect: vi.fn().mockResolvedValue(undefined), disconnect: vi.fn(), subscribe: vi.fn() },
}));

import { beginSessionRedirect, resetSessionRedirect } from '../src/lib/sessionRedirect';
import { LoginPage } from '../src/pages/Login';

describe('sessionRedirect (FE-08)', () => {
  beforeEach(() => {
    window.sessionStorage.clear();
    navigate.mockClear();
    resetSessionRedirect();
  });

  it('dedups simultaneous redirects (only first wins)', () => {
    expect(beginSessionRedirect()).toBe(true);
    expect(beginSessionRedirect()).toBe(false);
    expect(beginSessionRedirect()).toBe(false);
  });

  it('Login returns the user to the stored internal destination after success', async () => {
    window.sessionStorage.setItem('sail_session_return', '/some/dest?x=1');
    const { container } = render(<MemoryRouter><LoginPage /></MemoryRouter>);
    const button = await screen.findByRole('button', { name: 'Log in' });
    const inputs = container.querySelectorAll('input');
    fireEvent.change(inputs[0] as HTMLInputElement, { target: { value: 'admin' } });
    fireEvent.change(inputs[1] as HTMLInputElement, { target: { value: 'pw' } });
    fireEvent.click(button);
    await waitFor(() => expect(navigate).toHaveBeenCalledWith('/some/dest?x=1'));
    expect(window.sessionStorage.getItem('sail_session_return')).toBe(null);
  });
});
