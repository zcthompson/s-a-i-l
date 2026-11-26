import { afterEach, describe, expect, it, vi } from 'vitest';
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { CustomerDashboard } from '../src/pages/CustomerDashboard';
const { checkAccess } = vi.hoisted(() => ({ checkAccess: vi.fn() }));
vi.mock('../src/lib/api', () => ({ api: new Proxy({}, { get: (_t, prop) => {
  if (prop === 'checkAccess') return checkAccess;
  if (prop === 'getCustomer') return async (name: string) => ({ id: name === 'A' ? 1 : 2, name, departments: [] });
  if (prop === 'listVerticals') return async () => ({ verticals: [], departments_by_vertical: {} });
  return async () => [];
} }), getAuthIsAdmin: () => false, getAuthSalesRole: () => null, getAuthUsername: () => 'member', clearAuth: vi.fn() }));
vi.mock('../src/lib/websocket', () => ({ ws: { connect: vi.fn(), disconnect: vi.fn(), subscribe: () => vi.fn() } }));
vi.mock('../src/components/CustomerHeader', () => ({ CustomerHeader: (props: any) => <div><h1>{props.name}</h1><span>Role: {props.userRole}</span>{props.userRole === 'owner' && <button>Owner controls</button>}</div> }));
afterEach(() => { cleanup(); checkAccess.mockReset(); });
function dashboard(name = 'A') { return <MemoryRouter><CustomerDashboard onNavigate={vi.fn()} selectedCustomerName={name} /></MemoryRouter>; }
describe('customer access checks', () => {
  it('fails closed and recovers on retry', async () => {
    checkAccess.mockRejectedValueOnce(new Error('offline')).mockResolvedValueOnce({ has_access: true, permission_level: null });
    render(dashboard());
    await screen.findByRole('heading', { name: 'Access Check Failed' });
    expect(screen.queryByText('Owner controls')).toBeNull();
    expect(screen.queryByRole('heading', { name: 'A' })).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: 'Retry' }));
    await screen.findByText('Role: member');
    expect(checkAccess).toHaveBeenCalledTimes(2);
  });
  it('ignores a late owner response for the previous customer', async () => {
    let resolveA!: (value: unknown) => void;
    checkAccess.mockImplementation((name: string) => name === 'A' ? new Promise(resolve => { resolveA = resolve; }) : Promise.resolve({ has_access: true, permission_level: 'member' }));
    const view = render(dashboard());
    await waitFor(() => expect(checkAccess).toHaveBeenCalledWith('A'));
    view.rerender(dashboard('B'));
    await screen.findByRole('heading', { name: 'B' });
    await act(async () => { resolveA({ has_access: true, permission_level: 'owner' }); });
    expect(screen.getByText('Role: member')).toBeTruthy();
    expect(screen.queryByText('Owner controls')).toBeNull();
    expect(screen.queryByText('Access Check Failed')).toBeNull();
  });
  it('shows the existing denial panel', async () => {
    checkAccess.mockResolvedValue({ has_access: false, permission_level: null });
    render(dashboard());
    expect(await screen.findByRole('heading', { name: 'No Access' })).toBeTruthy();
    expect(screen.getByText("You do not have access to view this customer's data.")).toBeTruthy();
  });
  it.each([null, undefined])('defaults a granted %s role to member', async permission_level => {
    checkAccess.mockResolvedValue({ has_access: true, permission_level });
    render(dashboard());
    await screen.findByText('Role: member');
    expect(screen.queryByText('Owner controls')).toBeNull();
  });
  it('treats a missing access field as an error', async () => {
    checkAccess.mockResolvedValue({ permission_level: 'owner' });
    render(dashboard());
    await screen.findByRole('heading', { name: 'Access Check Failed' });
    expect(screen.queryByText('Owner controls')).toBeNull();
  });
});
