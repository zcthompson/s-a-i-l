// Rep Provided — Generic Account Intelligence pane: guidance + template,
// upload/result card, history, detail (issues, customer links, out-of-scope),
// can_manage-gated downloads/delete, error + empty states, no denied state.
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, waitFor, within, cleanup } from '@testing-library/react';
import { GenericRepIntelligencePane } from '../src/components/intelligence-import/GenericRepIntelligencePane';
import { MemoryRouter } from 'react-router-dom';

const { apiMock } = vi.hoisted(() => ({
  apiMock: {
    listRepIntelligenceImports: vi.fn(),
    uploadRepIntelligenceImport: vi.fn(),
    getRepIntelligenceImport: vi.fn(),
    deleteRepIntelligenceImport: vi.fn(),
    downloadRepIntelligenceTemplate: vi.fn(),
    downloadRepIntelligenceSource: vi.fn(),
    downloadRepIntelligenceIssues: vi.fn(),
  },
}));
vi.mock('../src/lib/api', () => ({ api: apiMock }));

const summary = {
  import_id: 7, file_name: 'rep-notes.csv', created_at: '2026-10-25T15:00:00+00:00',
  imported_by: 'rep1', total_rows: 4, imported_rows: 2, imported_with_issues: 1, skipped_rows: 1,
  status: 'completed_with_issues', technologies_created: 2, technologies_refreshed: 1,
};
const row = (over: Record<string, unknown> = {}) => ({
  id: 1, import_id: 7, source_row: 1, customer_name_supplied: 'Acme Testing Corp', customer_id: 11,
  customer_name: 'Acme Testing Corp', technology_name_supplied: 'Widget Server', hardware_software: 'hardware',
  is_sale: null, amount: null, currency: null, vendor: null, version: null, quantity: null, notes: null,
  technology_id: 5, status: 'imported', issues: [], created_at: '2026-10-25T15:00:00+00:00', ...over,
});
const detail = (over: Record<string, unknown> = {}) => ({
  ...summary,
  rows: [
    row(),
    row({
      id: 2, source_row: 2, technology_name_supplied: 'Gadget Suite', status: 'imported_with_issues',
      issues: [{ field: 'amount', code: 'amount_invalid', severity: 'warning', message: 'amount must be a valid decimal; technology imported with amount unknown', disposition: 'field_omitted', value: 'lots' }],
    }),
    row({
      id: 3, source_row: 3, customer_name_supplied: 'Nowhere Ltd', customer_id: null, customer_name: null,
      technology_name_supplied: 'Gizmo', status: 'skipped', technology_id: null,
      issues: [{ field: 'customer_name', code: 'customer_unmatched', severity: 'error', message: 'no matching accessible customer; row skipped', disposition: 'row_skipped' }],
    }),
  ],
  matched: [{ customer_id: 11, customer_name: 'Acme Testing Corp' }],
  matched_out_of_scope: 0, can_manage: true, ...over,
});

beforeEach(() => {
  Object.values(apiMock).forEach((m) => m.mockReset());
  apiMock.listRepIntelligenceImports.mockResolvedValue([summary]);
});
afterEach(() => { cleanup(); vi.restoreAllMocks(); });

