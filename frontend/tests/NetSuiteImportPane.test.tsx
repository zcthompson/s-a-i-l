// NetSuite pane: upload/result card (incl. the financial-ignored + not-stored
// line), history, read-only unmatched table (name/reason/suggestion/disposition),
// Re-match, manager-only 403 denied state, error + empty states. The pane never
// creates customers and never offers to create an alias.
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, waitFor, within, cleanup } from '@testing-library/react';
import { NetSuiteImportPane } from '../src/components/intelligence-import/NetSuiteImportPane';
import { MemoryRouter } from 'react-router-dom';

const { apiMock } = vi.hoisted(() => ({
  apiMock: {
    listNetSuiteImports: vi.fn(),
    uploadNetSuiteImport: vi.fn(),
    getNetSuiteImport: vi.fn(),
    getNetSuiteImportUnmatched: vi.fn(),
    rematchNetSuiteImport: vi.fn(),
  },
}));
vi.mock('../src/lib/api', () => ({ api: apiMock }));

const summary = {
  import_id: 11, file_name: 'ns-2026-09.csv', layout: 'csv',
  invoice_date: '2026-09-15', created_at: '2026-11-09T15:00:00+00:00',
  imported_by: 'manager1', status: 'complete_with_skips',
  total_rows: 309, matched_rows: 180, matched_accounts: 25, skipped_rows: 129,
  technologies_created: 40, technologies_refreshed: 140, technologies_associated: 0,
  risks_created: 3, risks_refreshed: 1, observations_created: 2,
};
const skippedRow = (over: Record<string, unknown> = {}) => ({
  id: 101, customer_name: 'Unmatched Testing Co', subscription_id: 'SUB-1',
  product: 'Acme Cloud Suite', term_end: null, detail_type: null, quantity: null,
  uom: null, term: null, term_type: null, invoice_date: '2026-09-15', status: 'Active',
  notes: null, source_row: 7, customer_id: null, matched_by: null, vendor: null,
  technology_id: null, risk_note_id: null, observation_note_id: null,
  disposition: 'skipped', reason: 'No unambiguous accessible customer name or alias',
  suggestion: { customer_id: 85, customer_name: 'Unmatched Testing Company' }, ...over,
});
const detail = (over: Record<string, unknown> = {}) => ({
  ...summary,
  rows: [],
  risk_notes: [{ customer_id: 85, subscription_id: 'SUB-9', kind: 'terminated', note_id: 401 }],
  risks: 4,
  skipped: [
    skippedRow(),
    skippedRow({
      id: 102, customer_name: 'Gone Testing LLC', source_row: 12,
      disposition: 'customer_deleted', reason: null, suggestion: null,
    }),
  ],
  ...over,
});
const forbidden = () => Object.assign(new Error('Manager access required'), { status: 403 });

beforeEach(() => {
  Object.values(apiMock).forEach((m) => m.mockReset());
  apiMock.listNetSuiteImports.mockResolvedValue([summary]);
});
afterEach(() => { cleanup(); vi.restoreAllMocks(); });

