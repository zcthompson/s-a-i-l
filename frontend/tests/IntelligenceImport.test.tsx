// Intelligence Import page — upload flow, 403 access-denied state, history
// rows + detail (matched/unmatched/out-of-scope), delete flow.
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, waitFor, within, cleanup } from '@testing-library/react';
import { IntelligenceImport } from '../src/pages/IntelligenceImport';
import { MemoryRouter, useLocation, useNavigate } from 'react-router-dom';

const { apiMock } = vi.hoisted(() => ({
  apiMock: {
    uploadIntelligenceImport: vi.fn(),
    listIntelligenceImports: vi.fn(),
    getIntelligenceImport: vi.fn(),
    deleteIntelligenceImport: vi.fn(),
    uploadRvToolsImport: vi.fn(),
    listRvToolsImports: vi.fn(),
    getRvToolsImport: vi.fn(),
    deleteRvToolsImport: vi.fn(),
    listCustomers: vi.fn(),
    listRepIntelligenceImports: vi.fn(),
    uploadRepIntelligenceImport: vi.fn(),
    getRepIntelligenceImport: vi.fn(),
    deleteRepIntelligenceImport: vi.fn(),
    downloadRepIntelligenceTemplate: vi.fn(),
    downloadRepIntelligenceSource: vi.fn(),
    downloadRepIntelligenceIssues: vi.fn(),
    listRedHatOpportunityImports: vi.fn(),
    uploadRedHatOpportunityImport: vi.fn(),
    getRedHatOpportunityUnmatched: vi.fn(),
    listNetSuiteImports: vi.fn(),
    uploadNetSuiteImport: vi.fn(),
    getNetSuiteImport: vi.fn(),
    getNetSuiteImportUnmatched: vi.fn(),
    rematchNetSuiteImport: vi.fn(),
  },
}));
vi.mock('../src/lib/api', () => ({ api: apiMock }));

const summary = {
  import_id: 1, file_name: 'report.csv', created_at: '2026-10-22T15:00:00+00:00',
  imported_by: 'admin', total_rows: 182, matched_accounts: 1, matched_rows: 4, unmatched_accounts: 2,
};
const detail = (over: Record<string, unknown> = {}) => ({
  ...summary, file_sha256: 'abc',
  matched: [{ customer_name: 'Example Customer B', customer_id: 85, account_name: 'Example Customer B', row_count: 4, knowledge_id: 9, est_acv_total: 123456, est_tcv_total: 234567, technologies: ['RHEL', 'OPENSHIFT'] }],
  unmatched: [{ account_name: 'Example Customer I', row_count: 39 }, { account_name: '(blank)', row_count: 1 }],
  pipeline_rows: [], matched_out_of_scope: 0, ...over,
});
const rvSummary = {
  import_id: 5, file_name: 'waltham.xlsx', customer_id: 90, customer_name: 'RVTools Sample — Waltham (temp)',
  created_customer: true, host_count: 3, vm_count: 13, vcenter: 'vc.example.com', vcenter_version: 'VMware vCenter Server 7.0.3',
  esxi_versions: ['6.7.0'], created_at: '2026-10-23T15:00:00+00:00', imported_by: 'admin',
};
const rvDetail = (over: Record<string, unknown> = {}) => ({
  ...rvSummary, rvtools_version: '4.4.5', collection_at: '2026-09-09T15:09:05',
  datastore_count: 1, license_count: 1, datacenters: ['DC1'],
  clusters: [{ name: 'CL1', hosts: 3, cpu_cores: 24, cpu_threads: 48, memory_mb: 262144, ha: true }],
  datastores: [{ name: 'DS1', type: 'VMFS', capacity_mib: 1048576, used_mib: 524288, free_mib: 524288, host_count: 3 }],
  guest_os_summary: { 'Microsoft Windows Server 2019': 8, 'Ubuntu Linux': 5 },
  summary: { total_cores: 24, total_memory_gb: 256, total_vcpus: 60, total_vm_memory_gb: 120.5, powered_on_vms: 11, datacenter_count: 1, cluster_count: 1 },
  technologies: ['HPE ProLiant DL360 Gen10', 'VMware ESXi 6.7.0'],
  hosts: [{ id: 11, host_name: 'esx01.example.com', datacenter: 'DC1', cluster: 'CL1', config_status: 'green', maintenance_mode: false, cpu_model: 'Xeon Gold', cpu_mhz: 2400, sockets: 2, cores_per_socket: 12, cores: 24, memory_mb: 262144, nics: 4, hbas: 2, vm_count: 5, vcpu_count: 20, vmotion: true, storage_vmotion: true, evc_mode: 'intel-skylake', esxi_version: 'VMware ESXi 6.7.0', vendor: 'HPE', model: 'ProLiant DL360 Gen10', service_tag: 'ABC123' }],
  licenses: [{ id: 21, name: 'VMware vSAN Advanced', cost_unit: 'cpuPackage', total: 6, used: 4, expiration: 'Never', features: 'vsan' }],
  vms: [{ id: 31, name: 'vm-one', power_state: 'poweredOn', cpus: 4, memory_mb: 8192, disks: 2, disk_capacity_mib: 102400, guest_os: 'Ubuntu Linux', host: 'esx01.example.com', cluster: 'CL1', datacenter: 'DC1', datastore: 'DS1', primary_ip: '10.0.0.5' }],
  vm_total: 250, vm_limit: 100, vm_offset: 0, ...over,
});
const pick = (id: string) =>
  fireEvent.change(screen.getByTestId('intelligence-import-source-select'), { target: { value: id } });
