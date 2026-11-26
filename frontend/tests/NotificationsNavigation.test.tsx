import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, useLocation, useNavigate } from 'react-router-dom';
import { NotificationsPage } from '../src/pages/NotificationsPage';

const { apiMock, handlers } = vi.hoisted(() => ({
  apiMock: { getNotifications: vi.fn(), markNotificationRead: vi.fn() },
  handlers: new Set<(message: any) => void>(),
}));
vi.mock('../src/lib/api', () => ({ api: apiMock }));
vi.mock('../src/lib/websocket', () => ({
  ws: { subscribe: (_type: string, handler: (message: any) => void) => {
    handlers.add(handler);
    return () => handlers.delete(handler);
  } },
}));

const items = [
  { id: 1, message: 'Read item', type: 'system', read: true, created_at: '2026-01-01T00:00:00Z' },
  { id: 2, message: 'Unread item', type: 'system', read: false, created_at: '2026-01-02T00:00:00Z' },
];
function RouteProbe() {
  const location = useLocation();
  const navigate = useNavigate();
  return <><output data-testid="notification-url">{location.search}</output><button onClick={() => navigate(-1)}>Back</button><button onClick={() => navigate(1)}>Forward</button></>;
}

beforeEach(() => {
  apiMock.getNotifications.mockReset().mockImplementation((_limit: number, unread: boolean) => Promise.resolve(unread ? items.filter(i => !i.read) : items));
  apiMock.markNotificationRead.mockReset().mockResolvedValue(undefined);
  handlers.clear();
});
afterEach(cleanup);

describe('notification filter navigation', () => {
  it('restores a direct filter and follows history while preserving other parameters', async () => {
    render(<MemoryRouter initialEntries={['/?view=collab-notifications&notification_filter=unread&extra=1']}><RouteProbe /><NotificationsPage onBack={() => {}} username="tester" /></MemoryRouter>);
    await screen.findByText('Unread item');
    expect(screen.queryByText('Read item')).toBeNull();
    expect(screen.getByRole('button', { name: 'Show unread notifications' }).getAttribute('aria-pressed')).toBe('true');
    fireEvent.click(screen.getByRole('button', { name: 'Show read notifications' }));
    await screen.findByText('Read item');
    expect(screen.queryByText('Unread item')).toBeNull();
    const params = new URLSearchParams(screen.getByTestId('notification-url').textContent ?? '');
    expect(params.get('notification_filter')).toBe('read');
    expect(params.get('extra')).toBe('1');
    fireEvent.click(screen.getByText('Back'));
    await screen.findByText('Unread item');
    expect(screen.queryByText('Read item')).toBeNull();
    fireEvent.click(screen.getByText('Forward'));
    await screen.findByText('Read item');
    expect(screen.queryByText('Unread item')).toBeNull();
  });

  it('falls back to all for an unknown filter', async () => {
    render(<MemoryRouter initialEntries={['/?notification_filter=invalid']}><NotificationsPage onBack={() => {}} username="tester" /></MemoryRouter>);
    await screen.findByText('Read item');
    expect(screen.getByText('Unread item')).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Show all notifications' }).getAttribute('aria-pressed')).toBe('true');
  });

  it('keeps the current filter on realtime updates and removes old subscriptions', async () => {
    const view = render(<MemoryRouter initialEntries={['/?notification_filter=unread']}><NotificationsPage onBack={() => {}} username="tester" /></MemoryRouter>);
    await screen.findByText('Unread item');
    fireEvent.click(screen.getByRole('button', { name: 'Show read notifications' }));
    await screen.findByText('Read item');
    expect(handlers.size).toBe(1);
    await act(async () => { handlers.forEach((handler) => handler({ type: 'notification_created', data: { user_name: 'tester' } })); });
    await waitFor(() => expect(screen.getByText('Read item')).toBeTruthy());
    expect(screen.queryByText('Unread item')).toBeNull();
    view.unmount();
    expect(handlers.size).toBe(0);
  });

  it('ignores an older response after the selected filter changes', async () => {
    let resolveOld!: (items: any[]) => void;
    let first = true;
    apiMock.getNotifications.mockImplementation((_limit: number, unread: boolean) => {
      if (unread && first) { first = false; return new Promise((resolve) => { resolveOld = resolve; }); }
      return Promise.resolve(unread ? items.filter(i => !i.read) : items);
    });
    render(<MemoryRouter initialEntries={['/?notification_filter=unread']}><NotificationsPage onBack={() => {}} username="tester" /></MemoryRouter>);
    fireEvent.click(screen.getByRole('button', { name: 'Show all notifications' }));
    await screen.findByText('Read item');
    await act(async () => resolveOld([items[1]]));
    expect(screen.getByText('Read item')).toBeTruthy();
    expect(screen.getByText('Unread item')).toBeTruthy();
  });
});
