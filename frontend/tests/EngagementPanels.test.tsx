/**
 * ActivitiesPanel / TasksPanel / PromoteTaskButton / MyTasksBlock
 * (synthetic fixtures; api mocked with the vi.hoisted pattern).
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, cleanup, waitFor, createEvent } from '@testing-library/react';
import { ActivitiesPanel } from '../src/components/ActivitiesPanel';
import { TasksPanel } from '../src/components/TasksPanel';
import { PromoteTaskButton } from '../src/components/PromoteTaskButton';
import { MyTasksBlock } from '../src/components/MyTasksBlock';

afterEach(() => cleanup());

const ts = '2026-10-01T00:00:00Z';
const CONFLICT = 'Task changed since you loaded it; reload and retry';

const { apiMock } = vi.hoisted(() => ({
  apiMock: {
    listActivities: vi.fn(), createActivity: vi.fn(), deleteActivity: vi.fn(),
    listCustomerContacts: vi.fn(),
    getTask: vi.fn(), listTasks: vi.fn(), createTask: vi.fn(), updateTask: vi.fn(), deleteTask: vi.fn(),
    promoteTask: vi.fn(), myTasks: vi.fn(),
  },
}));
vi.mock('../src/lib/api', () => ({ api: apiMock }));
vi.mock('../src/lib/auth', () => ({ getAuthUsername: () => 'rep1' }));

const activity = (over: Record<string, unknown> = {}) => ({
  id: 1, customer_id: 5, type: 'call', occurred_at: null, occurred_date: '2026-10-01', actor: 'rep1',
  source: 'discovery', outcome: 'Agreed to a demo', created_by: 'rep1', created_at: ts, updated_at: ts,
  attendees: [{ contact_id: 9, display_name: 'Pat Example' }], ...over,
});
const task = (over: Record<string, unknown> = {}) => ({
  id: 3, customer_id: 5, title: 'Send quote', detail: null, assignee: 'rep1', due_at: null, due_date: '2026-10-20',
  status: 'open', completed_by: null, completed_at: null, source_type: null, source_id: null, source_key: null,
  created_by: 'mgr', created_at: ts, updated_at: ts, version: 4, evidence_note_count: 2, evidence_activity_count: 1,
  overdue: true, due_soon: false, needs_reassignment: false, ...over,
});

beforeEach(() => {
  vi.clearAllMocks();
  apiMock.listActivities.mockResolvedValue([activity()]);
  apiMock.createActivity.mockResolvedValue(activity());
  apiMock.deleteActivity.mockResolvedValue(undefined);
  apiMock.listCustomerContacts.mockResolvedValue([{ id: 9, display_name: 'Pat Example' }]);
  apiMock.listTasks.mockResolvedValue([task()]);
  apiMock.updateTask.mockResolvedValue(task());
  apiMock.createTask.mockResolvedValue(task());
  apiMock.deleteTask.mockResolvedValue(undefined);
  apiMock.promoteTask.mockResolvedValue({ created: true, task: task() });
  apiMock.myTasks.mockResolvedValue([]);
});

describe('ActivitiesPanel', () => {
  it('renders type, occurred date-only, actor, attendees, source, outcome', async () => {
    render(<ActivitiesPanel customerId={5} userRole="member" />);
    expect((await screen.findByTestId('activity-type-1')).textContent).toBe('Call');
    expect(screen.getByTestId('activity-occurred-1').textContent).toBe('2026-10-01');
    expect(screen.getByTestId('activity-attendees-1').textContent).toContain('Pat Example');
    expect(screen.getByText('Agreed to a demo')).toBeTruthy();
    expect(screen.getByText('by rep1')).toBeTruthy();
  });

  it('enforces exactly-one date client-side (neither and both are refused without a call)', async () => {
    render(<ActivitiesPanel customerId={5} userRole="member" />);
    await screen.findByTestId('activity-row-1');
    fireEvent.click(screen.getByLabelText('Add activity'));
    fireEvent.click(screen.getByLabelText('Save activity'));
    expect(screen.getByTestId('activity-save-error')).toBeTruthy();
    fireEvent.change(screen.getByLabelText('Occurred time'), { target: { value: '2026-10-02T10:30' } });
    fireEvent.change(screen.getByLabelText('Occurred date'), { target: { value: '2026-10-02' } });
    fireEvent.click(screen.getByLabelText('Save activity'));
    expect(apiMock.createActivity).not.toHaveBeenCalled();
  });

  it('submits actor = current user with a single date and selected attendees', async () => {
    render(<ActivitiesPanel customerId={5} userRole="member" />);
    await screen.findByTestId('activity-row-1');
    fireEvent.click(screen.getByLabelText('Add activity'));
    fireEvent.change(screen.getByLabelText('Occurred date'), { target: { value: '2026-10-02' } });
    fireEvent.click(await screen.findByLabelText('Attendee Pat Example'));
    fireEvent.click(screen.getByLabelText('Save activity'));
    await waitFor(() => expect(apiMock.createActivity).toHaveBeenCalled());
    const body = apiMock.createActivity.mock.calls[0][1];
    expect(apiMock.createActivity.mock.calls[0][0]).toBe(5);
    expect(body).toMatchObject({ type: 'call', actor: 'rep1', occurred_at: null, occurred_date: '2026-10-02', contact_ids: [9] });
  });

  it('renders a backend 422 verbatim and hides write surfaces for auditors', async () => {
    apiMock.createActivity.mockRejectedValue(Object.assign(new Error('Unknown actor'), { status: 422 }));
    const { unmount } = render(<ActivitiesPanel customerId={5} userRole="member" />);
    await screen.findByTestId('activity-row-1');
    fireEvent.click(screen.getByLabelText('Add activity'));
    fireEvent.change(screen.getByLabelText('Occurred date'), { target: { value: '2026-10-02' } });
    fireEvent.click(screen.getByLabelText('Save activity'));
    expect((await screen.findByTestId('activity-save-error')).textContent).toBe('Unknown actor');
    unmount();
    render(<ActivitiesPanel customerId={5} userRole="auditor" />);
    await screen.findByTestId('activity-row-1');
    expect(screen.queryByLabelText('Add activity')).toBeNull();
    expect(screen.queryByLabelText('Delete activity')).toBeNull();
  });

  it('delete asks for confirmation first', async () => {
    render(<ActivitiesPanel customerId={5} userRole="member" />);
    await screen.findByTestId('activity-row-1');
    fireEvent.click(screen.getByLabelText('Delete activity'));
    expect(apiMock.deleteActivity).not.toHaveBeenCalled();
    fireEvent.click(screen.getByLabelText('Confirm delete'));
    await waitFor(() => expect(apiMock.deleteActivity).toHaveBeenCalledWith(1));
  });
});

describe('TasksPanel', () => {
  it('renders status, assignee, overdue due in red, evidence counts', async () => {
    render(<TasksPanel customerId={5} userRole="member" />);
    expect((await screen.findByTestId('task-status-3')).textContent).toBe('open');
    expect(screen.getByTestId('task-assignee-3').textContent).toBe('Assignee: rep1');
    const due = screen.getByTestId('task-due-3');
    expect(due.textContent).toContain('2026-10-20');
    expect(due.textContent).toContain('overdue');
    expect(due.style.color).toBe('var(--status-negative)');
    expect(screen.getByTestId('task-meta-3').textContent).toContain('2 note(s), 1 activity');
  });

  it('undated + unassigned render honestly; needs_reassignment chip is flag-driven', async () => {
    apiMock.listTasks.mockResolvedValue([task({ assignee: null, due_date: null, overdue: false })]);
    const { unmount } = render(<TasksPanel customerId={5} userRole="member" />);
    expect((await screen.findByTestId('task-assignee-3')).textContent).toBe('Unassigned');
    expect(screen.getByTestId('task-due-3').textContent).toBe('Due: —');
    expect(screen.queryByTestId('task-needs-reassignment-3')).toBeNull();
    unmount();
    apiMock.listTasks.mockResolvedValue([task({ needs_reassignment: true })]);
    render(<TasksPanel customerId={5} userRole="member" />);
    expect(await screen.findByTestId('task-needs-reassignment-3')).toBeTruthy();
  });

  it('Start / Complete / Cancel / Reopen send expected_version and the target status', async () => {
    render(<TasksPanel customerId={5} userRole="member" />);
    fireEvent.click(await screen.findByLabelText('Start task Send quote'));
    await waitFor(() => expect(apiMock.updateTask).toHaveBeenCalledWith(3, { expected_version: 4, status: 'in_progress' }));
    fireEvent.click(await screen.findByLabelText('Complete task Send quote'));
    await waitFor(() => expect(apiMock.updateTask).toHaveBeenCalledWith(3, { expected_version: 4, status: 'completed' }));
    apiMock.listTasks.mockResolvedValue([task({ status: 'completed', version: 5 })]);
    fireEvent.click(await screen.findByLabelText('Cancel task Send quote'));
    await waitFor(() => expect(apiMock.updateTask).toHaveBeenCalledWith(3, { expected_version: 4, status: 'cancelled' }));
    fireEvent.click(await screen.findByLabelText('Reopen task Send quote'));
    await waitFor(() => expect(apiMock.updateTask).toHaveBeenCalledWith(3, { expected_version: 5, status: 'open' }));
  });

  it('reassign displays a name but sends its valid username; 422 renders verbatim', async () => {
    apiMock.updateTask.mockRejectedValue(Object.assign(new Error('Unknown assignee'), { status: 422 }));
    render(<TasksPanel customerId={5} userRole="member" assignees={[{ username: 'pat_rep', display_name: 'Pat Rep' }]} />);
    fireEvent.click(await screen.findByLabelText('Reassign task Send quote'));
    expect(screen.getByRole('option', { name: 'Pat Rep (pat_rep)' })).toBeTruthy();
    fireEvent.change(screen.getByLabelText('Reassign to username'), { target: { value: 'pat_rep' } });
    fireEvent.click(screen.getByLabelText('Confirm reassign'));
    await waitFor(() => expect(apiMock.updateTask).toHaveBeenCalledWith(3, { expected_version: 4, assignee: 'pat_rep' }));
    expect((await screen.findByTestId('tasks-error')).textContent).toBe('Unknown assignee');
  });

  it('409 concurrency message renders verbatim and the list reloads', async () => {
    apiMock.updateTask.mockRejectedValue(Object.assign(new Error(CONFLICT), { status: 409 }));
    render(<TasksPanel customerId={5} userRole="member" />);
    fireEvent.click(await screen.findByLabelText('Complete task Send quote'));
    expect((await screen.findByTestId('tasks-error')).textContent).toBe(CONFLICT);
    await waitFor(() => expect(apiMock.listTasks).toHaveBeenCalledTimes(2));
  });

  it('delete sends the version after confirmation; auditors see no write actions', async () => {
    const { unmount } = render(<TasksPanel customerId={5} userRole="member" />);
    fireEvent.click(await screen.findByLabelText('Delete task Send quote'));
    expect(apiMock.deleteTask).not.toHaveBeenCalled();
    fireEvent.click(screen.getByLabelText('Confirm delete'));
    await waitFor(() => expect(apiMock.deleteTask).toHaveBeenCalledWith(3, 4));
    unmount();
    render(<TasksPanel customerId={5} userRole="auditor" />);
    await screen.findByTestId('task-row-3');
    expect(screen.queryByLabelText('Add task')).toBeNull();
    expect(screen.queryByLabelText('Complete task Send quote')).toBeNull();
  });
});

describe('PromoteTaskButton', () => {
  it('created=true then created=false shows the neutral status; in-flight guard prevents double calls', async () => {
    let resolve!: (v: unknown) => void;
    apiMock.promoteTask.mockImplementationOnce(() => new Promise((r) => { resolve = r; }));
    render(<PromoteTaskButton customerId={5} sourceType="note" sourceId={11} label="note" />);
    const b = screen.getByLabelText('Create follow-up task from note');
    fireEvent.click(b);
    fireEvent.click(b);
    expect(apiMock.promoteTask).toHaveBeenCalledTimes(1);
    expect(apiMock.promoteTask).toHaveBeenCalledWith(5, { source_type: 'note', source_id: 11 });
    resolve({ created: true, task: task() });
    await waitFor(() => expect(screen.getByRole('status').textContent).toBe('Follow-up task created'));
    apiMock.promoteTask.mockResolvedValueOnce({ created: false, task: task() });
    fireEvent.click(b);
    await waitFor(() => expect(screen.getByRole('status').textContent).toBe('Task already exists for this source'));
    expect(screen.queryByRole('alert')).toBeNull();
  });
});

describe('MyTasksBlock', () => {
  it('shows open + overdue counts, rows, overdue red, and navigates to the account', async () => {
    apiMock.myTasks.mockResolvedValue([
      { ...task({ id: 1 }), customer_name: 'Acme' },
      { ...task({ id: 2, title: 'Other', overdue: false, due_date: '2099-01-01' }), customer_name: 'Beta' },
    ]);
    const onOpen = vi.fn();
    render(<MyTasksBlock username="rep1" onOpenAccount={onOpen} />);
    expect((await screen.findByTestId('my-tasks-open-count')).textContent).toBe('2 open');
    expect(screen.getByTestId('my-tasks-overdue-count').textContent).toBe('1 overdue');
    expect(screen.getByTestId('my-task-due-1').style.color).toBe('var(--status-negative)');
    expect(screen.getByTestId('my-task-due-2').style.color).not.toBe('var(--status-negative)');
    fireEvent.click(screen.getByTestId('my-task-2'));
    expect(onOpen).toHaveBeenCalledWith('Beta');
  });

  it('describes due date, overdue state and status for each task', async () => {
    apiMock.myTasks.mockResolvedValue([
      { ...task({ id: 1, status: 'open' }), customer_name: 'Acme' },
      { ...task({ id: 2, status: 'in_progress', due_date: '2099-01-01', overdue: false }), customer_name: 'Beta' },
      { ...task({ id: 3, due_date: null, due_at: null, overdue: false }), customer_name: 'Gamma' },
      { ...task({ id: 4, due_date: null, due_at: '2099-01-02T12:30:00Z', overdue: false }), customer_name: 'Delta' },
    ]);
    render(<MyTasksBlock username="rep1" onOpenAccount={() => {}} />);
    expect(await screen.findByRole('button', { name: /Open account Acme/, description: 'Due: 2026-10-20, overdue. Status: open.' })).toBeTruthy();
    expect(screen.getByRole('button', { name: /Open account Beta/, description: 'Due: 2099-01-01. Status: in_progress.' })).toBeTruthy();
    expect(screen.getByRole('button', { name: /Open account Gamma/, description: 'No due date. Status: open.' })).toBeTruthy();
    expect(screen.getByRole('button', { name: /Open account Delta/, description: 'Due: 2099-01-02 12:30 UTC. Status: open.' })).toBeTruthy();
  });

  it.each([
    ['unbroken', 'Task' + 'X'.repeat(173), 'Customer' + 'Y'.repeat(180)],
    ['spaced', 'Review a long customer task '.repeat(7), 'Example customer name '.repeat(8)],
  ])('preserves full %s task and customer names and keyboard activation', async (_kind, title, customerName) => {
    apiMock.myTasks.mockResolvedValue([{ ...task({ id: 9, title }), customer_name: customerName }]);
    const onOpen = vi.fn();
    render(<MyTasksBlock username="rep1" onOpenAccount={onOpen} />);
    const fullLabel = `Open account ${customerName} for task ${title}`;
    const row = await screen.findByRole('button', { name: fullLabel.replace(/\s+/g, ' ').trim() });
    expect(row.getAttribute('aria-label')).toBe(fullLabel);
    expect(row.textContent).toContain(title);
    expect(row.textContent).toContain(customerName);
    row.focus();
    const space = createEvent.keyDown(row, { key: ' ', code: 'Space' });
    fireEvent(row, space);
    expect(space.defaultPrevented).toBe(true);
    expect(onOpen).toHaveBeenCalledWith(customerName);
    fireEvent.keyDown(row, { key: 'Enter' });
    expect(onOpen).toHaveBeenCalledTimes(2);
  });

  it('a load failure is contained to the block', async () => {
    apiMock.myTasks.mockRejectedValue(new Error('boom'));
    render(<MyTasksBlock username="rep1" onOpenAccount={() => {}} />);
    expect((await screen.findByTestId('my-tasks-error')).textContent).toBe('boom');
  });
});

it('opens a permitted quick task form and submits a selected username', async () => {
  apiMock.listTasks.mockResolvedValue([]);
  apiMock.createTask.mockResolvedValue(task());
  render(<TasksPanel customerId={5} userRole="owner" createRequest={1} allowCreate assignees={[{ username: 'valid_rep', display_name: 'Valid Rep' }]} />);
  fireEvent.change(await screen.findByLabelText('Task title'), { target: { value: 'Next meeting' } });
  fireEvent.change(screen.getByLabelText('Task assignee'), { target: { value: 'valid_rep' } });
  fireEvent.click(screen.getByLabelText('Save task'));
  await waitFor(() => expect(apiMock.createTask).toHaveBeenCalledWith(5, expect.objectContaining({ assignee: 'valid_rep' })));
});

it('keeps task filters distinct from a truly empty account', async () => {
  apiMock.listTasks.mockResolvedValue([task({ overdue: false })]);
  render(<TasksPanel customerId={5} userRole="auditor" />);
  await screen.findByTestId('task-row-3');
  fireEvent.change(screen.getByLabelText('Task view'), { target: { value: 'overdue' } });
  expect(screen.queryByTestId('task-row-3')).toBeNull();
  expect(screen.getByText('No tasks match this view.')).toBeTruthy();
  expect(screen.queryByLabelText('Add task')).toBeNull();
});

it('edits existing task details and due date using the loaded version', async () => {
  apiMock.listTasks.mockResolvedValue([task()]);
  apiMock.updateTask.mockResolvedValue(task({ version: 5 }));
  render(<TasksPanel customerId={5} userRole="owner" />);
  fireEvent.click(await screen.findByLabelText('Edit task Send quote'));
  fireEvent.change(screen.getByLabelText('Task title'), { target: { value: 'Review new quote' } });
  fireEvent.change(screen.getByLabelText('Task detail'), { target: { value: 'Updated customer requirements' } });
  fireEvent.change(screen.getByLabelText('Due time'), { target: { value: '' } });
  fireEvent.change(screen.getByLabelText('Due date'), { target: { value: '2026-12-05' } });
  fireEvent.click(screen.getByLabelText('Save task'));
  await waitFor(() => expect(apiMock.updateTask).toHaveBeenCalledWith(3, expect.objectContaining({ expected_version: 4, title: 'Review new quote', detail: 'Updated customer requirements', due_date: '2026-12-05' })));
});


it('blocks a stale task edit until the user explicitly reloads the current version', async () => {
  apiMock.listTasks.mockResolvedValue([task()]);
  apiMock.updateTask.mockRejectedValue(Object.assign(new Error('Task changed since you loaded it'), { status: 409 }));
  apiMock.getTask.mockResolvedValue(task({ version: 8, title: 'Server task title' }));
  vi.spyOn(window, 'confirm').mockReturnValue(true);
  render(<TasksPanel customerId={5} userRole="owner" />);
  fireEvent.click(await screen.findByLabelText('Edit task Send quote'));
  fireEvent.change(screen.getByLabelText('Task title'), { target: { value: 'My stale draft' } });
  fireEvent.click(screen.getByLabelText('Save task'));
  await screen.findByText('Task changed since you loaded it');
  expect((screen.getByLabelText('Save task') as HTMLButtonElement).disabled).toBe(true);
  expect((screen.getByLabelText('Task title') as HTMLInputElement).value).toBe('My stale draft');
  fireEvent.click(screen.getByText('Reload task'));
  await waitFor(() => expect((screen.getByLabelText('Task title') as HTMLInputElement).value).toBe('Server task title'));
  expect((screen.getByLabelText('Save task') as HTMLButtonElement).disabled).toBe(false);
});