const forbidden = () => Object.assign(new Error('Forbidden'), { status: 403 });

beforeEach(() => {
  Object.values(apiMock).forEach(m => m.mockReset());
  apiMock.listIntelligenceImports.mockResolvedValue([summary]);
  apiMock.listRvToolsImports.mockResolvedValue([rvSummary]);
  apiMock.listCustomers.mockResolvedValue([{ id: 85, name: 'Example Customer B' }, { id: 86, name: 'Acme' }]);
  apiMock.listRepIntelligenceImports.mockResolvedValue([]);
  apiMock.listRedHatOpportunityImports.mockResolvedValue([]);
  apiMock.listNetSuiteImports.mockResolvedValue([]);
  window.history.replaceState(null, '', '/');
});
afterEach(() => { cleanup(); vi.restoreAllMocks(); window.history.replaceState(null, '', '/'); });

describe('IntelligenceImport', () => {
  it('uploads a CSV, renders the summary and refreshes history', async () => {
    apiMock.uploadIntelligenceImport.mockResolvedValue({ ...detail(), pipeline_rows: undefined });
    render(<IntelligenceImport />);
    await screen.findByTestId('intelligence-import-row-1');
    const submit = screen.getByTestId('intelligence-import-submit') as HTMLButtonElement;
    expect(submit.disabled).toBe(true);
    const file = new File(['a,b'], 'report.csv', { type: 'text/csv' });
    fireEvent.change(screen.getByTestId('intelligence-import-file'), { target: { files: [file] } });
    expect(submit.disabled).toBe(false);
    fireEvent.click(submit);
    const sum = await screen.findByTestId('intelligence-import-summary');
    expect(apiMock.uploadIntelligenceImport).toHaveBeenCalledWith(file);
    expect(sum.textContent).toContain('182 rows');
    expect(sum.textContent).toContain('1 matched accounts (4 rows)');
    expect(sum.textContent).toContain('2 unmatched accounts');
    await waitFor(() => expect(apiMock.listIntelligenceImports).toHaveBeenCalledTimes(2));
  });

  // Part 14 import remediation (operator rules 2026-11-01): unmatched rows
  // and unreadable amounts are non-blocking warnings on the result.
  it('warns about unmatched rows and unreadable amounts without blocking', async () => {
    apiMock.uploadIntelligenceImport.mockResolvedValue({
      ...detail({ skipped_rows: 40, amount_issues: [{ source_row: 3, column: 'Est. ACV Line Amount (USD)', value: 'TBD' }] }),
      pipeline_rows: undefined,
    });
    render(<IntelligenceImport />);
    await screen.findByTestId('intelligence-import-row-1');
    fireEvent.change(screen.getByTestId('intelligence-import-file'), { target: { files: [new File(['a'], 'r.csv')] } });
    fireEvent.click(screen.getByTestId('intelligence-import-submit'));
    const warn = await screen.findByTestId('intelligence-import-unmatched-warning');
    expect(warn.textContent).toContain('40 rows could not be imported — no matching customer name or alias');
    expect(warn.textContent).toContain('no customers were created');
    expect(screen.getByTestId('intelligence-import-amount-warning').textContent).toContain('1 amount could not be read');
    expect(screen.getByTestId('intelligence-import-summary').textContent).toContain('1 matched accounts (4 rows)');
  });

  it('no warning when every row matched', async () => {
    apiMock.uploadIntelligenceImport.mockResolvedValue({ ...detail({ skipped_rows: 0, amount_issues: [] }), pipeline_rows: undefined });
    render(<IntelligenceImport />);
    await screen.findByTestId('intelligence-import-row-1');
    fireEvent.change(screen.getByTestId('intelligence-import-file'), { target: { files: [new File(['a'], 'r.csv')] } });
    fireEvent.click(screen.getByTestId('intelligence-import-submit'));
    await screen.findByTestId('intelligence-import-summary');
    expect(screen.queryByTestId('intelligence-import-unmatched-warning')).toBeNull();
    expect(screen.queryByTestId('intelligence-import-amount-warning')).toBeNull();
  });

  it('detail shows matched-by spellings, unmatched reasons and unreadable amounts', async () => {
    apiMock.getIntelligenceImport.mockResolvedValue(detail({
      skipped_rows: 40,
      matched: [{ customer_name: 'Example Customer B', customer_id: 85, account_name: 'NorthwindF Corp', row_count: 4, knowledge_id: 9, est_acv_total: null, est_tcv_total: null, technologies: [], matched_by: 'name',
        supplied_names: [{ name: 'Example Customer B', row_count: 3, matched_by: 'name' }, { name: 'NorthwindF Corp', row_count: 1, matched_by: 'alias' }] }],
      unmatched: [{ account_name: 'Example Customer I', row_count: 39, reason: 'unmatched' }, { account_name: 'Dup Co', row_count: 1, reason: 'ambiguous' }],
      amount_issues: [{ source_row: 7, column: 'Est. TCV Line Amount (USD)', value: 'TBD' }],
    }));
    render(<IntelligenceImport />);
    fireEvent.click(await screen.findByTestId('intelligence-import-row-1'));
    const by = await screen.findByTestId('intelligence-import-matched-by-85');
    expect(by.textContent).toBe('name “Example Customer B” (3), alias “NorthwindF Corp” (1)');
    expect(screen.getByTestId('intelligence-import-unmatched-Example Customer I').textContent).toContain('No matching customer name or alias');
    expect(screen.getByTestId('intelligence-import-unmatched-Dup Co').textContent).toContain('Matches more than one customer');
    expect(screen.getByTestId('intelligence-import-detail-unmatched-warning').textContent).toContain('40 rows could not be imported');
    expect(screen.getByTestId('intelligence-import-detail-amounts').textContent).toContain('TBD');
  });

  it('shows a clean access-denied state on 403 (no raw error)', async () => {
    apiMock.listIntelligenceImports.mockRejectedValue(forbidden());
    render(<IntelligenceImport />);
    const denied = await screen.findByTestId('intelligence-import-denied');
    expect(denied.textContent).toContain('Requires sales manager or higher');
    expect(screen.queryByTestId('intelligence-import-error')).toBeNull();
    expect(screen.queryByTestId('intelligence-import-submit')).toBeNull();
  });

  it('shows access-denied when the upload itself 403s', async () => {
    apiMock.uploadIntelligenceImport.mockRejectedValue(forbidden());
    render(<IntelligenceImport />);
    await screen.findByTestId('intelligence-import-row-1');
    fireEvent.change(screen.getByTestId('intelligence-import-file'), { target: { files: [new File(['x'], 'r.csv')] } });
    fireEvent.click(screen.getByTestId('intelligence-import-submit'));
    expect((await screen.findByTestId('intelligence-import-denied')).textContent).toContain('Requires sales manager or higher');
  });

  it('renders history rows and the detail tables with customer link', async () => {
    apiMock.getIntelligenceImport.mockResolvedValue(detail({ matched_out_of_scope: 2 }));
    const onOpenCustomer = vi.fn();
    render(<IntelligenceImport onOpenCustomer={onOpenCustomer} />);
    const row = await screen.findByTestId('intelligence-import-row-1');
    expect(row.textContent).toContain('report.csv');
    expect(row.textContent).toContain('admin');
    expect(row.textContent).toContain('182');
    fireEvent.click(row);
    const matched = await screen.findByTestId('intelligence-import-detail-matched');
    expect(apiMock.getIntelligenceImport).toHaveBeenCalledWith(1);
    const m = within(matched).getByTestId('intelligence-import-matched-85');
    expect(m.textContent).toContain('Example Customer B');
    expect(m.textContent).toContain('$123,456');
    expect(m.textContent).toContain('$234,567');
    expect(within(matched).getByTestId('intelligence-import-matched-tech-85').textContent).toBe('RHEL, OPENSHIFT');
    fireEvent.click(within(m).getByRole('button', { name: 'Open Example Customer B' }));
    expect(onOpenCustomer).toHaveBeenCalledWith('Example Customer B');
    expect(screen.getByTestId('intelligence-import-out-of-scope').textContent).toContain('2 matched accounts outside your scope');
    const unmatched = screen.getByTestId('intelligence-import-detail-unmatched');
    expect(within(unmatched).getByText('Example Customer I')).toBeTruthy();
    expect(within(unmatched).getByText('39')).toBeTruthy();
  });

  it('omits the out-of-scope note when the count is 0', async () => {
    apiMock.getIntelligenceImport.mockResolvedValue(detail());
    render(<IntelligenceImport />);
    fireEvent.click(await screen.findByTestId('intelligence-import-row-1'));
    await screen.findByTestId('intelligence-import-detail');
    expect(screen.queryByTestId('intelligence-import-out-of-scope')).toBeNull();
  });

  it('deletes after confirm, then refreshes history; cancel does nothing', async () => {
    apiMock.getIntelligenceImport.mockResolvedValue(detail());
    apiMock.deleteIntelligenceImport.mockResolvedValue({ detail: 'Import deleted', deleted_rows: 4, deleted_knowledge: 1, deleted_technologies: 2 });
    render(<IntelligenceImport />);
    fireEvent.click(await screen.findByTestId('intelligence-import-row-1'));
    const del = await screen.findByTestId('intelligence-import-delete');

    const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValueOnce(false);
    fireEvent.click(del);
    expect(apiMock.deleteIntelligenceImport).not.toHaveBeenCalled();

    confirmSpy.mockReturnValueOnce(true);
    apiMock.listIntelligenceImports.mockResolvedValue([]);
    fireEvent.click(del);
    await waitFor(() => expect(apiMock.deleteIntelligenceImport).toHaveBeenCalledWith(1));
    expect((await screen.findByTestId('intelligence-import-notice')).textContent).toContain('4 pipeline rows');
    expect(screen.getByTestId('intelligence-import-notice').textContent).toContain('2 technology records removed');
    await screen.findByTestId('intelligence-import-history-empty');
    expect(screen.queryByTestId('intelligence-import-detail')).toBeNull();
  });
});

