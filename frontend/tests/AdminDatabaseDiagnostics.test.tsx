import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen } from '@testing-library/react';
import { AdminConsole } from '../src/components/AdminConsole';

const { apiMock } = vi.hoisted(() => ({ apiMock: {
  getGlobalAdminStats: vi.fn(), getAllUsers: vi.fn(), getDatabaseDiagnostics: vi.fn(),
} }));
vi.mock('../src/lib/api', () => ({ api: apiMock }));
beforeEach(() => {
  apiMock.getGlobalAdminStats.mockResolvedValue(null);
  apiMock.getAllUsers.mockResolvedValue([]);
  apiMock.getDatabaseDiagnostics.mockReset();
});
afterEach(cleanup);

describe('admin database diagnostics', () => {
  it.each([['sqlite', 'SQLite'], ['postgresql', 'PostgreSQL']])('displays the active %s backend', async (backend, label) => {
    apiMock.getDatabaseDiagnostics.mockResolvedValue({ database: { backend, connected: true } });
    render(<AdminConsole onNavigate={() => {}} showPortfolio={false} />);
    expect(await screen.findByText(`Database: ${label}`)).toBeTruthy();
  });
  it('reports unavailable diagnostics without exposing an error', async () => {
    apiMock.getDatabaseDiagnostics.mockRejectedValue(new Error('sensitive internal details'));
    render(<AdminConsole onNavigate={() => {}} showPortfolio={false} />);
    expect(await screen.findByText('Database: Unavailable')).toBeTruthy();
    expect(screen.queryByText(/sensitive internal details/)).toBeNull();
  });
});
