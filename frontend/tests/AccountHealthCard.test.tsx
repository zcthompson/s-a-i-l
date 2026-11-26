/**
 * AccountHealthCard component tests (synthetic fixtures only).
 * Partial-mocks the api module (repo pattern: vi.hoisted + vi.mock factory),
 * so the real module need not export getCustomerHealth for these to run.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, cleanup, waitFor, act } from '@testing-library/react';
import { AccountHealthCard } from '../src/components/AccountHealthCard';

afterEach(() => cleanup());

const { apiMock } = vi.hoisted(() => ({ apiMock: { getCustomerHealth: vi.fn() } }));
vi.mock('../src/lib/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../src/lib/api')>();
  return { ...actual, api: { ...actual.api, ...apiMock } };
});

const ENG_BASIS = 'Latest qualified activity or note (synthetic basis).';
const REN_BASIS = 'Vendor-reported renewal lines from the latest pipeline snapshot.';
const TASK_BASIS = 'Open account tasks; overdue = due date before today.';

const populated = () => ({
  customer_id: 7,
  calc_version: 'account-health/1',
  as_of: '2026-11-04T09:15:30.123456Z',
  components: {
    engagement: { last_contacted: '2026-10-20', days_since: 15, basis: ENG_BASIS },
    renewals: {
      snapshot: { id: 3, imported_at: '2026-11-01T00:00:00Z' },
      counts: { overdue: 1, within_30: 2, unknown_date: 3, beyond_180: 4 },
      exposure: { acv: 125000, tcv: null, coverage: 'partial' },
      basis: REN_BASIS,
    },
    buying_coverage: {
      contacts_recorded: 4,
      economic_buyer_recorded: false,
      champion_recorded: true,
      roles: { champion: 1, technical_buyer: 2, mystery_role: 1 },
      gaps: ['No economic buyer recorded.', 'No decision maker recorded.'],
    },
    tasks: { open: 5, in_progress: 2, overdue: 1, basis: TASK_BASIS },
    eol: {
      dated_count: 7,
      items: [1, 2, 3, 4, 5, 6].map((i) => ({
        id: i,
        name: `Synthetic Platform ${i}`,
        vendor: i === 1 ? 'Synthetic Vendor' : null,
        end_of_support_date: '2027-01-31',
        eol_source: i === 1 ? 'vendor lifecycle page' : null,
        lifecycle_state: 'eol_announced',
        business_criticality: i === 1 ? 'critical' : null,
      })),
    },
    data_freshness: {
      pipeline_import: '2026-11-01T08:00:00.987Z',
      rep_import: null,
      rvtools_import: '2026-09-15T10:00:00Z',
      latest_note: '2026-10-30',
      latest_activity: null,
    },
  },
});

const empty = () => ({
  customer_id: 8,
  calc_version: 'account-health/1',
  as_of: '2026-11-04T09:15:30Z',
  components: {
    engagement: { last_contacted: null, days_since: null, basis: ENG_BASIS },
    renewals: { snapshot: null, counts: {}, exposure: { acv: null, tcv: null, coverage: 'no_data' }, basis: REN_BASIS },
    buying_coverage: { contacts_recorded: 0, economic_buyer_recorded: false, champion_recorded: false, roles: {}, gaps: ['No contacts recorded.'] },
    tasks: { open: 0, in_progress: 0, overdue: 0, basis: TASK_BASIS },
    eol: { dated_count: 0, items: [] },
    data_freshness: { pipeline_import: null, rep_import: null, rvtools_import: null, latest_note: null, latest_activity: null },
  },
});

const text = (id: string) => screen.getByTestId(id).textContent;

describe('AccountHealthCard', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    apiMock.getCustomerHealth.mockResolvedValue(populated());
  });

  it('fetches once on mount with the customer id and shows loading first', async () => {
    render(<AccountHealthCard customerId={7} />);
    expect(screen.getByText('Loading account health…')).toBeTruthy();
    await screen.findByTestId('account-health-engagement');
    expect(apiMock.getCustomerHealth).toHaveBeenCalledTimes(1);
    expect(apiMock.getCustomerHealth).toHaveBeenCalledWith(7);
  });

  it('renders all six labelled components with the pinned populated strings', async () => {
    render(<AccountHealthCard customerId={7} />);
    await screen.findByTestId('account-health-engagement');
    for (const label of ['Engagement', 'Renewals', 'Buying coverage', 'Tasks', 'End-of-support', 'Data freshness']) {
      expect(screen.getByRole('region', { name: label })).toBeTruthy();
    }
    // Engagement
    expect(text('account-health-engagement-line')).toBe('Last meaningful interaction Oct 20, 2026 (15 days ago)');
    expect(text('account-health-engagement-basis')).toBe(ENG_BASIS);
    // Renewals — reused bucket labels; unlabelled keys fall back to the key
    expect(text('account-health-renewals-count-overdue')).toBe('Overdue: 1');
    expect(text('account-health-renewals-count-within_30')).toBe('30 days: 2');
    expect(text('account-health-renewals-count-unknown_date')).toBe('Unknown date: 3');
    expect(text('account-health-renewals-count-beyond_180')).toBe('beyond_180: 4');
    expect(text('account-health-renewals-exposure')).toContain('ACV $125,000 · TCV Not recorded');
    expect(text('account-health-renewals-exposure')).toContain('Partial sum — unknown amounts excluded');
    expect(text('account-health-renewals-basis')).toBe(REN_BASIS);
    expect(screen.queryByTestId('account-health-renewals-empty')).toBeNull();
    // Buying coverage
    expect(text('account-health-buying-contacts')).toBe('4 contacts');
    expect(text('account-health-buying-role-champion')).toBe('Champion: 1');
    expect(text('account-health-buying-role-technical_buyer')).toBe('Technical buyer: 2');
    expect(text('account-health-buying-role-mystery_role')).toBe('mystery_role: 1');
    expect(screen.getAllByTestId('account-health-buying-gap').map((e) => e.textContent))
      .toEqual(['No economic buyer recorded.', 'No decision maker recorded.']);
    // Tasks
    expect(text('account-health-tasks-line')).toBe('5 open · 2 in progress · 1 overdue');
    expect(text('account-health-tasks-basis')).toBe(TASK_BASIS);
    // End-of-support — capped at 5 items; source never invented
    expect(text('account-health-eol-count')).toBe('7 dated end-of-support records:');
    expect(screen.getByTestId('account-health-eol-item-1').textContent)
      .toBe('Synthetic Platform 1 (Synthetic Vendor)Jan 31, 2027source: vendor lifecycle pagecritical');
    expect(screen.getByTestId('account-health-eol-item-2').textContent)
      .toBe('Synthetic Platform 2Jan 31, 2027source: not recorded');
    expect(screen.getByTestId('account-health-eol-item-5')).toBeTruthy();
    expect(screen.queryByTestId('account-health-eol-item-6')).toBeNull();
    // Data freshness
    expect(text('account-health-freshness-pipeline_import')).toContain('Pipeline import: Nov 1, 2026, 8:00 AM UTC');
    expect(text('account-health-freshness-rep_import')).toBe('Rep intelligence: not recorded');
    expect(text('account-health-freshness-rvtools_import')).toContain('RVTools: Sep 15, 2026, 10:00 AM UTC');
    expect(text('account-health-freshness-latest_note')).toContain('Latest note: Oct 30, 2026');
    expect(text('account-health-freshness-latest_activity')).toBe('Latest activity: not recorded');
  });

  it('renders the meta line with sub-second precision stripped', async () => {
    render(<AccountHealthCard customerId={7} />);
    expect((await screen.findByTestId('account-health-meta')).textContent)
      .toBe('account-health/1 · as of 2026-11-04T09:15:30Z');
  });

  it('empty account: every component renders its honest empty state', async () => {
    apiMock.getCustomerHealth.mockResolvedValue(empty());
    render(<AccountHealthCard customerId={8} />);
    await screen.findByTestId('account-health-engagement');
    expect(text('account-health-engagement-line')).toBe('No meaningful interaction recorded');
    expect(text('account-health-engagement-basis')).toBe(ENG_BASIS);
    expect(text('account-health-renewals-empty')).toBe('No pipeline data recorded.');
    expect(screen.queryByTestId('account-health-renewals-counts')).toBeNull();
    expect(text('account-health-renewals-exposure')).toBe('Not recorded');
    expect(text('account-health-buying-contacts')).toBe('0 contacts');
    expect(screen.queryByTestId('account-health-buying-roles')).toBeNull();
    expect(screen.getAllByTestId('account-health-buying-gap').map((e) => e.textContent)).toEqual(['No contacts recorded.']);
    expect(text('account-health-tasks-line')).toBe('0 open · 0 in progress · 0 overdue');
    expect(text('account-health-eol-empty')).toBe('No dated end-of-support records.');
    for (const label of ['Pipeline import', 'Rep intelligence', 'RVTools', 'Latest note', 'Latest activity']) {
      expect(screen.getByText(`${label}: not recorded`)).toBeTruthy();
    }
    expect(text('account-health-meta')).toBe('account-health/1 · as of 2026-11-04T09:15:30Z');
  });

  it('labels a complete recorded zero without a partial warning', async () => {
    const value = populated();
    value.components.renewals.exposure = { acv: 0, tcv: 0, coverage: 'complete' };
    apiMock.getCustomerHealth.mockResolvedValue(value);
    render(<AccountHealthCard customerId={7} />);
    await screen.findByTestId('account-health-renewals-exposure');
    expect(text('account-health-renewals-exposure')).toContain('ACV $0 · TCV $0');
    expect(text('account-health-renewals-exposure')).not.toContain('Partial sum');
  });

  it('never renders a null amount as $0', async () => {
    apiMock.getCustomerHealth.mockResolvedValue(empty());
    render(<AccountHealthCard customerId={8} />);
    await screen.findByTestId('account-health-renewals-exposure');
    expect(screen.getByTestId('account-health').textContent).not.toContain('$0');
  });

  it('never renders a composite score / single health number', async () => {
    for (const fixture of [populated(), empty()]) {
      apiMock.getCustomerHealth.mockResolvedValue({ ...fixture, customer_id: 7 });
      const { unmount } = render(<AccountHealthCard customerId={7} />);
      await screen.findByTestId('account-health-engagement');
      const all = Array.from(screen.getByTestId('account-health').querySelectorAll('*'));
      for (const el of all) {
        expect(/^Health[: ]?\d/i.test((el.textContent || '').trim())).toBe(false);
        expect(/score/i.test(el.textContent || '')).toBe(false);
      }
      unmount();
    }
  });

  it('does not crash on missing/null components and renders the honest empty strings', async () => {
    apiMock.getCustomerHealth.mockResolvedValue({
      customer_id: 9, calc_version: 'account-health/1', as_of: '2026-11-04T00:00:00Z',
      components: { engagement: null, renewals: null, buying_coverage: null, tasks: null, eol: null, data_freshness: null },
    });
    render(<AccountHealthCard customerId={9} />);
    await screen.findByTestId('account-health-engagement');
    for (const id of ['engagement', 'renewals', 'buying', 'tasks', 'eol', 'freshness']) {
      expect(text(`account-health-${id}`)).toContain('Unavailable');
    }
    expect(screen.queryByText('0 contacts')).toBeNull();
    cleanup();
    apiMock.getCustomerHealth.mockResolvedValue({ customer_id: 9 });
    render(<AccountHealthCard customerId={9} />);
    await screen.findByTestId('account-health-engagement');
    expect(screen.queryByTestId('account-health-meta')).toBeNull();
    expect(text('account-health-eol')).toContain('Unavailable');
  });

  it('does not invent values when fields are missing from present components', async () => {
    apiMock.getCustomerHealth.mockResolvedValue({ customer_id: 9, components: { engagement: {}, renewals: {}, buying_coverage: {}, tasks: {}, eol: {}, data_freshness: {} } });
    render(<AccountHealthCard customerId={9} />);
    expect(await screen.findByText('Interaction data unavailable')).toBeTruthy();
    expect(text('account-health-tasks-line')).toContain('unavailable open');
    expect(text('account-health-buying-contacts')).toContain('unavailable');
    expect(screen.getByText('Count unavailable.')).toBeTruthy();
    expect(text('account-health-freshness-latest_activity')).toContain('unavailable');
  });

  it('rejects a health response for a different customer', async () => {
    apiMock.getCustomerHealth.mockResolvedValue(populated());
    render(<AccountHealthCard customerId={999} />);
    expect((await screen.findByRole('alert')).textContent).toContain('Account health unavailable');
    expect(screen.queryByTestId('account-health-engagement')).toBeNull();
  });

  it('error shows the retry affordance and retry refetches', async () => {
    apiMock.getCustomerHealth.mockRejectedValueOnce(new Error('boom'));
    render(<AccountHealthCard customerId={7} />);
    const err = await screen.findByTestId('account-health-error');
    expect(err.textContent).toContain('Account health unavailable. Try again.');
    fireEvent.click(screen.getByRole('button', { name: 'Retry' }));
    await screen.findByTestId('account-health-engagement');
    expect(screen.queryByTestId('account-health-error')).toBeNull();
    expect(apiMock.getCustomerHealth).toHaveBeenCalledTimes(2);
  });

  it('ignores a superseded response when the customer changes', async () => {
    let resolveFirst: (v: unknown) => void = () => {};
    apiMock.getCustomerHealth
      .mockImplementationOnce(() => new Promise((r) => { resolveFirst = r; }))
      .mockResolvedValueOnce(empty());
    const { rerender } = render(<AccountHealthCard customerId={7} />);
    await waitFor(() => expect(apiMock.getCustomerHealth).toHaveBeenCalledTimes(1));
    rerender(<AccountHealthCard customerId={8} />);
    await screen.findByTestId('account-health-eol-empty');
    await act(async () => { resolveFirst(populated()); });
    expect(text('account-health-engagement-line')).toBe('No meaningful interaction recorded');
    expect(screen.queryByTestId('account-health-eol-count')).toBeNull();
    expect(apiMock.getCustomerHealth).toHaveBeenNthCalledWith(1, 7);
    expect(apiMock.getCustomerHealth).toHaveBeenNthCalledWith(2, 8);
  });
});

it('connects each health signal to its owning customer workflow', async () => {
  apiMock.getCustomerHealth.mockResolvedValue(populated());
  const navigate = vi.fn();
  render(<AccountHealthCard customerId={7} onNavigate={navigate} />);
  for (const [label, area] of [['Review renewals', 'renewals-due'], ['Review buying contacts', 'buying-gaps'], ['View overdue follow-ups', 'tasks-overdue']]) {
    fireEvent.click(await screen.findByRole('button', { name: label }));
    expect(navigate).toHaveBeenLastCalledWith(area);
  }
});