describe('GenericRepIntelligencePane', () => {
  it('restores an authorized detail from a direct record link', async () => {
    apiMock.getRepIntelligenceImport.mockResolvedValue(detail());
    render(<MemoryRouter initialEntries={['/?view=gi-import&source=rep&import=7']}><GenericRepIntelligencePane /></MemoryRouter>);
    expect(await screen.findByTestId('rep-intel-detail')).toBeTruthy();
    expect(apiMock.getRepIntelligenceImport).toHaveBeenCalledWith(7);
  });

  it('renders the field guidance and downloads the template as a blob', async () => {
    const createUrl = vi.fn(() => 'blob:tpl');
    const revokeUrl = vi.fn();
    Object.assign(URL, { createObjectURL: createUrl, revokeObjectURL: revokeUrl });
    const clickSpy = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {});
    const blob = new Blob(['customer_name,technology_name\n'], { type: 'text/csv' });
    apiMock.downloadRepIntelligenceTemplate.mockResolvedValue(blob);

    render(<GenericRepIntelligencePane />);
    await screen.findByTestId('rep-intel-row-7');
    const guidance = screen.getByTestId('rep-intel-guidance');
    expect(within(guidance).getByTestId('rep-intel-guidance-customer_name').textContent).toContain('Required');
    expect(within(guidance).getByTestId('rep-intel-guidance-technology_name').textContent).toContain('Required');
    expect(within(guidance).getByTestId('rep-intel-guidance-amount').textContent).toContain('Optional');
    expect(within(guidance).getByTestId('rep-intel-guidance-amount').textContent).toContain('Blank = unknown (not zero)');
    expect(within(guidance).getByTestId('rep-intel-guidance-is_sale').textContent).toContain("Blank = unknown (not 'no')");

    fireEvent.click(screen.getByTestId('rep-intel-template'));
    await waitFor(() => expect(clickSpy).toHaveBeenCalled());
    expect(apiMock.downloadRepIntelligenceTemplate).toHaveBeenCalledTimes(1);
    expect(createUrl).toHaveBeenCalledWith(blob);
    expect(revokeUrl).toHaveBeenCalledWith('blob:tpl');
  });

  it('uploads a CSV, shows the result card and refreshes history', async () => {
    apiMock.uploadRepIntelligenceImport.mockResolvedValue({ ...detail(), matched_out_of_scope: undefined });
    render(<GenericRepIntelligencePane />);
    await screen.findByTestId('rep-intel-row-7');
    const submit = screen.getByTestId('rep-intel-submit') as HTMLButtonElement;
    expect(submit.disabled).toBe(true);
    expect((screen.getByTestId('rep-intel-file') as HTMLInputElement).accept).toBe('.csv');
    const file = new File(['customer_name,technology_name'], 'rep-notes.csv', { type: 'text/csv' });
    fireEvent.change(screen.getByTestId('rep-intel-file'), { target: { files: [file] } });
    expect(submit.disabled).toBe(false);
    fireEvent.click(submit);
    const sum = await screen.findByTestId('rep-intel-summary');
    expect(apiMock.uploadRepIntelligenceImport).toHaveBeenCalledWith(file);
    expect(sum.textContent).toContain('rep-notes.csv');
    expect(sum.textContent).toContain('Completed with issues');
    expect(sum.textContent).toContain('4 rows processed');
    expect(sum.textContent).toContain('2 imported');
    expect(sum.textContent).toContain('1 imported with issues');
    expect(sum.textContent).toContain('1 skipped');
    expect(sum.textContent).toContain('2 created');
    expect(sum.textContent).toContain('1 refreshed');
    await waitFor(() => expect(apiMock.listRepIntelligenceImports).toHaveBeenCalledTimes(2));
  });

  // customer-match skips get the non-blocking warning.
  it('warns about rows with no matching customer name or alias', async () => {
    apiMock.uploadRepIntelligenceImport.mockResolvedValue({ ...detail(), unmatched_customer_rows: 1 });
    render(<GenericRepIntelligencePane />);
    await screen.findByTestId('rep-intel-row-7');
    fireEvent.change(screen.getByTestId('rep-intel-file'), { target: { files: [new File(['x'], 'r.csv')] } });
    fireEvent.click(screen.getByTestId('rep-intel-submit'));
    const warn = await screen.findByTestId('rep-intel-unmatched-warning');
    expect(warn.textContent).toContain('1 row could not be imported — no matching customer name or alias');
  });

  it('no customer-match warning when every customer matched', async () => {
    apiMock.uploadRepIntelligenceImport.mockResolvedValue({ ...detail(), unmatched_customer_rows: 0 });
    render(<GenericRepIntelligencePane />);
    await screen.findByTestId('rep-intel-row-7');
    fireEvent.change(screen.getByTestId('rep-intel-file'), { target: { files: [new File(['x'], 'r.csv')] } });
    fireEvent.click(screen.getByTestId('rep-intel-submit'));
    await screen.findByTestId('rep-intel-summary');
    expect(screen.queryByTestId('rep-intel-unmatched-warning')).toBeNull();
  });

  it('renders history rows and opens the detail with issues, customer links and clean-row count', async () => {
    apiMock.getRepIntelligenceImport.mockResolvedValue(detail({ matched_out_of_scope: 2 }));
    const onOpenCustomer = vi.fn();
    render(<GenericRepIntelligencePane onOpenCustomer={onOpenCustomer} />);
    const hrow = await screen.findByTestId('rep-intel-row-7');
    expect(hrow.textContent).toContain('rep-notes.csv');
    expect(hrow.textContent).toContain('rep1');
    expect(hrow.textContent).toContain('Completed with issues');
    fireEvent.click(hrow);
    const issues = await screen.findByTestId('rep-intel-detail-issues');
    expect(apiMock.getRepIntelligenceImport).toHaveBeenCalledWith(7);
    const cells = within(issues).getByTestId('rep-intel-issue-2-0').textContent ?? '';
    for (const part of ['2', 'Acme Testing Corp', 'Gadget Suite', 'amount', 'amount_invalid', 'technology imported with amount unknown', 'warning', 'field_omitted']) {
      expect(cells).toContain(part);
    }
    const skipped = within(issues).getByTestId('rep-intel-issue-3-0').textContent ?? '';
    expect(skipped).toContain('Nowhere Ltd');
    expect(skipped).toContain('customer_unmatched');
    expect(skipped).toContain('row_skipped');
    expect(skipped).toContain('error');
    expect(screen.getByTestId('rep-intel-detail-clean').textContent).toContain('1 row imported with no issues');

    const customers = screen.getByTestId('rep-intel-detail-customers');
    fireEvent.click(within(customers).getByRole('button', { name: 'Open Acme Testing Corp' }));
    expect(onOpenCustomer).toHaveBeenCalledWith('Acme Testing Corp');
    expect(screen.getByTestId('rep-intel-out-of-scope').textContent).toContain('2 matched accounts outside your scope');
  });

  it('omits the out-of-scope note when the count is 0', async () => {
    apiMock.getRepIntelligenceImport.mockResolvedValue(detail());
    render(<GenericRepIntelligencePane />);
    fireEvent.click(await screen.findByTestId('rep-intel-row-7'));
    await screen.findByTestId('rep-intel-detail');
    expect(screen.queryByTestId('rep-intel-out-of-scope')).toBeNull();
  });

  it('shows source/issues/delete only when can_manage', async () => {
    apiMock.getRepIntelligenceImport.mockResolvedValue(detail({ can_manage: false }));
    render(<GenericRepIntelligencePane />);
    fireEvent.click(await screen.findByTestId('rep-intel-row-7'));
    await screen.findByTestId('rep-intel-detail');
    expect(screen.queryByTestId('rep-intel-source')).toBeNull();
    expect(screen.queryByTestId('rep-intel-issues-download')).toBeNull();
    expect(screen.queryByTestId('rep-intel-delete')).toBeNull();
  });

  it('downloads the source file and issue report when can_manage', async () => {
    const createUrl = vi.fn(() => 'blob:x');
    Object.assign(URL, { createObjectURL: createUrl, revokeObjectURL: vi.fn() });
    const clickSpy = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {});
    apiMock.getRepIntelligenceImport.mockResolvedValue(detail());
    apiMock.downloadRepIntelligenceSource.mockResolvedValue(new Blob(['a']));
    apiMock.downloadRepIntelligenceIssues.mockResolvedValue(new Blob(['b']));
    render(<GenericRepIntelligencePane />);
    fireEvent.click(await screen.findByTestId('rep-intel-row-7'));
    fireEvent.click(await screen.findByTestId('rep-intel-source'));
    await waitFor(() => expect(apiMock.downloadRepIntelligenceSource).toHaveBeenCalledWith(7));
    await waitFor(() => expect(clickSpy).toHaveBeenCalledTimes(1));
    fireEvent.click(screen.getByTestId('rep-intel-issues-download'));
    await waitFor(() => expect(apiMock.downloadRepIntelligenceIssues).toHaveBeenCalledWith(7));
    await waitFor(() => expect(clickSpy).toHaveBeenCalledTimes(2));
  });

  it('deletes after confirm then refreshes history; cancel does nothing', async () => {
    apiMock.getRepIntelligenceImport.mockResolvedValue(detail());
    apiMock.deleteRepIntelligenceImport.mockResolvedValue({ detail: 'Import deleted', deleted_rows: 3, deleted_technologies: 2 });
    render(<GenericRepIntelligencePane />);
    fireEvent.click(await screen.findByTestId('rep-intel-row-7'));
    const del = await screen.findByTestId('rep-intel-delete');

    const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValueOnce(false);
    fireEvent.click(del);
    expect(apiMock.deleteRepIntelligenceImport).not.toHaveBeenCalled();
    expect(screen.getByTestId('rep-intel-detail')).toBeTruthy();
    expect(apiMock.listRepIntelligenceImports).toHaveBeenCalledTimes(1);

    confirmSpy.mockReturnValueOnce(true);
    apiMock.listRepIntelligenceImports.mockResolvedValue([]);
    fireEvent.click(del);
    await waitFor(() => expect(apiMock.deleteRepIntelligenceImport).toHaveBeenCalledWith(7));
    const notice = await screen.findByTestId('rep-intel-notice');
    expect(notice.textContent).toContain('3 rows');
    expect(notice.textContent).toContain('2 technology records removed');
    await screen.findByTestId('rep-intel-history-empty');
    expect(screen.queryByTestId('rep-intel-detail')).toBeNull();
  });

  it('shows an error banner when the upload fails', async () => {
    apiMock.uploadRepIntelligenceImport.mockRejectedValue(new Error('Invalid CSV: bad header'));
    render(<GenericRepIntelligencePane />);
    await screen.findByTestId('rep-intel-row-7');
    fireEvent.change(screen.getByTestId('rep-intel-file'), { target: { files: [new File(['x'], 'bad.csv')] } });
    fireEvent.click(screen.getByTestId('rep-intel-submit'));
    expect((await screen.findByTestId('rep-intel-error')).textContent).toContain('Invalid CSV: bad header');
    expect(screen.queryByTestId('rep-intel-summary')).toBeNull();
  });

  it('shows the empty-history state and still offers the upload form (no denied state)', async () => {
    apiMock.listRepIntelligenceImports.mockResolvedValue([]);
    render(<GenericRepIntelligencePane />);
    await screen.findByTestId('rep-intel-history-empty');
    expect(screen.getByTestId('rep-intel-file')).toBeTruthy();
    expect(screen.getByTestId('rep-intel-submit')).toBeTruthy();
    expect(screen.getByTestId('rep-intel-template')).toBeTruthy();
    expect(screen.queryByTestId('intelligence-import-denied')).toBeNull();
    expect(screen.queryByText(/Requires sales manager/)).toBeNull();
  });

  it('keeps the upload form on a 403 history load (no manager-only state)', async () => {
    apiMock.listRepIntelligenceImports.mockRejectedValue(Object.assign(new Error('Forbidden'), { status: 403 }));
    render(<GenericRepIntelligencePane />);
    await screen.findByTestId('rep-intel-error');
    expect(screen.getByTestId('rep-intel-submit')).toBeTruthy();
    expect(screen.queryByText(/Requires sales manager/)).toBeNull();
  });
});
