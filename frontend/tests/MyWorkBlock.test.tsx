/**
 * E3 — MyWorkBlock component tests (synthetic fixtures only).
 * Partial-mocks the api module (repo pattern: vi.hoisted + vi.mock factory).
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, cleanup, within } from '@testing-library/react';
import { MyWorkBlock } from '../src/components/MyWorkBlock';
import type { WorklistQbr, WorklistRenewal, WorklistResponse } from '../src/types/savedViews';
import type { MyTask } from '../src/types/engagement';

afterEach(() => cleanup());

const { apiMock } = vi.hoisted(() => ({ apiMock: { myWorklist: vi.fn() } }));
vi.mock('../src/lib/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../src/lib/api')>();
  return { ...actual, api: { ...actual.api, ...apiMock } };
});

const task = (over: Partial<MyTask> = {}): MyTask => ({
  id: 1, customer_id: 11, customer_name: 'Synthetic Co', title: 'Send follow-up', detail: null, assignee: 'synthetic_rep',
  due_at: null, due_date: '2026-11-10', status: 'open', completed_by: null, completed_at: null, source_type: null,
  source_id: null, source_key: null, created_by: 'synthetic_rep', created_at: '2026-10-01T00:00:00Z',
  updated_at: '2026-10-01T00:00:00Z', version: 1, evidence_note_count: 0, evidence_activity_count: 0, overdue: false, ...over,
} as MyTask);

const renewal = (over: Partial<WorklistRenewal> = {}): WorklistRenewal => ({
  customer_id: 21, customer_name: 'Synthetic Renewals', opportunity_name: 'Synthetic support renewal',
  end_date: '2026-11-30', bucket: 'within_30', acv_usd: 12000, tcv_usd: 36000, ...over,
});

const qbr = (over: Partial<WorklistQbr> = {}): WorklistQbr => ({
  customer_id: 31, customer_name: 'Synthetic QBR', state: 'due_soon', next_qbr_due: '2026-11-08', days_until: 5, ...over,
});

const resp = (over: Partial<WorklistResponse> = {}): WorklistResponse => ({
  generated_at: '2026-11-03T12:00:00Z', tasks: [], renewals: [], qbr: [], ...over,
});

describe('MyWorkBlock', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    apiMock.myWorklist.mockResolvedValue(resp());
  });

  it('loads once on mount and renders the three exact empty states', async () => {
    render(<MyWorkBlock />);
    expect(screen.getByText('Loading worklist…')).toBeTruthy();
    expect((await screen.findByTestId('my-work-tasks-empty')).textContent).toBe('No open tasks.');
    expect(screen.getByTestId('my-work-renewals-empty').textContent).toBe('No renewals due.');
    expect(screen.getByTestId('my-work-qbr-empty').textContent).toBe('No QBRs due.');
    expect(apiMock.myWorklist).toHaveBeenCalledTimes(1);
    expect(apiMock.myWorklist).toHaveBeenCalledWith();
  });

  it('tasks reuse the established due / overdue strings', async () => {
    apiMock.myWorklist.mockResolvedValue(resp({ tasks: [
      task(),
      task({ id: 2, title: 'Chase signature', due_date: '2026-10-20', overdue: true }),
      task({ id: 3, title: 'No date', due_date: null }),
    ] }));
    render(<MyWorkBlock />);
    const first = await screen.findByTestId('my-work-task-1');
    expect(first.textContent).toContain('Send follow-up');
    expect(first.textContent).toContain('Synthetic Co');
    expect(screen.getByTestId('my-work-task-due-1').textContent).toBe('Due: 2026-11-10');
    expect(screen.getByTestId('my-work-task-due-2').textContent).toBe('Due: 2026-10-20 (overdue)');
    expect(screen.getByTestId('my-work-task-due-3').textContent).toBe('Due: —');
  });

  it('renewals: opportunity, bucket chip, end date and honest money', async () => {
    apiMock.myWorklist.mockResolvedValue(resp({ renewals: [
      renewal(),
      renewal({ customer_id: 22, opportunity_name: null, end_date: null, bucket: 'unknown_date', acv_usd: null, tcv_usd: null }),
      renewal({ customer_id: 23, bucket: 'beyond_180', acv_usd: 0, tcv_usd: null }),
    ] }));
    render(<MyWorkBlock />);
    await screen.findByTestId('my-work-renewal-21');
    expect(screen.getByTestId('my-work-renewal-opp-21').textContent).toBe('Synthetic support renewal');
    expect(screen.getByTestId('my-work-renewal-bucket-21').textContent).toBe('30 days');
    expect(screen.getByTestId('my-work-renewal-end-21').textContent).toBe('Ends Nov 30, 2026');
    expect(screen.getByTestId('my-work-renewal-money-21').textContent).toBe('ACV $12,000 · TCV $36,000');
    // null → never $0
    expect(screen.getByTestId('my-work-renewal-opp-22').textContent).toBe('Opportunity not recorded');
    expect(screen.getByTestId('my-work-renewal-bucket-22').textContent).toBe('Unknown date');
    expect(screen.getByTestId('my-work-renewal-end-22').textContent).toBe('End date not recorded');
    const nullMoney = screen.getByTestId('my-work-renewal-money-22').textContent ?? '';
    expect(nullMoney).toBe('ACV Not recorded · TCV Not recorded');
    expect(nullMoney).not.toContain('$0');
    // a recorded 0 is a number; unlabelled buckets fall back to the raw key
    expect(screen.getByTestId('my-work-renewal-money-23').textContent).toBe('ACV $0 · TCV Not recorded');
    expect(screen.getByTestId('my-work-renewal-bucket-23').textContent).toBe('beyond_180');
  });

  it('QBR rows use the verbatim timeline strings', async () => {
    apiMock.myWorklist.mockResolvedValue(resp({ qbr: [
      qbr({ customer_id: 32, state: 'overdue', next_qbr_due: '2026-09-29', days_until: -35 }),
      qbr(),
    ] }));
    render(<MyWorkBlock />);
    expect((await screen.findByTestId('my-work-qbr-state-32')).textContent).toBe('QBR overdue (35 days late)');
    expect(screen.getByTestId('my-work-qbr-state-31').textContent).toBe('QBR due 2026-11-08 (in 5 days)');
    expect(screen.getByTestId('my-work-qbr-32').textContent).toContain('Synthetic QBR');
  });

  it('caps each section at 5 with an honest "Showing 5 of 8" line', async () => {
    apiMock.myWorklist.mockResolvedValue(resp({
      tasks: Array.from({ length: 8 }, (_, i) => task({ id: i + 1, title: `Task ${i + 1}` })),
      renewals: Array.from({ length: 6 }, (_, i) => renewal({ customer_id: 100 + i })),
      qbr: Array.from({ length: 5 }, (_, i) => qbr({ customer_id: 200 + i })),
    }));
    render(<MyWorkBlock />);
    const tasks = await screen.findByTestId('my-work-tasks');
    expect(within(tasks).getAllByRole('button')).toHaveLength(5);
    expect(screen.queryByTestId('my-work-task-6')).toBeNull();
    expect(screen.getByTestId('my-work-tasks-truncated').textContent).toBe('Showing 5 of 8');
    expect(screen.getByTestId('my-work-renewals-truncated').textContent).toBe('Showing 5 of 6');
    expect(within(screen.getByTestId('my-work-qbr')).getAllByRole('button')).toHaveLength(5);
    expect(screen.queryByTestId('my-work-qbr-truncated')).toBeNull();
  });

  it('labels server-truncated results as a lower bound', async () => {
    apiMock.myWorklist.mockResolvedValue(resp({
      tasks: Array.from({ length: 20 }, (_, i) => task({ id: i + 1 })),
      truncated: { tasks: true, renewals: false, qbr: false },
    }));
    render(<MyWorkBlock />);
    expect((await screen.findByTestId('my-work-tasks-truncated')).textContent).toBe('Showing 5 of at least 21');
  });

  it('error state is exact (no raw message) and Retry refetches', async () => {
    apiMock.myWorklist.mockRejectedValueOnce(new Error('500 internal'));
    render(<MyWorkBlock />);
    const err = await screen.findByTestId('my-work-error');
    expect(err.textContent).toContain('Worklist unavailable. Try again.');
    expect(err.textContent).not.toContain('500');
    apiMock.myWorklist.mockResolvedValue(resp({ tasks: [task()] }));
    fireEvent.click(within(err).getByRole('button', { name: 'Retry' }));
    expect(await screen.findByTestId('my-work-task-1')).toBeTruthy();
    expect(apiMock.myWorklist).toHaveBeenCalledTimes(2);
  });

  it('items are buttons that call onOpenCustomer with the customer id', async () => {
    apiMock.myWorklist.mockResolvedValue(resp({ tasks: [task()], renewals: [renewal()], qbr: [qbr()] }));
    const onOpen = vi.fn();
    render(<MyWorkBlock onOpenCustomer={onOpen} />);
    fireEvent.click(await screen.findByRole('button', { name: 'Open account Synthetic Co for task Send follow-up' }));
    fireEvent.click(screen.getByRole('button', { name: 'Open account Synthetic Renewals renewal' }));
    fireEvent.click(screen.getByRole('button', { name: 'Open account Synthetic QBR QBR' }));
    expect(onOpen.mock.calls).toEqual([[11], [21], [31]]);
  });

  it('without onOpenCustomer the item buttons are disabled (no dead clicks)', async () => {
    apiMock.myWorklist.mockResolvedValue(resp({ tasks: [task()] }));
    render(<MyWorkBlock />);
    expect(((await screen.findByTestId('my-work-task-1')) as HTMLButtonElement).disabled).toBe(true);
  });
});
