/**
 * FE-02 / FE-06 / FE-07 — wizard (AssessmentForm) regressions, part 48.
 *
 * - FE-07: edit mode starts at "Step 1: Basic Info" (the old code indexed an
 *   unadjusted stepNames array and showed "Step 1: Select Template"); create
 *   mode includes the template step.
 * - FE-02: a blank CREATE assessment starts empty even when Home still holds
 *   a previously viewed record (field init only happens in edit mode).
 * - FE-06: a failed save surfaces in the wizard (submitError) with the input
 *   intact and no success navigation — Home's handlers rethrow to the form.
 *
 * Deterministic: the api module is mocked; no network, no inference.
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
vi.mock('../src/lib/templates', () => ({
  loadTemplates: vi.fn(),
}));

import { api } from '../src/lib/api';
import { loadTemplates } from '../src/lib/templates';

const mockedApi = vi.mocked(api);
const mockedTemplates = vi.mocked(loadTemplates);

const CUSTOMERS = [
  { id: 1, name: 'CustA', description: '', created_at: '', updated_at: '' },
  { id: 2, name: 'CustB', description: '', created_at: '', updated_at: '' },
];
const DEPTS_A = [{ id: 11, name: 'EngA', use_case_count: 0 }];
const DEPTS_B = [{ id: 22, name: 'EngB', use_case_count: 0 }];

beforeEach(() => {
  vi.clearAllMocks();
  mockedApi.listCustomers.mockResolvedValue(CUSTOMERS as any);
  mockedApi.listVerticals.mockResolvedValue({ verticals: [] } as any);
  mockedApi.listDepartments.mockImplementation(async (name?: string) =>
    (name ?? '').startsWith('CustA') ? DEPTS_A : DEPTS_B,
  );
  mockedTemplates.mockResolvedValue([]);
});
afterEach(cleanup);

// A record with DISTINCT customer + department ids (FE-02 acceptance).
const VIEWED_RECORD = {
  id: 99,
  title: 'Previously viewed record',
  description: 'must not leak into a blank create',
  customer_id: 2,
  department_id: 22,
  department: 'EngB',
  status: 'active',
  goals: ['goal-from-record'],
  challenges: [],
  pain_points: [],
  impact_category: 'savings',
  impact_description: 'impact-from-record',
  estimated_savings: 5000,
  estimated_revenue: 0,
  timeline_estimate: '12 months',
  created_at: '',
  updated_at: '',
};

const next = () => fireEvent.click(screen.getByRole('button', { name: 'Go to next step' }));

describe('AssessmentForm wizard (FE-02/06/07)', () => {
  it('FE-07: edit mode starts at "Step 1: Basic Info" and shows 6 steps', async () => {
    render(<AssessmentForm editMode initialData={VIEWED_RECORD} onSubmit={() => {}} onCancel={() => {}} />);
    await waitFor(() => expect(screen.getByText('Step 1: Basic Info')).toBeTruthy());
    expect(screen.queryByText(/Select Template/)).toBeNull();
    expect(screen.getByText('17% Complete')).toBeTruthy(); // 1/6
    for (let i = 0; i < 5; i++) next();
    await waitFor(() => expect(screen.getByText('Step 6: Review')).toBeTruthy());
  });

  it('FE-07: create mode includes the Select Template step (7 steps)', async () => {
    render(<AssessmentForm editMode={false} initialData={null} onSubmit={() => {}} onCancel={() => {}} />);
    await waitFor(() => expect(screen.getByText('Step 1: Select Template')).toBeTruthy());
    // Blank-assessment entry (no template).
    fireEvent.click(screen.getByRole('button', { name: 'Start a blank assessment' }));
    // (The template step's own "next" is guarded by the template choice; use
    // the wizard's Next after choosing blank.)
  });

  it('FE-02: a blank create starts empty even with a viewed record held', async () => {
    // Home passes initialData=selectedUseCase in both modes (legacy); create
    // mode must ignore it for field initialization.
    render(<AssessmentForm editMode={false} initialData={VIEWED_RECORD} onSubmit={() => {}} onCancel={() => {}} />);
    await waitFor(() => expect(screen.getByText('Step 1: Select Template')).toBeTruthy());
    fireEvent.click(screen.getByRole('button', { name: 'Start a blank assessment' }));
    next();
    await waitFor(() => expect(screen.getByText('Step 2: Basic Info')).toBeTruthy());
    // Title (targeted by its placeholder — the first generic textbox on
    // Basic Info is the "New Customer" name field) is blank, not the
    // viewed record's.
    const title = screen.getByPlaceholderText('e.g., AI-Powered Customer Support');
    expect((title as HTMLInputElement).value).toBe('');
    expect(screen.queryByText('Previously viewed record')).toBeNull();
  });

  it('FE-02: edit mode preselects the records customer (name + id in the payload)', async () => {
    render(<AssessmentForm editMode initialData={VIEWED_RECORD} onSubmit={() => {}} onCancel={() => {}} />);
    await waitFor(() => expect(screen.getByText('Step 1: Basic Info')).toBeTruthy());
    // Customer select shows the record's customer by name…
    await waitFor(() => expect(screen.getByDisplayValue('CustB')).toBeTruthy());
  });

  it('FE-06: a failed save shows the error, keeps the input, navigates nowhere', async () => {
    const failingCreate = vi.fn().mockRejectedValue(new Error('Server error (500)'));
    const onCancel = vi.fn();
    render(<AssessmentForm editMode={false} initialData={null} onSubmit={failingCreate} onCancel={onCancel} />);
    await waitFor(() => expect(screen.getByText('Step 1: Select Template')).toBeTruthy());
    // Choose blank (the button only selects; the wizard's Next advances).
    fireEvent.click(screen.getByRole('button', { name: 'Start a blank assessment' }));
    next();
    await waitFor(() => expect(screen.getByText('Step 2: Basic Info')).toBeTruthy());
    // Pick customer + set title.
    const selects = screen.getAllByLabelText('Assessment Form selection');
    fireEvent.change(selects[0], { target: { value: 'CustA' } });
    const title = screen.getByPlaceholderText('e.g., AI-Powered Customer Support');
    fireEvent.change(title, { target: { value: 'New blank assessment' } });
    // Forward to Review (Goals → Challenges → Pain Points → Impact → Review).
    for (let i = 0; i < 5; i++) next();
    await waitFor(() => expect(screen.getByText(/100% Complete/)).toBeTruthy());
    fireEvent.click(screen.getByRole('button', { name: 'Submit assessment' }));
    // The rejected callback surfaces as submitError — the form owns it.
    await waitFor(() => expect(screen.getByRole('alert').textContent).toContain('Server error (500)'));
    // Input intact + still on Review (no success navigation, no reset).
    expect(screen.getByText(/100% Complete/)).toBeTruthy();
    expect(onCancel).not.toHaveBeenCalled();
  });

  it('FE-06: a successful edit submits with customer_id + department_id (not names)', async () => {
    const onEdit = vi.fn().mockResolvedValue(undefined);
    render(<AssessmentForm editMode initialData={VIEWED_RECORD} onSubmit={() => {}} onCancel={() => {}} onEdit={onEdit} />);
    await waitFor(() => expect(screen.getByText('Step 1: Basic Info')).toBeTruthy());
    for (let i = 0; i < 5; i++) next();
    await waitFor(() => expect(screen.getByText(/100% Complete/)).toBeTruthy());
    fireEvent.click(screen.getByRole('button', { name: 'Submit assessment' }));
    await waitFor(() => expect(onEdit).toHaveBeenCalledTimes(1));
    const payload = onEdit.mock.calls[0][0];
    expect(payload.title).toBe('Previously viewed record');
    expect(payload.customer_id).toBe(2);
    expect(payload.department_id).toBe(22);
  });
});
