/**
 * FE-12 — assessment-work discard guard.
 *
 * The wizard tracks meaningful changes relative to the initial draft and
 * warns before abandoning a dirty assessment. The Cancel button (first step)
 * surfaces a Stay/Discard confirm when the draft is dirty; a clean form (or a
 * successful save) navigates without prompting. The dirty flag is also
 * reported to the parent (Home's sidebar guard + beforeunload) via
 * onDirtyChange.
 * Deterministic: api + templates mocked.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, cleanup, waitFor, fireEvent } from '@testing-library/react';
import { AssessmentForm } from '../src/components/AssessmentForm';

vi.mock('../src/lib/api', () => ({
  api: {
    listCustomers: vi.fn(),
    listVerticals: vi.fn(),
    listDepartments: vi.fn(),
    create: vi.fn(),
    update: vi.fn(),
  },
}));
vi.mock('../src/lib/templates', () => ({ loadTemplates: vi.fn() }));

import { api } from '../src/lib/api';
import { loadTemplates } from '../src/lib/templates';

const mockedApi = vi.mocked(api);
const mockedTemplates = vi.mocked(loadTemplates);

const CUSTOMERS = [{ id: 1, name: 'CustA', description: '', created_at: '', updated_at: '' }];
const DEPTS_A = [{ id: 11, name: 'EngA', customer_id: 1, created_at: '' }];

beforeEach(() => {
  vi.clearAllMocks();
  mockedApi.listCustomers.mockResolvedValue(CUSTOMERS as any);
  mockedApi.listVerticals.mockResolvedValue({ verticals: [] } as any);
  mockedApi.listDepartments.mockResolvedValue(DEPTS_A as any);
  mockedTemplates.mockResolvedValue([]);
});
afterEach(cleanup);

const titleInput = () => screen.getByPlaceholderText('e.g., AI-Powered Customer Support') as HTMLInputElement;
const next = () => fireEvent.click(screen.getByRole('button', { name: 'Go to next step' }));
const prev = () => fireEvent.click(screen.getByRole('button', { name: 'Go to previous step' }));
const cancel = () => fireEvent.click(screen.getByRole('button', { name: 'Cancel assessment' }));

describe('FE-12 assessment discard guard', () => {
  it('a clean create form is not dirty and Cancel navigates immediately', async () => {
    const onCancel = vi.fn();
    const onDirtyChange = vi.fn();
    render(<AssessmentForm editMode={false} initialData={null} onSubmit={() => {}} onCancel={onCancel} onDirtyChange={onDirtyChange} />);
    await waitFor(() => expect(screen.getByText('Step 1: Select Template')).toBeTruthy());
    expect(onDirtyChange).toHaveBeenLastCalledWith(false);
    // On the first step with no edits: Cancel navigates immediately (no dialog).
    cancel();
    expect(onCancel).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole('dialog')).toBeNull();
  });

  it('editing a field makes the draft dirty; Cancel surfaces Stay/Discard', async () => {
    const onCancel = vi.fn();
    const onDirtyChange = vi.fn();
    render(<AssessmentForm editMode={false} initialData={null} onSubmit={() => {}} onCancel={onCancel} onDirtyChange={onDirtyChange} />);
    await waitFor(() => expect(screen.getByText('Step 1: Select Template')).toBeTruthy());
    // Advance to Basic Info and edit the title (now dirty).
    fireEvent.click(screen.getByRole('button', { name: 'Start a blank assessment' }));
    next();
    await waitFor(() => expect(screen.getByText('Step 2: Basic Info')).toBeTruthy());
    fireEvent.change(titleInput(), { target: { value: 'Unsaved draft' } });
    await waitFor(() => expect(onDirtyChange).toHaveBeenLastCalledWith(true));
    // Return to the first step (where the Cancel button lives) and cancel.
    prev();
    await waitFor(() => expect(screen.getByText('Step 1: Select Template')).toBeTruthy());
    cancel();
    // Dirty → the confirm dialog appears, no immediate navigation.
    await waitFor(() => expect(screen.getByRole('dialog')).toBeTruthy());
    expect(onCancel).not.toHaveBeenCalled();
    // Stay keeps the draft (dialog closes, still on the first step, dirty).
    fireEvent.click(screen.getByRole('button', { name: 'Stay and keep editing' }));
    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
    expect(onCancel).not.toHaveBeenCalled();
    // Discard navigates exactly once.
    cancel();
    await waitFor(() => expect(screen.getByRole('dialog')).toBeTruthy());
    fireEvent.click(screen.getByRole('button', { name: 'Discard and leave' }));
    expect(onCancel).toHaveBeenCalledTimes(1);
  });

  it('a successful save clears the dirty state (onDirtyChange back to false)', async () => {
    const onSubmit = vi.fn().mockResolvedValue({});
    const onDirtyChange = vi.fn();
    render(<AssessmentForm editMode={false} initialData={null} onSubmit={onSubmit} onCancel={() => {}} onDirtyChange={onDirtyChange} />);
    await waitFor(() => expect(screen.getByText('Step 1: Select Template')).toBeTruthy());
    fireEvent.click(screen.getByRole('button', { name: 'Start a blank assessment' }));
    next();
    await waitFor(() => expect(screen.getByText('Step 2: Basic Info')).toBeTruthy());
    const selects = screen.getAllByLabelText('Assessment Form selection');
    fireEvent.change(selects[0], { target: { value: 'CustA' } });
    fireEvent.change(titleInput(), { target: { value: 'Saved draft' } });
    await waitFor(() => expect(onDirtyChange).toHaveBeenLastCalledWith(true));
    // Advance to Review and submit (success).
    for (let i = 0; i < 5; i++) next();
    await waitFor(() => expect(screen.getByText(/100% Complete/)).toBeTruthy());
    fireEvent.click(screen.getByRole('button', { name: 'Submit assessment' }));
    await waitFor(() => expect(onSubmit).toHaveBeenCalledTimes(1));
    // After a successful save the baseline resets → no longer dirty.
    await waitFor(() => expect(onDirtyChange).toHaveBeenLastCalledWith(false));
  });
});