describe('NetSuiteImportPane', () => {
  it('renders the intro, the financial-ignored/not-stored line, and gates upload on a file', async () => {
    render(<NetSuiteImportPane />);
    expect(screen.getByTestId('netsuite-import-privacy').textContent)
      .toContain('Pricing and other financial columns are ignored, and the uploaded file is not stored');
    expect(screen.getByText(/No customers are created and no money is imported/)).toBeTruthy();
    const submit = screen.getByTestId('netsuite-import-submit') as HTMLButtonElement;
    expect(submit.disabled).toBe(true);
    expect((screen.getByTestId('netsuite-import-file') as HTMLInputElement).accept).toBe('.csv,.xlsx');
    fireEvent.change(screen.getByTestId('netsuite-import-file'), { target: { files: [new File(['x'], 'ns.csv')] } });
    expect(submit.disabled).toBe(false);
  });

  it('uploads a report, shows the result summary counters and refreshes history', async () => {
    apiMock.uploadNetSuiteImport.mockResolvedValue(detail());
    render(<NetSuiteImportPane />);
    await screen.findByTestId('netsuite-import-row-11');
    fireEvent.change(screen.getByTestId('netsuite-import-file'), { target: { files: [new File(['x'], 'ns-2026-09.csv')] } });
    fireEvent.click(screen.getByTestId('netsuite-import-submit'));
    const sum = await screen.findByTestId('netsuite-import-summary');
    expect(apiMock.uploadNetSuiteImport).toHaveBeenCalledTimes(1);
    expect(sum.textContent).toContain('ns-2026-09.csv');
    expect(sum.textContent).toContain('Completed with skipped rows');
    expect(sum.textContent).toContain('309 rows read');
    expect(sum.textContent).toContain('180 rows matched 25 customers');
    expect(sum.textContent).toContain('40 created, 140 refreshed, 0 associated');
    expect(sum.textContent).toContain('3 raised, 1 refreshed');
    const warn = screen.getByTestId('netsuite-import-unmatched-warning');
    expect(warn.textContent).toContain('129 rows skipped');
    expect(warn.textContent).toContain('no customers were created');
    await waitFor(() => expect(apiMock.listNetSuiteImports).toHaveBeenCalledTimes(2));
  });

  it('omits the skipped warning when every row matched', async () => {
    apiMock.uploadNetSuiteImport.mockResolvedValue(detail({ status: 'complete', skipped_rows: 0, skipped: [] }));
    render(<NetSuiteImportPane />);
    await screen.findByTestId('netsuite-import-row-11');
    fireEvent.change(screen.getByTestId('netsuite-import-file'), { target: { files: [new File(['x'], 'ns.csv')] } });
    fireEvent.click(screen.getByTestId('netsuite-import-submit'));
    await screen.findByTestId('netsuite-import-summary');
    expect(screen.queryByTestId('netsuite-import-unmatched-warning')).toBeNull();
  });

  it('opens a history record and shows the read-only unmatched table with reasons and the single suggestion', async () => {
    apiMock.getNetSuiteImport.mockResolvedValue(detail());
    render(<NetSuiteImportPane />);
    const row = await screen.findByTestId('netsuite-import-row-11');
    expect(row.textContent).toContain('ns-2026-09.csv');
    expect(row.textContent).toContain('manager1');
    expect(row.textContent).toContain('Completed with skipped rows');
    fireEvent.click(row);
    const unmatched = await screen.findByTestId('netsuite-import-unmatched');
    expect(apiMock.getNetSuiteImport).toHaveBeenCalledWith(11);
    const first = within(unmatched).getByTestId('netsuite-import-unmatched-101');
    expect(first.textContent).toContain('Unmatched Testing Co');
    expect(first.textContent).toContain('No unambiguous accessible customer name or alias');
    expect(first.textContent).toContain('Possible match: Unmatched Testing Company');
    expect(first.textContent).toContain('Skipped');
    const second = within(unmatched).getByTestId('netsuite-import-unmatched-102');
    expect(second.textContent).toContain('Customer deleted');
    expect(second.textContent).toContain('—'); // no suggestion rendered
    expect(screen.getByTestId('netsuite-import-rematch-help').textContent).toContain('no re-upload');
  });

  it('shows the all-rows-matched state when nothing was skipped', async () => {
    apiMock.getNetSuiteImport.mockResolvedValue(detail({ skipped: [], skipped_rows: 0 }));
    render(<NetSuiteImportPane />);
    fireEvent.click(await screen.findByTestId('netsuite-import-row-11'));
    expect((await screen.findByTestId('netsuite-import-unmatched-empty')).textContent).toContain('All rows matched');
  });

  it('re-matches the stored rows and reports the outcome', async () => {
    apiMock.getNetSuiteImport.mockResolvedValue(detail());
    apiMock.rematchNetSuiteImport.mockResolvedValue(detail({ matched_rows: 200, matched_accounts: 28, skipped_rows: 109 }));
    render(<NetSuiteImportPane />);
    fireEvent.click(await screen.findByTestId('netsuite-import-row-11'));
    await screen.findByTestId('netsuite-import-detail');
    fireEvent.click(screen.getByTestId('netsuite-import-rematch'));
    expect(apiMock.rematchNetSuiteImport).toHaveBeenCalledWith(11);
    const notice = await screen.findByTestId('netsuite-import-notice');
    expect(notice.textContent).toContain('200 of 309 rows now match 28 customers');
    await waitFor(() => expect(apiMock.listNetSuiteImports).toHaveBeenCalledTimes(2));
  });

  it('re-match notice uses the singular for a single matched account', async () => {
    apiMock.getNetSuiteImport.mockResolvedValue(detail());
    apiMock.rematchNetSuiteImport.mockResolvedValue(detail({ matched_rows: 1, matched_accounts: 1, skipped_rows: 308 }));
    render(<NetSuiteImportPane />);
    fireEvent.click(await screen.findByTestId('netsuite-import-row-11'));
    await screen.findByTestId('netsuite-import-detail');
    fireEvent.click(screen.getByTestId('netsuite-import-rematch'));
    const notice = await screen.findByTestId('netsuite-import-notice');
    expect(notice.textContent).toContain('1 of 309 rows now match 1 customer');
    expect(notice.textContent).not.toContain('1 customers');
  });

  it('shows the manager-only denied state on a 403 history load (no raw error, no form)', async () => {
    apiMock.listNetSuiteImports.mockRejectedValue(forbidden());
    render(<NetSuiteImportPane />);
    const denied = await screen.findByTestId('netsuite-import-denied');
    expect(denied.textContent).toContain('Requires a system admin or sales manager');
    expect(screen.queryByTestId('netsuite-import-error')).toBeNull();
    expect(screen.queryByTestId('netsuite-import-submit')).toBeNull();
    expect(screen.queryByTestId('netsuite-import-file')).toBeNull();
  });

  it('shows the denied state when the upload itself 403s', async () => {
    apiMock.uploadNetSuiteImport.mockRejectedValue(forbidden());
    render(<NetSuiteImportPane />);
    await screen.findByTestId('netsuite-import-row-11');
    fireEvent.change(screen.getByTestId('netsuite-import-file'), { target: { files: [new File(['x'], 'ns.csv')] } });
    fireEvent.click(screen.getByTestId('netsuite-import-submit'));
    expect((await screen.findByTestId('netsuite-import-denied')).textContent).toContain('Requires a system admin or sales manager');
  });

  it('surfaces a 422 report error in the banner without a result card', async () => {
    apiMock.uploadNetSuiteImport.mockRejectedValue(Object.assign(new Error('Report contains no subscription rows'), { status: 422 }));
    render(<NetSuiteImportPane />);
    await screen.findByTestId('netsuite-import-row-11');
    fireEvent.change(screen.getByTestId('netsuite-import-file'), { target: { files: [new File(['x'], 'bad.csv')] } });
    fireEvent.click(screen.getByTestId('netsuite-import-submit'));
    expect((await screen.findByTestId('netsuite-import-error')).textContent).toContain('Report contains no subscription rows');
    expect(screen.queryByTestId('netsuite-import-summary')).toBeNull();
  });

  it('reports an inaccessible or removed record instead of stale detail', async () => {
    apiMock.getNetSuiteImport.mockRejectedValue(Object.assign(new Error('Import not found'), { status: 404 }));
    render(<NetSuiteImportPane />);
    fireEvent.click(await screen.findByTestId('netsuite-import-row-11'));
    expect((await screen.findByTestId('netsuite-import-error')).textContent).toContain('Import not found or unavailable');
    expect(screen.queryByTestId('netsuite-import-detail')).toBeNull();
  });

  it('restores a linked record from a direct URL', async () => {
    apiMock.getNetSuiteImport.mockResolvedValue(detail());
    render(<MemoryRouter initialEntries={['/?view=gi-import&source=netsuite&import=11']}><NetSuiteImportPane /></MemoryRouter>);
    expect(await screen.findByTestId('netsuite-import-detail')).toBeTruthy();
    expect(apiMock.getNetSuiteImport).toHaveBeenCalledWith(11);
  });

  it('offers no alias or customer creation affordance anywhere in the pane', async () => {
    apiMock.getNetSuiteImport.mockResolvedValue(detail());
    render(<NetSuiteImportPane />);
    fireEvent.click(await screen.findByTestId('netsuite-import-row-11'));
    await screen.findByTestId('netsuite-import-detail');
    expect(screen.queryByRole('button', { name: /add alias/i })).toBeNull();
    expect(screen.queryByRole('button', { name: /create.*customer/i })).toBeNull();
    expect(screen.queryByRole('button', { name: /create.*alias/i })).toBeNull();
    // The guidance describes the manual path only — it is not an offer.
    expect(screen.getByText(/add that name as an alias in More → Edit Customer/)).toBeTruthy();
    expect(screen.getByText(/add that name as an alias in More → Edit Customer/).tagName).toBe('P');
  });
});
