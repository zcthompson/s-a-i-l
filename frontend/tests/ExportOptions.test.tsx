import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { act, cleanup, fireEvent, render, screen } from '@testing-library/react';
import { ExportPage } from '../src/pages/ExportPage';
import { CustomerExport } from '../src/components/CustomerExport';
import type { Customer, UseCase } from '../src/types/use_case';
const apiMock = vi.hoisted(() => ({ exportPdf: vi.fn(), exportExcel: vi.fn(), exportCSV: vi.fn(), listCustomers: vi.fn(), listAssessments: vi.fn() }));
vi.mock('../src/lib/api', () => ({ api: apiMock }));
beforeEach(() => vi.clearAllMocks());
afterEach(cleanup);
const customer = { id: 1, name: 'Synthetic export account' } as Customer;
it('blocks other formats during export and restores them after a failure', async () => {
  let reject!: (error: Error) => void;
  apiMock.exportPdf.mockReturnValue(new Promise((_, r) => { reject = r; }));
  render(<CustomerExport customer={customer} useCases={[{ id: 1 } as UseCase]} onBack={() => {}} />);
  const pdf = screen.getByRole('button', { name: 'Export customer report as PDF' }) as HTMLButtonElement;
  const csv = screen.getByRole('button', { name: 'Export customer report as CSV' }) as HTMLButtonElement;
  fireEvent.click(pdf);
  expect(apiMock.exportPdf).toHaveBeenCalledWith(customer.name);
  expect(pdf.getAttribute('aria-busy')).toBe('true');
  expect(csv.disabled).toBe(true);
  fireEvent.click(csv);
  expect(apiMock.exportCSV).not.toHaveBeenCalled();
  await act(async () => reject(new Error('Export unavailable')));
  expect(screen.getByRole('alert').textContent).toContain('Export unavailable');
  expect(pdf.disabled).toBe(false);
  expect(csv.disabled).toBe(false);
});
it('keeps all report formats unavailable when there are no use cases', () => {
  render(<CustomerExport customer={customer} useCases={[]} onBack={() => {}} />);
  for (const format of ['PDF','Excel','CSV']) expect((screen.getByRole('button', { name: `Export customer report as ${format}` }) as HTMLButtonElement).disabled).toBe(true);
});

it('preserves assessment scope and a linked format suggestion on global export', async () => {
  apiMock.listCustomers.mockResolvedValue([customer]);
  apiMock.listAssessments.mockResolvedValue([{ id: 37, name: 'Synthetic round', status: 'active', created_at: '2026-01-01', use_case_count: 1 }]);
  apiMock.exportExcel.mockRejectedValue(new Error('Synthetic failure'));
  render(<ExportPage initialFormat="excel" />);
  const select = await screen.findByLabelText('Select customer to export');
  fireEvent.change(select, { target: { value: customer.name } });
  await screen.findByText('Synthetic round — Active (1 use case)');
  expect(screen.getByText('Suggested format').closest('button')?.getAttribute('aria-label')).toBe('Export report as Excel');
  fireEvent.click(screen.getByRole('button', { name: 'Export report as Excel' }));
  await screen.findByRole('alert');
  expect(apiMock.exportExcel).toHaveBeenCalledWith(customer.name, undefined, 37);
});
