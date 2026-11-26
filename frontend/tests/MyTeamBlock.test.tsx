/**
 * MyTeamBlock component tests (synthetic fixtures only).
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, cleanup, within } from '@testing-library/react';
import { MyTeamBlock, renewalsWithin90 } from '../src/components/MyTeamBlock';
import type { TeamRollupResponse, TeamRollupRep, TeamRollupSummary } from '../src/types/teamRollup';

afterEach(() => cleanup());

const { apiMock, auth } = vi.hoisted(() => ({ apiMock: { teamRollup: vi.fn() }, auth: { salesRole: 'sales_manager' as string | null } }));
vi.mock('../src/lib/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../src/lib/api')>();
  return { ...actual, api: { ...actual.api, ...apiMock }, getAuthSalesRole: () => auth.salesRole };
});

const amount = (total: number | null, coverage: TeamRollupSummary['pipeline']['acv']['coverage']) =>
  ({ total, coverage, lines_included: 0, lines_excluded: 0, accounts_no_data: 0 });

const summary = (over: Partial<TeamRollupSummary> = {}): TeamRollupSummary => ({
  accounts: 3,
  pipeline: { acv: amount(120000, 'quantified'), tcv: amount(300000, 'quantified'), stages: { open: 2, won: 0, lost: 0, unknown: 0 } },
  renewal_counts: { overdue: 1, within_30: 1, within_60: 0, within_90: 2, within_180: 5, beyond_180: 0, unknown_date: 0 },
  open_tasks: 4, overdue_tasks: 1, no_recorded_interaction: 2, no_contacts_recorded: 1,
  no_economic_buyer_recorded: 3, no_champion_recorded: 2, ...over,
});

const rep = (id: number, over: Partial<TeamRollupRep> = {}): TeamRollupRep => ({
  user_id: id, username: `synthetic_rep_${id}`, display_name: `Synthetic Rep ${id}`, ...summary(), ...over,
});

const resp = (over: Partial<TeamRollupResponse> = {}): TeamRollupResponse => ({
  generated_at: '2026-11-05T12:00:00Z', team: summary(),
  reps: [rep(1), rep(2, { pipeline: { ...summary().pipeline, acv: amount(null, 'no_data') }, renewal_counts: { ...summary().renewal_counts, overdue: 0 } })],
  basis: 'Report-owned readable accounts; not booked revenue.', ...over,
});

describe('MyTeamBlock', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    auth.salesRole = 'sales_manager';
  });

  it('renders nothing and never calls the API for non-managers', () => {
    auth.salesRole = 'rep';
    const { container } = render(<MyTeamBlock />);
    expect(container.innerHTML).toBe('');
    expect(apiMock.teamRollup).not.toHaveBeenCalled();
  });

  it('shows the team summary, per-rep rows and the basis caveat', async () => {
    apiMock.teamRollup.mockResolvedValue(resp());
    render(<MyTeamBlock />);
    await screen.findByTestId('my-team-summary');
    expect(screen.getByRole('heading', { name: 'My Team' })).toBeTruthy();
    expect(within(screen.getByTestId('my-team-stat-accounts')).getByText('3')).toBeTruthy();
    expect(within(screen.getByTestId('my-team-stat-acv')).getByText('$120,000')).toBeTruthy();
    expect(within(screen.getByTestId('my-team-stat-renewals')).getByText('4')).toBeTruthy();
    expect(within(screen.getByTestId('my-team-stat-tasks')).getByText('4 (1)')).toBeTruthy();
    const table = screen.getByTestId('my-team-table');
    expect(within(table).getByRole('rowheader', { name: 'Synthetic Rep 1' })).toBeTruthy();
    expect(within(table).getAllByRole('columnheader').length).toBe(9);
    expect(screen.getByTestId('my-team-rep-1').textContent).toContain('(1 overdue)');
    expect(screen.getByTestId('my-team-basis').textContent).toContain('not booked revenue');
  });

  it('keeps unknown amounts honest — never $0', async () => {
    apiMock.teamRollup.mockResolvedValue(resp({ team: summary({ pipeline: { ...summary().pipeline, acv: amount(5000, 'partial') } }) }));
    render(<MyTeamBlock />);
    await screen.findByTestId('my-team-summary');
    expect(within(screen.getByTestId('my-team-stat-acv')).getByText('$5,000 (partial)')).toBeTruthy();
    expect(screen.getByTestId('my-team-rep-acv-2').textContent).toBe('Not recorded');
  });

  it('shows an empty state when no reps report to the manager', async () => {
    apiMock.teamRollup.mockResolvedValue(resp({ reps: [], team: summary({ accounts: 0 }) }));
    render(<MyTeamBlock />);
    expect((await screen.findByTestId('my-team-empty')).textContent).toContain('No active reps report to you');
    expect(screen.queryByTestId('my-team-table')).toBeNull();
  });

  it('hides itself when the server refuses (403), e.g. a stale stored role', async () => {
    apiMock.teamRollup.mockRejectedValue(Object.assign(new Error('Manager role required'), { status: 403 }));
    const { container } = render(<MyTeamBlock />);
    await vi.waitFor(() => expect(container.innerHTML).toBe(''));
  });

  it('offers a retry after a failure', async () => {
    apiMock.teamRollup.mockRejectedValueOnce(Object.assign(new Error('boom'), { status: 500 })).mockResolvedValueOnce(resp());
    render(<MyTeamBlock />);
    const alert = await screen.findByTestId('my-team-error');
    fireEvent.click(within(alert).getByRole('button', { name: 'Retry' }));
    await screen.findByTestId('my-team-summary');
    expect(apiMock.teamRollup).toHaveBeenCalledTimes(2);
  });

  it('counts overdue renewals inside the 90-day figure', () => {
    expect(renewalsWithin90(summary())).toBe(4);
  });
});
