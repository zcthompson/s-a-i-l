/**
 * AccountTimelinePanel component tests (synthetic fixtures only).
 * Partial-mocks the api module (repo pattern: vi.hoisted + vi.mock factory).
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, cleanup, waitFor, act } from '@testing-library/react';
import { AccountTimelinePanel } from '../src/components/AccountTimelinePanel';
import type { AccountTimelineResponse, TimelineItem, TimelineQbr } from '../src/types/accountTimeline';

afterEach(() => cleanup());

const { apiMock } = vi.hoisted(() => ({ apiMock: { getAccountTimeline: vi.fn() } }));
vi.mock('../src/lib/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../lib/api')>();
  return { ...actual, api: { ...actual.api, ...apiMock } };
});

const qbr = (over: Partial<TimelineQbr> = {}): TimelineQbr => ({
  last_qbr_date: null, cadence_days: 90, next_qbr_due: null, state: 'not_recorded', days_until: null, ...over,
});

const item = (over: Partial<TimelineItem> = {}): TimelineItem => ({
  kind: 'note', id: 1, title: 'Synthetic note', detail: null, actor: null, timestamp: '2026-10-05',
  date_only: true, imported: false, source_ref: 'module=note&id=1', ...over,
});

const page = (over: Partial<AccountTimelineResponse> = {}): AccountTimelineResponse => ({
  customer_id: 5, qbr: qbr(), items: [item()], next_cursor: null, more: false, ...over,
});

function deferred<T>() {
  let resolve!: (v: T) => void;
  let reject!: (e: unknown) => void;
  const promise = new Promise<T>((res, rej) => { resolve = res; reject = rej; });
  return { promise, resolve, reject };
}

describe('AccountTimelinePanel', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    apiMock.getAccountTimeline.mockResolvedValue(page());
  });

  it.each([
    [qbr(), 'No QBR recorded'],
    [qbr({ state: 'current', last_qbr_date: '2026-09-01', next_qbr_due: '2026-11-30', days_until: 27 }),
      'Next QBR due 2026-11-30'],
    [qbr({ state: 'due_soon', last_qbr_date: '2026-08-10', next_qbr_due: '2026-11-08', days_until: 5 }),
      'QBR due 2026-11-08 (in 5 days)'],
    [qbr({ state: 'overdue', last_qbr_date: '2026-07-01', next_qbr_due: '2026-09-29', days_until: -35 }),
      'QBR overdue (35 days late)'],
  ])('renders the QBR header verbatim (%#)', async (state, text) => {
    apiMock.getAccountTimeline.mockResolvedValue(page({ qbr: state }));
    render(<AccountTimelinePanel customerId={5} />);
    expect((await screen.findByTestId('timeline-qbr')).textContent).toBe(text);
  });

  it('shows the loading state then the exact empty string', async () => {
    const d = deferred<AccountTimelineResponse>();
    apiMock.getAccountTimeline.mockReturnValue(d.promise);
    render(<AccountTimelinePanel customerId={5} />);
    expect(screen.getByText('Loading timeline…')).toBeTruthy();
    d.resolve(page({ items: [] }));
    expect((await screen.findByTestId('timeline-empty')).textContent).toBe('No recorded activity for this account.');
    expect(apiMock.getAccountTimeline).toHaveBeenCalledWith(5);
  });

  it('renders kind chip, title, detail, actor, timestamp and the imported tag', async () => {
    apiMock.getAccountTimeline.mockResolvedValue(page({ items: [
      item({ kind: 'activity', id: 7, title: 'Meeting', detail: 'Synthetic outcome', actor: 'synthetic_rep',
        timestamp: '2026-10-05T09:00:00+00:00', date_only: false, source_ref: 'module=activity&id=7' }),
      item({ kind: 'pipeline_import', id: 3, title: 'Pipeline import #3', detail: 'imported admin',
        timestamp: '2026-10-04T08:30:00+00:00', date_only: false, imported: true }),
    ] }));
    render(<AccountTimelinePanel customerId={5} />);
    const activity = await screen.findByTestId('timeline-item-activity-7');
    expect(activity.querySelector('[data-testid="timeline-kind"]')?.textContent).toBe('ACTIVITY');
    expect(activity.querySelector('[data-testid="timeline-title"]')?.textContent).toBe('Meeting');
    expect(activity.querySelector('[data-testid="timeline-detail"]')?.textContent).toBe('Synthetic outcome');
    expect(activity.querySelector('[data-testid="timeline-actor"]')?.textContent).toBe('by synthetic_rep');
    expect(activity.querySelector('[data-testid="timeline-when"]')?.textContent).toBe('2026-10-05 09:00 UTC');
    expect(activity.querySelector('[data-testid="timeline-imported"]')).toBeNull();
    const imported = screen.getByTestId('timeline-item-pipeline_import-3');
    expect(imported.querySelector('[data-testid="timeline-kind"]')?.textContent).toBe('PIPELINE_IMPORT');
    expect(imported.querySelector('[data-testid="timeline-imported"]')?.textContent).toBe('imported');
    expect(imported.querySelector('[data-testid="timeline-actor"]')).toBeNull();
  });

  it('passes the cursor through on "Show older items" and appends the page', async () => {
    apiMock.getAccountTimeline
      .mockResolvedValueOnce(page({ items: [item({ id: 9, title: 'Newest' })], next_cursor: 'CURSOR-1', more: true }));
    const older = deferred<AccountTimelineResponse>();
    apiMock.getAccountTimeline.mockReturnValueOnce(older.promise);
    render(<AccountTimelinePanel customerId={5} />);
    fireEvent.click(await screen.findByText('Show older items'));
    expect(apiMock.getAccountTimeline).toHaveBeenLastCalledWith(5, undefined, 'CURSOR-1');
    expect(screen.getByText('Loading…')).toBeTruthy();
    expect(screen.queryByText('Show older items')).toBeNull();
    older.resolve(page({ items: [item({ id: 2, title: 'Older' })] }));
    expect(await screen.findByText('Older')).toBeTruthy();
    expect(screen.getByText('Newest')).toBeTruthy();
    expect(screen.queryByText('Show older items')).toBeNull();
    expect(screen.queryByText('Loading…')).toBeNull();
  });

  it('shows the error state and retries', async () => {
    apiMock.getAccountTimeline.mockRejectedValueOnce(new Error('boom'));
    render(<AccountTimelinePanel customerId={5} />);
    expect(await screen.findByText('Timeline unavailable. Try again.')).toBeTruthy();
    apiMock.getAccountTimeline.mockResolvedValueOnce(page({ items: [item({ title: 'After retry' })] }));
    fireEvent.click(screen.getByText('Retry'));
    expect(await screen.findByText('After retry')).toBeTruthy();
    expect(apiMock.getAccountTimeline).toHaveBeenCalledTimes(2);
  });

  it('ignores a superseded response', async () => {
    const stale = deferred<AccountTimelineResponse>();
    const fresh = deferred<AccountTimelineResponse>();
    apiMock.getAccountTimeline.mockReturnValueOnce(stale.promise).mockReturnValueOnce(fresh.promise);
    const { rerender } = render(<AccountTimelinePanel customerId={5} />);
    rerender(<AccountTimelinePanel customerId={6} />);
    fresh.resolve(page({ customer_id: 6, items: [item({ title: 'Fresh account' })] }));
    expect(await screen.findByText('Fresh account')).toBeTruthy();
    await act(async () => { stale.resolve(page({ items: [item({ title: 'Stale account' })] })); });
    await waitFor(() => expect(screen.getByText('Fresh account')).toBeTruthy());
    expect(screen.queryByText('Stale account')).toBeNull();
  });

  it('ignores a superseded "Show older" page after a retry reload', async () => {
    apiMock.getAccountTimeline
      .mockResolvedValueOnce(page({ items: [item({ id: 9, title: 'First' })], next_cursor: 'C1', more: true }));
    const older = deferred<AccountTimelineResponse>();
    apiMock.getAccountTimeline.mockReturnValueOnce(older.promise);
    const { rerender } = render(<AccountTimelinePanel customerId={5} />);
    fireEvent.click(await screen.findByText('Show older items'));
    apiMock.getAccountTimeline.mockResolvedValueOnce(page({ customer_id: 6, items: [item({ title: 'Other account' })] }));
    rerender(<AccountTimelinePanel customerId={6} />);
    expect(await screen.findByText('Other account')).toBeTruthy();
    await act(async () => { older.resolve(page({ items: [item({ id: 1, title: 'Late older page' })] })); });
    expect(screen.getByText('Other account')).toBeTruthy();
    expect(screen.queryByText('Late older page')).toBeNull();
  });

  it('calls onSelect for items with an id, never for computed items', async () => {
    const onSelect = vi.fn();
    apiMock.getAccountTimeline.mockResolvedValue(page({ items: [
      item({ kind: 'qbr', id: null, title: 'QBR overdue', source_ref: null, date_only: true }),
      item({ kind: 'task', id: 4, title: 'Task open: Synthetic' }),
    ] }));
    render(<AccountTimelinePanel customerId={5} onSelect={onSelect} />);
    fireEvent.click(await screen.findByTestId('timeline-item-qbr-computed'));
    expect(onSelect).not.toHaveBeenCalled();
    fireEvent.click(screen.getByTestId('timeline-item-task-4'));
    expect(onSelect).toHaveBeenCalledWith('task', 4);
    expect(onSelect).toHaveBeenCalledTimes(1);
  });

  it('opens area destinations for older imports/snapshots and leaves rep imports inert (RF-07)', async () => {
    const onSelect = vi.fn();
    apiMock.getAccountTimeline.mockResolvedValue(page({ items: [
      item({ kind: 'pipeline_import', id: 7, title: 'Pipeline import #7', imported: true }),
      item({ kind: 'rvtools_import', id: 8, title: 'RVTools import #8', imported: true }),
      item({ kind: 'strategy_snapshot', id: 9, title: 'Strategy plan #2 published' }),
      item({ kind: 'membership', id: 10, title: 'Member added' }),
      item({ kind: 'rep_import', id: 11, title: 'Rep intelligence import #11', imported: true }),
    ] }));
    render(<AccountTimelinePanel customerId={5} onSelect={onSelect} />);
    const rep = await screen.findByTestId('timeline-item-rep_import-11');
    expect(rep.getAttribute('role')).toBeNull();
    expect(rep.getAttribute('tabindex')).toBeNull();
    fireEvent.click(rep);
    expect(onSelect).not.toHaveBeenCalled();
    fireEvent.click(screen.getByTestId('timeline-item-pipeline_import-7'));
    fireEvent.click(screen.getByTestId('timeline-item-rvtools_import-8'));
    fireEvent.keyDown(screen.getByTestId('timeline-item-strategy_snapshot-9'), { key: ' ' });
    fireEvent.keyDown(screen.getByTestId('timeline-item-membership-10'), { key: 'Enter' });
    expect(onSelect.mock.calls).toEqual([
      ['pipeline_import', 7], ['rvtools_import', 8], ['strategy_snapshot', 9], ['membership', 10],
    ]);
  });
});
