/**
 * H7 — AccountStrategyPanel (synthetic fixtures; api mocked with the vi.hoisted
 * pattern used by the H4/H6 panel tests). Covers: empty-state prefill, recorded
 * plan verbatim, save CAS version, verbatim 409, read-only role, links, and the
 * publish → list → view → restore snapshot flow.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, cleanup, waitFor } from '@testing-library/react';
import { AccountStrategyPanel } from '../src/components/AccountStrategyPanel';

afterEach(() => cleanup());

const CONFLICT = 'Strategy changed since you loaded it; reload and retry';
const HEADER = 'Derived from recorded evidence — for review. Nothing is applied automatically.';

const { apiMock } = vi.hoisted(() => ({
  apiMock: {
    getAccountStrategy: vi.fn(),
    updateAccountStrategy: vi.fn(),
    updateStrategyLinks: vi.fn(),
    publishStrategySnapshot: vi.fn(),
    listStrategySnapshots: vi.fn(),
    getStrategySnapshot: vi.fn(),
    restoreStrategySnapshot: vi.fn(),
    listTasks: vi.fn(),
  },
}));
vi.mock('../src/lib/api', () => ({ api: apiMock }));

const sug = (text: string, source = 'pipeline import') => ({ text, source });
const emptySuggestions = () => ({
  calculation_version: 'strategy-suggestions/1', as_of: '2026-10-28T12:00:00+00:00', reference_date: '2026-10-28',
  objectives: [], desired_outcomes: [], risks: [], plays: [], discovery_gaps: [], next_actions: [],
});

const plan = (over: Record<string, unknown> = {}) => ({
  id: 7, objectives: null, desired_outcomes: null, risks: null, plays: null, discovery_gaps: null,
  version: 3, created_by: 'zt', created_at: '2026-10-01T00:00:00+00:00', updated_by: 'zt', updated_at: '2026-10-02T00:00:00+00:00',
  links: { tasks: [], contacts: [], notes: [] },
  ...over,
});

const view = (over: Record<string, unknown> = {}) => ({
  plan: null,
  suggestions: emptySuggestions(),
  snapshots: { count: 0, latest: null },
  ...over,
});

const snap = (over: Record<string, unknown> = {}) => ({
  id: 41, plan_number: 1, note: 'first', published_by: 'zt', published_at: '2026-10-20T09:00:00+00:00', ...over,
});

beforeEach(() => {
  vi.clearAllMocks();
  apiMock.getAccountStrategy.mockResolvedValue(view());
  apiMock.listStrategySnapshots.mockResolvedValue({ snapshots: [] });
  apiMock.listTasks.mockResolvedValue([]);
  apiMock.updateAccountStrategy.mockResolvedValue(plan());
  apiMock.updateStrategyLinks.mockResolvedValue({ tasks: [], contacts: [], notes: [] });
  apiMock.publishStrategySnapshot.mockResolvedValue(snap());
  apiMock.getStrategySnapshot.mockResolvedValue({
    ...snap(),
    content: { objectives: 'Grow', desired_outcomes: null, risks: 'Renewal risk\n  line two', plays: null, discovery_gaps: null, version: 2 },
  });
  apiMock.restoreStrategySnapshot.mockResolvedValue(plan({ objectives: 'Grow', version: 4 }));
});

describe('AccountStrategyPanel', () => {
  it('empty state (no plan): prefills empty fields from suggestions and marks each with a chip', async () => {
    apiMock.getAccountStrategy.mockResolvedValue(view({
      suggestions: {
        ...emptySuggestions(),
        objectives: [sug('Advance the recorded partner-pipeline opportunities (2 line(s))'), sug('second objective')],
        risks: [sug('Renewal 77 (Acme) recorded end date not recorded')],
      },
    }));
    render(<AccountStrategyPanel customerId={5} userRole="owner" />);

    const objectives = await screen.findByTestId('account-strategy-field-objectives') as HTMLTextAreaElement;
    expect(objectives.value).toBe('Advance the recorded partner-pipeline opportunities (2 line(s))');
    expect((screen.getByTestId('account-strategy-field-risks') as HTMLTextAreaElement).value).toBe('Renewal 77 (Acme) recorded end date not recorded');
    expect((screen.getByTestId('account-strategy-field-plays') as HTMLTextAreaElement).value).toBe('');
    expect(screen.getByTestId('account-strategy-suggested-objectives').textContent).toBe('suggested');
    expect(screen.getByTestId('account-strategy-suggested-risks')).toBeTruthy();
    expect(screen.queryByTestId('account-strategy-suggested-plays')).toBeNull();
    expect(screen.getByTestId('account-strategy-empty')).toBeTruthy();
    expect(screen.getByTestId('account-strategy-suggestions').textContent).toContain(HEADER);
  });

  it('recorded plan renders verbatim and is never prefilled over; only null fields get suggestions', async () => {
    apiMock.getAccountStrategy.mockResolvedValue(view({
      plan: plan({ objectives: 'Recorded objective', risks: '  ' }),
      suggestions: { ...emptySuggestions(), objectives: [sug('should not appear')], risks: [sug('suggested risk')] },
    }));
    render(<AccountStrategyPanel customerId={5} userRole="member" />);

    const objectives = await screen.findByTestId('account-strategy-field-objectives') as HTMLTextAreaElement;
    expect(objectives.value).toBe('Recorded objective');
    expect(screen.queryByTestId('account-strategy-suggested-objectives')).toBeNull();
    // Whitespace-only recorded text counts as empty → the suggestion fills it.
    expect((screen.getByTestId('account-strategy-field-risks') as HTMLTextAreaElement).value).toBe('suggested risk');
    expect(screen.getByTestId('account-strategy-suggested-risks')).toBeTruthy();
    expect(screen.getByTestId('account-strategy-plan').textContent).toContain('Version 3');
  });

  it('save sends expected_version from the latest GET; blank text is sent as null', async () => {
    apiMock.getAccountStrategy.mockResolvedValue(view({ plan: plan({ objectives: 'old', version: 3 }) }));
    render(<AccountStrategyPanel customerId={5} userRole="owner" />);

    fireEvent.change(await screen.findByTestId('account-strategy-field-objectives'), { target: { value: 'new objective' } });
    fireEvent.change(screen.getByTestId('account-strategy-field-plays'), { target: { value: '   ' } });
    fireEvent.click(screen.getByTestId('account-strategy-save'));

    await waitFor(() => expect(apiMock.updateAccountStrategy).toHaveBeenCalledTimes(1));
    expect(apiMock.updateAccountStrategy).toHaveBeenCalledWith(5, {
      objectives: 'new objective', desired_outcomes: null, risks: null, plays: null, discovery_gaps: null, expected_version: 3,
    });
  });

  it('save with no plan sends expected_version 0', async () => {
    render(<AccountStrategyPanel customerId={5} userRole="owner" />);
    fireEvent.change(await screen.findByTestId('account-strategy-field-risks'), { target: { value: 'a risk' } });
    fireEvent.click(screen.getByTestId('account-strategy-save'));
    await waitFor(() => expect(apiMock.updateAccountStrategy).toHaveBeenCalledTimes(1));
    expect(apiMock.updateAccountStrategy.mock.calls[0][1].expected_version).toBe(0);
  });

  it('409 conflict renders the server message verbatim inline (role=status)', async () => {
    apiMock.getAccountStrategy.mockResolvedValue(view({ plan: plan() }));
    apiMock.updateAccountStrategy.mockRejectedValue(Object.assign(new Error(CONFLICT), { status: 409 }));
    render(<AccountStrategyPanel customerId={5} userRole="owner" />);

    fireEvent.change(await screen.findByTestId('account-strategy-field-plays'), { target: { value: 'play' } });
    fireEvent.click(screen.getByTestId('account-strategy-save'));

    const err = await screen.findByTestId('account-strategy-error');
    expect(err.getAttribute('role')).toBe('status');
    expect(err.textContent).toBe(CONFLICT);
  });

  it('editing a prefilled field clears its suggested chip', async () => {
    apiMock.getAccountStrategy.mockResolvedValue(view({
      suggestions: { ...emptySuggestions(), plays: [sug('Follow through on the 2 open task(s)')] },
    }));
    render(<AccountStrategyPanel customerId={5} userRole="owner" />);
    await screen.findByTestId('account-strategy-suggested-plays');
    fireEvent.change(screen.getByTestId('account-strategy-field-plays'), { target: { value: 'my play' } });
    expect(screen.queryByTestId('account-strategy-suggested-plays')).toBeNull();
  });

  it('auditor (read-only): no save, no publish/restore, no link checkboxes, no prefill', async () => {
    apiMock.getAccountStrategy.mockResolvedValue(view({
      plan: plan({ objectives: 'Recorded' }),
      suggestions: { ...emptySuggestions(), risks: [sug('suggested risk')] },
    }));
    apiMock.listStrategySnapshots.mockResolvedValue({ snapshots: [snap()] });
    render(<AccountStrategyPanel customerId={5} userRole="auditor" />);

    const risks = await screen.findByTestId('account-strategy-field-risks') as HTMLTextAreaElement;
    expect(risks.readOnly).toBe(true);
    expect(risks.value).toBe('');
    expect(screen.queryByTestId('account-strategy-suggested-risks')).toBeNull();
    expect(screen.queryByTestId('account-strategy-save')).toBeNull();
    expect(screen.queryByTestId('account-strategy-snapshot-publish')).toBeNull();
    expect(screen.queryByTestId('account-strategy-snapshot-note')).toBeNull();
    expect(screen.queryByTestId('account-strategy-restore-1')).toBeNull();
    expect(screen.getByTestId('account-strategy-view-1')).toBeTruthy();
    expect(apiMock.listTasks).not.toHaveBeenCalled();
  });

  it('links: toggling a task sends the full set; unlinking a contact drops only that id', async () => {
    apiMock.getAccountStrategy.mockResolvedValue(view({
      plan: plan({
        links: {
          tasks: [{ task_id: 9, title: 'Call sponsor', status: 'open' }],
          contacts: [{ contact_id: 3, display_name: 'Pat Example' }, { contact_id: 4, display_name: 'Sam Two' }],
          notes: [],
        },
      }),
    }));
    apiMock.listTasks.mockResolvedValue([
      { id: 9, title: 'Call sponsor', status: 'open', due_date: '2026-11-01', due_at: null },
      { id: 12, title: 'Send proposal', status: 'in_progress', due_date: null, due_at: null },
      { id: 13, title: 'Done thing', status: 'completed', due_date: null, due_at: null },
    ]);
    render(<AccountStrategyPanel customerId={5} userRole="owner" />);

    const box12 = await screen.findByTestId('account-strategy-link-task-12') as HTMLInputElement;
    expect(box12.checked).toBe(false);
    expect(screen.getByTestId('account-strategy-link-task-9').closest('label')!.textContent).toContain('Call sponsor');
    expect(screen.queryByTestId('account-strategy-link-task-13')).toBeNull();

    fireEvent.click(box12);
    await waitFor(() => expect(apiMock.updateStrategyLinks).toHaveBeenCalledTimes(1));
    expect(apiMock.updateStrategyLinks).toHaveBeenLastCalledWith(5, { task_ids: [9, 12], contact_ids: [3, 4], note_ids: [] });

    fireEvent.click(screen.getByTestId('account-strategy-unlink-contact-3'));
    await waitFor(() => expect(apiMock.updateStrategyLinks).toHaveBeenCalledTimes(2));
    expect(apiMock.updateStrategyLinks).toHaveBeenLastCalledWith(5, { task_ids: [9], contact_ids: [4], note_ids: [] });
  });

  it('snapshots: publish → refresh list → view verbatim → restore with confirm and the current version', async () => {
    apiMock.getAccountStrategy.mockResolvedValue(view({ plan: plan({ version: 2, objectives: 'Grow' }) }));
    apiMock.listStrategySnapshots
      .mockResolvedValueOnce({ snapshots: [snap()] })
      .mockResolvedValue({ snapshots: [snap({ id: 42, plan_number: 2, note: 'second' }), snap()] });
    const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(true);
    render(<AccountStrategyPanel customerId={5} userRole="owner" />);

    fireEvent.change(await screen.findByTestId('account-strategy-snapshot-note'), { target: { value: 'second' } });
    fireEvent.click(screen.getByTestId('account-strategy-snapshot-publish'));
    await waitFor(() => expect(apiMock.publishStrategySnapshot).toHaveBeenCalledWith(5, { note: 'second' }));
    const row2 = await screen.findByTestId('account-strategy-snapshot-2');
    expect(row2.textContent).toContain('second');

    fireEvent.click(screen.getByTestId('account-strategy-view-1'));
    const content = await screen.findByTestId('account-strategy-view-content-1');
    expect(apiMock.getStrategySnapshot).toHaveBeenCalledWith(41);
    expect(content.textContent).toContain('Grow');
    expect(content.textContent).toContain('not recorded');
    expect(content.textContent).toContain('Renewal risk\n  line two');

    fireEvent.click(screen.getByTestId('account-strategy-restore-1'));
    await waitFor(() => expect(apiMock.restoreStrategySnapshot).toHaveBeenCalledWith(41, 2));
    expect(confirmSpy).toHaveBeenCalledTimes(1);
  });

  it('restore is not sent when the confirm is cancelled; a 422 restore error shows verbatim', async () => {
    apiMock.getAccountStrategy.mockResolvedValue(view({ plan: null }));
    apiMock.listStrategySnapshots.mockResolvedValue({ snapshots: [snap()] });
    const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValueOnce(false).mockReturnValueOnce(true);
    apiMock.restoreStrategySnapshot.mockRejectedValue(Object.assign(new Error(CONFLICT), { status: 409 }));
    render(<AccountStrategyPanel customerId={5} userRole="member" />);

    fireEvent.click(await screen.findByTestId('account-strategy-restore-1'));
    expect(apiMock.restoreStrategySnapshot).not.toHaveBeenCalled();

    fireEvent.click(screen.getByTestId('account-strategy-restore-1'));
    await waitFor(() => expect(apiMock.restoreStrategySnapshot).toHaveBeenCalledWith(41, 0));
    expect((await screen.findByTestId('account-strategy-error')).textContent).toBe(CONFLICT);
    expect(confirmSpy).toHaveBeenCalledTimes(2);
  });
});