function RouterProbe() {
  const location = useLocation();
  const navigate = useNavigate();
  return <><output data-testid="router-search">{location.search}</output><button onClick={() => navigate('/?view=gi-import&source=rep&extra=1')}>Open rep link</button><button onClick={() => navigate(-1)}>Back</button><button onClick={() => navigate('/?view=gi-import&source=redhat&import=2')}>Open second record</button></>;
}

describe('IntelligenceImport — source selector', () => {
  it('opens a linked pipeline record and restores the previous history selection', async () => {
    apiMock.getIntelligenceImport.mockResolvedValue(detail());
    render(<MemoryRouter initialEntries={['/?view=gi-import&source=redhat']}><RouterProbe /><IntelligenceImport /></MemoryRouter>);
    await screen.findByTestId('intelligence-import-row-1');
    fireEvent.click(screen.getByTestId('intelligence-import-row-1'));
    await screen.findByTestId('intelligence-import-detail');
    expect(new URLSearchParams(screen.getByTestId('router-search').textContent ?? '').get('import')).toBe('1');
    fireEvent.click(screen.getByText('Back'));
    await waitFor(() => expect(screen.queryByTestId('intelligence-import-detail')).toBeNull());
  });

  it('restores linked RVTools and rep details, and clears the record when switching sources', async () => {
    apiMock.getRvToolsImport.mockResolvedValue(rvDetail());
    apiMock.getRepIntelligenceImport.mockResolvedValue({ import_id: 7, file_name: 'rep.csv', status: 'completed', rows: [], matched: [], can_manage: false });
    render(<MemoryRouter initialEntries={['/?view=gi-import&source=vmware&import=5']}><RouterProbe /><IntelligenceImport /></MemoryRouter>);
    await screen.findByTestId('rvtools-import-detail');
    expect(apiMock.getRvToolsImport).toHaveBeenCalledWith(5, 100, 0);
    pick('rep');
    expect(new URLSearchParams(screen.getByTestId('router-search').textContent ?? '').has('import')).toBe(false);
    expect(apiMock.getRepIntelligenceImport).not.toHaveBeenCalled();
  });

  it('ignores a late response for a previously selected record', async () => {
    let finishFirst!: (value: ReturnType<typeof detail>) => void;
    apiMock.getIntelligenceImport.mockImplementation((id: number) => id === 1
      ? new Promise((resolve) => { finishFirst = resolve; })
      : Promise.resolve(detail({ import_id: 2, file_name: 'second.csv' })));
    render(<MemoryRouter initialEntries={['/?view=gi-import&source=redhat&import=1']}><RouterProbe /><IntelligenceImport /></MemoryRouter>);
    await waitFor(() => expect(apiMock.getIntelligenceImport).toHaveBeenCalledWith(1));
    fireEvent.click(screen.getByText('Open second record'));
    await waitFor(() => expect(screen.getByTestId('intelligence-import-detail').textContent).toContain('second.csv'));
    finishFirst(detail({ file_name: 'first.csv' }));
    await waitFor(() => expect(screen.getByTestId('intelligence-import-detail').textContent).toContain('second.csv'));
  });

  it('loads a rep detail directly and reports inaccessible records without stale detail', async () => {
    apiMock.getRepIntelligenceImport.mockRejectedValue(Object.assign(new Error('Forbidden'), { status: 403 }));
    render(<MemoryRouter initialEntries={['/?view=gi-import&source=rep&import=7']}><IntelligenceImport /></MemoryRouter>);
    expect(await screen.findByText('Import not found or unavailable.')).toBeTruthy();
    expect(apiMock.getRepIntelligenceImport).toHaveBeenCalledWith(7);
    expect(screen.queryByTestId('rep-intel-detail')).toBeNull();
    expect(screen.getByText(/Refreshing or leaving this page clears/)).toBeTruthy();
  });

  it('keeps source synchronized with the router and follows external URL changes', async () => {
    render(<MemoryRouter initialEntries={['/?view=gi-import&source=redhat&extra=1']}><RouterProbe /><IntelligenceImport /></MemoryRouter>);
    pick('vmware');
    expect(new URLSearchParams(screen.getByTestId('router-search').textContent ?? '').get('source')).toBe('vmware');
    expect(new URLSearchParams(screen.getByTestId('router-search').textContent ?? '').get('extra')).toBe('1');
    fireEvent.click(screen.getByText('Open rep link'));
    expect((screen.getByTestId('intelligence-import-source-select') as HTMLSelectElement).value).toBe('rep');
  });

  it('renders a labelled Import source select with the registry optgroups', () => {
    render(<IntelligenceImport />);
    const select = screen.getByLabelText('Import source') as HTMLSelectElement;
    expect(select).toBe(screen.getByTestId('intelligence-import-source-select'));
    expect(select.tagName).toBe('SELECT');
    const groups = Array.from(select.querySelectorAll('optgroup')).map((g) => ({
      label: g.getAttribute('label'),
      options: Array.from(g.querySelectorAll('option')).map((o) => [o.value, o.textContent]),
    }));
    expect(groups).toEqual([
      { label: 'Vendor/Distributor Provided', options: [['redhat', 'Red Hat Partner Pipeline Import'], ['redhat-opportunity', 'Red Hat Opportunity Import']] },
      { label: 'Customer Provided Accepted Imports', options: [['vmware', 'VMware RVTools Import']] },
      { label: 'Rep Provided', options: [['rep', 'Generic Account Intelligence Import (CSV)']] },
      { label: 'NetSuite', options: [['netsuite', 'NetSuite Intelligence Import']] },
    ]);
    expect(screen.queryByTestId('intelligence-import-vendors')).toBeNull();
  });

  it('imports a Red Hat opportunity workbook and reports unmatched rows', async () => {
    apiMock.uploadRedHatOpportunityImport.mockResolvedValue({ import_id: 4, total_rows: 2,
      matched_rows: 1, matched_accounts: 1, skipped: [{ source_row: 6, account: 'Synthetic missing', reason: 'No unambiguous accessible customer name or alias' }] });
    render(<IntelligenceImport />);
    pick('redhat-opportunity');
    const file = new File(['synthetic'], 'report.xlsx');
    fireEvent.change(screen.getByLabelText('Opportunity workbook (.xlsx)'), { target: { files: [file] } });
    fireEvent.click(screen.getByRole('button', { name: 'Import workbook' }));
    expect((await screen.findByRole('status')).textContent).toContain('Imported 1 of 2 rows');
    expect(screen.getByText(/Synthetic missing/)).toBeTruthy();
    expect(apiMock.uploadRedHatOpportunityImport).toHaveBeenCalledWith(file);
  });

  it('defaults to Red Hat and switches panes, unmounting the previous one', async () => {
    render(<IntelligenceImport />);
    const select = screen.getByTestId('intelligence-import-source-select') as HTMLSelectElement;
    expect(select.value).toBe('redhat');
    await screen.findByTestId('intelligence-import-row-1');
    expect(screen.queryByTestId('rvtools-import')).toBeNull();
    expect(screen.queryByTestId('rep-intel')).toBeNull();

    pick('rep');
    await screen.findByTestId('rep-intel');
    expect(screen.queryByTestId('intelligence-import-redhat')).toBeNull();
    expect(screen.queryByTestId('intelligence-import-upload')).toBeNull();

    pick('vmware');
    await screen.findByTestId('rvtools-import-row-5');
    expect(screen.queryByTestId('rep-intel')).toBeNull();

    pick('redhat');
    await screen.findByTestId('intelligence-import-row-1');
    expect(screen.queryByTestId('rvtools-import')).toBeNull();
  });

  it('seeds the source from ?source= and keeps other params on change (replaceState, no push)', async () => {
    window.history.replaceState(null, '', '/?view=gi-import&source=rep');
    const pushSpy = vi.spyOn(window.history, 'pushState');
    render(<IntelligenceImport />);
    expect((screen.getByTestId('intelligence-import-source-select') as HTMLSelectElement).value).toBe('rep');
    await screen.findByTestId('rep-intel');

    pick('vmware');
    await screen.findByTestId('rvtools-import-row-5');
    const params = new URLSearchParams(window.location.search);
    expect(params.get('source')).toBe('vmware');
    expect(params.get('view')).toBe('gi-import');
    expect(pushSpy).not.toHaveBeenCalled();
  });

  it('falls back to Red Hat on an unknown ?source=', async () => {
    window.history.replaceState(null, '', '/?source=bogus');
    render(<IntelligenceImport />);
    expect((screen.getByTestId('intelligence-import-source-select') as HTMLSelectElement).value).toBe('redhat');
    await screen.findByTestId('intelligence-import-row-1');
  });

  it('shows the accepted file types of the selected source', async () => {
    render(<IntelligenceImport />);
    const formats = screen.getByTestId('intelligence-import-source-formats');
    expect(formats.textContent).toContain('.csv');
    pick('vmware');
    expect(formats.textContent).toContain('.xlsx, .xlsm');
    pick('rep');
    expect(formats.textContent).toContain('.csv');
    expect(formats.textContent).not.toContain('.xlsx');
    await screen.findByTestId('rep-intel');
    pick('netsuite');
    expect(formats.textContent).toContain('.csv, .xlsx');
    await screen.findByTestId('netsuite-import');
  });
});

