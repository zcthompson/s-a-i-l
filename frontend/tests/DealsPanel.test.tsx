/**
 * DealsPanel component tests (synthetic fixtures only).
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, cleanup, within, waitFor } from '@testing-library/react';
import { DealsPanel, formatDealAmount, probabilityText, toMinor } from '../src/components/DealsPanel';
import type { Deal, PipelineStage } from '../src/types/deals';

afterEach(() => cleanup());

const { apiMock } = vi.hoisted(() => ({
  apiMock: {
    getDeal: vi.fn(), listDeals: vi.fn(), listPipelineStages: vi.fn(), createDeal: vi.fn(), updateDeal: vi.fn(),
    deleteDeal: vi.fn(), dealHistory: vi.fn(),
  },
}));
vi.mock('../src/lib/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../src/lib/api')>();
  return { ...actual, api: { ...actual.api, ...apiMock } };
});

const stage = (id: number, label: string, stage_class: PipelineStage['stage_class'], prob: number | null): PipelineStage =>
  ({ id, key: label.toLowerCase().replace(/ /g, '_'), label, stage_class, position: id * 10, active: true, default_probability: prob });
const STAGES = [stage(1, 'Qualification', 'open', 10), stage(2, 'Proposal', 'open', 50), stage(3, 'Closed Lost', 'lost', 0)];

const deal = (over: Partial<Deal> = {}): Deal => ({
  id: 7, customer_id: 1, name: 'Synthetic expansion', owner_user_id: 3, owner_name: 'Synthetic Rep', stage: STAGES[1],
  stage_id: 2, probability: null, suggested_probability: 50, close_date: '2026-12-31',
  amount: { minor: 1250000, currency: 'USD' }, amount_minor: 1250000, currency: 'USD', amount_basis: 'acv',
  deal_type: 'expansion', next_step: 'Send proposal', next_step_date: '2026-11-20', closed_reason: null, closed_at: null,
  source_type: null, source_id: null, source_key: null, created_by: 'synthetic', created_at: null, updated_at: null,
  version: 3, contacts: [], task_ids: [], activity_ids: [], note_ids: [], technology_ids: [], ...over,
});

describe('DealsPanel', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    apiMock.listPipelineStages.mockResolvedValue(STAGES);
    apiMock.listDeals.mockResolvedValue([deal()]);
  });

  it('lists deals with currency, basis and a probability suggestion (never stored)', async () => {
    render(<DealsPanel customerId={1} userRole="owner" />);
    await screen.findByTestId('deal-7');
    expect(screen.getByRole('heading', { name: 'Deals (1 open)' })).toBeTruthy();
    expect(screen.getByTestId('deal-amount-7').textContent).toMatch(/12,500\.00 · ACV/);
    expect(screen.getByTestId('deal-probability-7').textContent).toBe('Probability: Not set (stage suggests 50%)');
    expect(screen.getByTestId('deal-stage-7').textContent).toBe('Proposal');
  });

  it('shows an empty state', async () => {
    apiMock.listDeals.mockResolvedValue([]);
    render(<DealsPanel customerId={1} userRole="owner" />);
    expect((await screen.findByTestId('deals-empty')).textContent).toContain('No deals recorded');
  });

  it('hides write controls from auditors', async () => {
    render(<DealsPanel customerId={1} userRole="auditor" />);
    await screen.findByTestId('deal-7');
    expect(screen.queryByRole('button', { name: 'New deal' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'Edit' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'Delete' })).toBeNull();
    expect(screen.getByRole('button', { name: 'History' })).toBeTruthy();
  });

  it('creates a deal in minor units and requires a basis for an amount', async () => {
    apiMock.createDeal.mockResolvedValue(deal({ id: 8 }));
    render(<DealsPanel customerId={1} userRole="owner" />);
    fireEvent.click(await screen.findByRole('button', { name: 'New deal' }));
    const form = screen.getByTestId('deal-form');
    fireEvent.change(within(form).getByLabelText('Deal name'), { target: { value: 'Synthetic new deal' } });
    fireEvent.change(within(form).getByLabelText('Deal amount'), { target: { value: '1,500.50' } });
    expect((within(form).getByLabelText('Deal probability') as HTMLInputElement).placeholder).toBe('Stage suggests 10');
    fireEvent.click(within(form).getByRole('button', { name: 'Create deal' }));
    expect(within(form).getByRole('alert').textContent).toContain('Choose a basis');
    expect(apiMock.createDeal).not.toHaveBeenCalled();
    fireEvent.change(within(form).getByLabelText('Deal amount basis'), { target: { value: 'tcv' } });
    fireEvent.click(within(form).getByRole('button', { name: 'Create deal' }));
    await waitFor(() => expect(apiMock.createDeal).toHaveBeenCalledTimes(1));
    expect(apiMock.createDeal.mock.calls[0][1]).toMatchObject({
      name: 'Synthetic new deal', stage_id: 1, amount_minor: 150050, currency: 'USD', amount_basis: 'tcv', probability: null,
    });
  });

  it('shows the closed-reason field for a lost stage and reloads after a version conflict', async () => {
    apiMock.updateDeal.mockRejectedValue(Object.assign(new Error('Deal changed since you loaded it; reload and retry'), { status: 409 }));
    render(<DealsPanel customerId={1} userRole="owner" />);
    fireEvent.click(await screen.findByRole('button', { name: 'Edit' }));
    const form = screen.getByTestId('deal-form');
    expect(within(form).queryByLabelText('Deal closed reason')).toBeNull();
    fireEvent.change(within(form).getByLabelText('Deal stage'), { target: { value: '3' } });
    fireEvent.change(within(form).getByLabelText('Deal closed reason'), { target: { value: 'Budget withdrawn' } });
    fireEvent.click(within(form).getByRole('button', { name: 'Save deal' }));
    await waitFor(() => expect(screen.getByRole('alert').textContent).toContain('Deal changed since you loaded it'));
    expect(apiMock.updateDeal.mock.calls[0][1]).toMatchObject({ expected_version: 3, stage_id: 3, closed_reason: 'Budget withdrawn' });
    expect(apiMock.listDeals).toHaveBeenCalledTimes(2);
  });

  it('helpers stay honest', () => {
    expect(toMinor('')).toBeNull();
    expect(toMinor('12.5')).toBe(1250);
    expect(Number.isNaN(toMinor('12.555') as number)).toBe(true);
    expect(formatDealAmount({ amount: null, amount_basis: null })).toBe('Amount not recorded');
    expect(probabilityText({ probability: 40, suggested_probability: 50 })).toBe('40%');
  });
});

it('filters the complete account list and renders counted stage columns with a reviewed move', async () => {
  apiMock.listPipelineStages.mockResolvedValue(STAGES);
  apiMock.listDeals.mockResolvedValue([deal(), deal({ id: 8, name: 'Other renewal', owner_user_id: null, owner_name: null, stage: STAGES[0], stage_id: 1, close_date: null })]);
  render(<DealsPanel customerId={1} userRole="owner" />);
  await screen.findByTestId('deal-8');
  fireEvent.change(screen.getByLabelText('Filter deals by owner'), { target: { value: 'unassigned' } });
  expect(screen.queryByTestId('deal-7')).toBeNull();
  fireEvent.change(screen.getByLabelText('Close date from'), { target: { value: '2026-01-01' } });
  expect(screen.getByText('No deals match these filters.')).toBeTruthy();
  fireEvent.click(screen.getAllByText('Clear deal filters')[0]);
  fireEvent.change(screen.getByLabelText('Deal layout'), { target: { value: 'board' } });
  expect(screen.getByRole('heading', { name: 'Proposal (1)' })).toBeTruthy();
  fireEvent.change(screen.getByLabelText('Move Synthetic expansion to stage'), { target: { value: '3' } });
  expect(screen.getByLabelText('Deal closed reason')).toBeTruthy();
  expect(apiMock.updateDeal).not.toHaveBeenCalled();
});

it('opens the quick-create form with a valid stage after asynchronous stages load', async () => {
  apiMock.listPipelineStages.mockResolvedValue(STAGES);
  apiMock.listDeals.mockResolvedValue([]);
  apiMock.createDeal.mockResolvedValue(deal());
  render(<DealsPanel customerId={1} userRole="owner" createRequest={1} allowCreate />);
  const field = await screen.findByLabelText('Deal name');
  fireEvent.change(field, { target: { value: 'Quick deal' } });
  fireEvent.click(screen.getByText('Create deal'));
  await waitFor(() => expect(apiMock.createDeal).toHaveBeenCalledWith(1, expect.objectContaining({ name: 'Quick deal', stage_id: 1 })));
});


it('fetches the current deal version when editing from an exact record detail', async () => {
  apiMock.listDeals.mockResolvedValue([deal({ version: 3 })]);
  apiMock.listPipelineStages.mockResolvedValue(STAGES);
  apiMock.getDeal.mockResolvedValue(deal({ version: 8 }));
  apiMock.updateDeal.mockResolvedValue(deal({ version: 9 }));
  render(<DealsPanel customerId={1} userRole="owner" editRecordId={7} editRequest={1} />);
  await screen.findByLabelText('Deal name');
  fireEvent.click(screen.getByText('Save deal'));
  await waitFor(() => expect(apiMock.updateDeal).toHaveBeenCalledWith(7, expect.objectContaining({ expected_version: 8 })));
});