describe('IntelligenceImport — VMware RVTools pane', () => {
  const open = async () => {
    render(<IntelligenceImport />);
    pick('vmware');
    await screen.findByTestId('rvtools-import-row-5');
  };

  // Part 14 import remediation: the target is an existing customer only
  // (picked by name or alias) — there is no new/temporary customer input.
  it('target is an existing customer only and gates submit', async () => {
    await open();
    await waitFor(() => expect(screen.getByRole('option', { name: 'Acme' })).toBeTruthy());
    const submit = screen.getByTestId('rvtools-import-submit') as HTMLButtonElement;
    const select = screen.getByTestId('rvtools-import-customer') as HTMLSelectElement;
    expect(screen.queryByTestId('rvtools-import-new-customer')).toBeNull();
    expect((screen.getByTestId('rvtools-import-file') as HTMLInputElement).accept).toBe('.xlsx,.xlsm');
    expect(screen.getByTestId('rvtools-import-target-help').textContent).toContain('Imports never create customers');
    fireEvent.change(screen.getByTestId('rvtools-import-file'), { target: { files: [new File(['x'], 'a.xlsx')] } });
    expect(submit.disabled).toBe(true); // no target yet
    fireEvent.change(select, { target: { value: 'Acme' } });
    expect(submit.disabled).toBe(false);
    fireEvent.change(select, { target: { value: '' } });
    expect(submit.disabled).toBe(true);
  });

  it('uploads against the picked customer and shows the result card', async () => {
    apiMock.uploadRvToolsImport.mockResolvedValue(rvDetail({ created_customer: false }));
    await open();
    await waitFor(() => expect(screen.getByRole('option', { name: 'Acme' })).toBeTruthy());
    const file = new File(['x'], 'waltham.xlsx');
    fireEvent.change(screen.getByTestId('rvtools-import-file'), { target: { files: [file] } });
    fireEvent.change(screen.getByTestId('rvtools-import-customer'), { target: { value: 'Acme' } });
    fireEvent.click(screen.getByTestId('rvtools-import-submit'));
    const sum = await screen.findByTestId('rvtools-import-summary');
    expect(apiMock.uploadRvToolsImport).toHaveBeenCalledWith(file, { customer_name: 'Acme' });
    expect(sum.textContent).toContain('3 hosts, 13 VMs, 1 datastores, 1 licenses');
    expect(screen.getByTestId('rvtools-import-summary-versions').textContent).toContain('ESXi 6.7.0');
    expect(screen.getByTestId('rvtools-import-summary-tech').textContent).toContain('2 technologies recorded');
    await waitFor(() => expect(apiMock.listRvToolsImports).toHaveBeenCalledTimes(2));
  });

  it('uploads against an existing customer without a temp notice', async () => {
    apiMock.uploadRvToolsImport.mockResolvedValue(rvDetail({ created_customer: false, customer_name: 'Acme' }));
    await open();
    await waitFor(() => expect(screen.getByRole('option', { name: 'Acme' })).toBeTruthy());
    const file = new File(['x'], 'a.xlsx');
    fireEvent.change(screen.getByTestId('rvtools-import-file'), { target: { files: [file] } });
    fireEvent.change(screen.getByTestId('rvtools-import-customer'), { target: { value: 'Acme' } });
    fireEvent.click(screen.getByTestId('rvtools-import-submit'));
    await screen.findByTestId('rvtools-import-summary');
    expect(apiMock.uploadRvToolsImport).toHaveBeenCalledWith(file, { customer_name: 'Acme' });
    expect(screen.queryByTestId('rvtools-import-temp-notice')).toBeNull();
  });

  it('renders history (created flag, customer link) and the full detail', async () => {
    apiMock.getRvToolsImport.mockResolvedValue(rvDetail());
    const onOpenCustomer = vi.fn();
    render(<IntelligenceImport onOpenCustomer={onOpenCustomer} />);
    pick('vmware');
    const row = await screen.findByTestId('rvtools-import-row-5');
    expect(row.textContent).toContain('waltham.xlsx');
    expect(row.textContent).toContain('VMware vCenter Server 7.0.3');
    expect(row.textContent).toContain('6.7.0');
    expect(screen.getByTestId('rvtools-import-created-5')).toBeTruthy();
    fireEvent.click(within(row).getByRole('button', { name: 'Open RVTools Sample — Waltham (temp)' }));
    expect(onOpenCustomer).toHaveBeenCalledWith('RVTools Sample — Waltham (temp)');
    expect(apiMock.getRvToolsImport).not.toHaveBeenCalled(); // link click does not open detail
    fireEvent.click(row);
    await screen.findByTestId('rvtools-import-detail');
    expect(apiMock.getRvToolsImport).toHaveBeenCalledWith(5, 100, 0);
    expect(screen.getByTestId('rvtools-import-detail-strip').textContent).toContain('24 cores');
    expect(screen.getByTestId('rvtools-import-host-11').textContent).toContain('HPE ProLiant DL360 Gen10');
    expect(screen.getByTestId('rvtools-import-host-11').textContent).toContain('ABC123');
    expect(screen.getByTestId('rvtools-import-license-21').textContent).toContain('VMware vSAN Advanced');
    expect(screen.getByTestId('rvtools-import-cluster-CL1').textContent).toContain('256.0 GB');
    expect(screen.getByTestId('rvtools-import-datastore-DS1').textContent).toContain('1.00 TB');
    expect(screen.getByTestId('rvtools-import-guestos-table').textContent).toContain('Microsoft Windows Server 2019');
    expect(screen.getByTestId('rvtools-import-vm-31').textContent).toContain('10.0.0.5');
    expect(screen.getByTestId('rvtools-import-detail-technologies').textContent).toContain('VMware ESXi 6.7.0');
  });

  it('paginates VMs with prev/next using vm_limit/vm_offset', async () => {
    apiMock.getRvToolsImport.mockResolvedValueOnce(rvDetail());
    await open();
    fireEvent.click(screen.getByTestId('rvtools-import-row-5'));
    await screen.findByTestId('rvtools-import-detail');
    expect(screen.getByTestId('rvtools-import-vm-range').textContent).toBe('1–1 of 250');
    expect((screen.getByTestId('rvtools-import-vm-prev') as HTMLButtonElement).disabled).toBe(true);
    apiMock.getRvToolsImport.mockResolvedValueOnce(rvDetail({ vm_offset: 100 }));
    fireEvent.click(screen.getByTestId('rvtools-import-vm-next'));
    await waitFor(() => expect(apiMock.getRvToolsImport).toHaveBeenLastCalledWith(5, 100, 100));
    await waitFor(() => expect(screen.getByTestId('rvtools-import-vm-range').textContent).toBe('101–101 of 250'));
    expect((screen.getByTestId('rvtools-import-vm-prev') as HTMLButtonElement).disabled).toBe(false);
    apiMock.getRvToolsImport.mockResolvedValueOnce(rvDetail({ vm_offset: 200 }));
    fireEvent.click(screen.getByTestId('rvtools-import-vm-next'));
    await waitFor(() => expect((screen.getByTestId('rvtools-import-vm-next') as HTMLButtonElement).disabled).toBe(true));
  });

  it('shows a scope message on a 404 detail', async () => {
    apiMock.getRvToolsImport.mockRejectedValue(Object.assign(new Error('Not found'), { status: 404 }));
    await open();
    fireEvent.click(screen.getByTestId('rvtools-import-row-5'));
    expect((await screen.findByTestId('rvtools-import-error')).textContent).toContain('outside your scope');
    expect(screen.queryByTestId('rvtools-import-detail')).toBeNull();
  });

  it('deletes after confirm and keeps the customer; cancel does nothing', async () => {
    apiMock.getRvToolsImport.mockResolvedValue(rvDetail());
    apiMock.deleteRvToolsImport.mockResolvedValue({ detail: 'ok', deleted_hosts: 3, deleted_vms: 13, deleted_licenses: 1, deleted_knowledge: 1, deleted_technologies: 2, temp_customer_kept: true });
    await open();
    fireEvent.click(screen.getByTestId('rvtools-import-row-5'));
    const del = await screen.findByTestId('rvtools-import-delete');
    const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValueOnce(false);
    fireEvent.click(del);
    expect(apiMock.deleteRvToolsImport).not.toHaveBeenCalled();
    confirmSpy.mockReturnValueOnce(true);
    apiMock.listRvToolsImports.mockResolvedValue([]);
    fireEvent.click(del);
    await waitFor(() => expect(apiMock.deleteRvToolsImport).toHaveBeenCalledWith(5));
    const notice = await screen.findByTestId('rvtools-import-notice');
    expect(notice.textContent).toContain('13 VMs');
    expect(notice.textContent).toContain('customer account was kept');
    await screen.findByTestId('rvtools-import-history-empty');
    expect(screen.queryByTestId('rvtools-import-detail')).toBeNull();
  });

  it('shows the access-denied state on 403 (list and upload)', async () => {
    apiMock.listRvToolsImports.mockRejectedValue(forbidden());
    render(<IntelligenceImport />);
    pick('vmware');
    const denied = await screen.findByTestId('rvtools-import-denied');
    expect(denied.textContent).toContain('Requires sales manager or higher');
    expect(screen.queryByTestId('rvtools-import-error')).toBeNull();
    expect(screen.queryByTestId('rvtools-import-submit')).toBeNull();
  });

  it('shows access-denied when the RVTools upload itself 403s', async () => {
    apiMock.uploadRvToolsImport.mockRejectedValue(forbidden());
    await open();
    await waitFor(() => expect(screen.getByRole('option', { name: 'Acme' })).toBeTruthy());
    fireEvent.change(screen.getByTestId('rvtools-import-file'), { target: { files: [new File(['x'], 'a.xlsx')] } });
    fireEvent.change(screen.getByTestId('rvtools-import-customer'), { target: { value: 'Acme' } });
    fireEvent.click(screen.getByTestId('rvtools-import-submit'));
    expect((await screen.findByTestId('rvtools-import-denied')).textContent).toContain('Requires sales manager or higher');
  });
});

describe('IntelligenceImport — NetSuite pane', () => {
  const open = async () => {
    render(<IntelligenceImport />);
    pick('netsuite');
    await screen.findByTestId('netsuite-import');
  };

  it('switches to the NetSuite pane and unmounts the previous ones', async () => {
    render(<IntelligenceImport />);
    await screen.findByTestId('intelligence-import-row-1');
    pick('netsuite');
    await screen.findByTestId('netsuite-import');
    expect(screen.queryByTestId('intelligence-import-redhat')).toBeNull();
    expect(screen.queryByTestId('rep-intel')).toBeNull();
    pick('redhat');
    await screen.findByTestId('intelligence-import-row-1');
    expect(screen.queryByTestId('netsuite-import')).toBeNull();
  });

  it('shows the manager-only denied state when the NetSuite history 403s', async () => {
    apiMock.listNetSuiteImports.mockRejectedValue(forbidden());
    await open();
    const denied = await screen.findByTestId('netsuite-import-denied');
    expect(denied.textContent).toContain('Requires a system admin or sales manager');
    expect(screen.queryByTestId('netsuite-import-error')).toBeNull();
  });
});
