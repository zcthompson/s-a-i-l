/**
 * RVTools existing-customer picker: a filter input narrows the
 * native select by name OR alias; option value/label stay the customer name
 * and the submission contract (customer_name) is unchanged. Synthetic names.
 */
import { describe, it, expect, vi, afterEach, beforeEach } from 'vitest';
import { render, screen, cleanup, fireEvent, waitFor } from '@testing-library/react';

const { apiMock } = vi.hoisted(() => ({
  apiMock: {
    listRvToolsImports: vi.fn(),
    listCustomers: vi.fn(),
    uploadRvToolsImport: vi.fn(),
    getRvToolsImport: vi.fn(),
    deleteRvToolsImport: vi.fn(),
  },
}));
vi.mock('../src/lib/api', () => ({ api: apiMock }));

import { VMwareRvToolsPane } from '../src/components/intelligence-import/VMwareRvToolsPane';

const cust = (id: number, name: string, aliases: string[] = []) => ({
  id, name, aliases, description: null, vertical: null, created_at: '', updated_at: '', departments: [],
});

beforeEach(() => {
  apiMock.listRvToolsImports.mockReset().mockResolvedValue([]);
  apiMock.listCustomers.mockReset().mockResolvedValue([
    cust(1, 'Acme Corp', ['Roadrunner Supply']),
    cust(2, 'Borealis Energy'),
    cust(3, 'Cobalt Systems', ['CSI']),
  ]);
  apiMock.uploadRvToolsImport.mockReset();
});
afterEach(cleanup);

const filter = () => screen.getByTestId('rvtools-import-customer-filter') as HTMLInputElement;
const select = () => screen.getByTestId('rvtools-import-customer') as HTMLSelectElement;
const options = () => Array.from(select().options).filter(o => o.value !== '').map(o => [o.value, o.textContent]);
const open = async () => {
  render(<VMwareRvToolsPane />);
  await waitFor(() => expect(options()).toHaveLength(3));
};

describe('RVTools target picker', () => {
  it('shows loading, then an error and recovers on retry', async () => {
    let rejectLoad!: (error: Error) => void;
    apiMock.listCustomers.mockReturnValueOnce(new Promise((_resolve, reject) => { rejectLoad = reject; }));
    render(<VMwareRvToolsPane />);
    expect(await screen.findByText('Loading customers…')).toBeTruthy();
    expect(select().disabled).toBe(true);
    rejectLoad(new Error('offline'));
    expect(await screen.findByText(/Could not load customers/)).toBeTruthy();
    expect(select().disabled).toBe(true);
    fireEvent.click(screen.getByRole('button', { name: 'Retry loading customers' }));
    await waitFor(() => expect(options()).toHaveLength(3));
    expect(select().disabled).toBe(false);
    expect(screen.queryByText(/Could not load customers/)).toBeNull();
  });

  it('distinguishes no accessible customers from no filter matches', async () => {
    apiMock.listCustomers.mockResolvedValueOnce([]);
    const view = render(<VMwareRvToolsPane />);
    expect(await screen.findByText('No accessible customers are available.')).toBeTruthy();
    view.unmount();
    await open();
    fireEvent.change(filter(), { target: { value: 'no match' } });
    expect(screen.getByText('No customers match this filter.')).toBeTruthy();
    expect(screen.queryByText('No accessible customers are available.')).toBeNull();
  });

  it('has the labelled filter input', async () => {
    await open();
    expect(screen.getByLabelText('Filter customers by name or alias')).toBe(filter());
    expect(screen.getByTestId('rvtools-import-target-help').textContent).toContain('then select the customer');
    expect(screen.getByTestId('rvtools-import-target-help').textContent).toContain('does not choose a customer');
  });

  it('an alias substring query shows the matching customer (value/label = name)', async () => {
    await open();
    fireEvent.change(filter(), { target: { value: 'roadrun' } });
    expect(options()).toEqual([['Acme Corp', 'Acme Corp — matching alias: Roadrunner Supply']]);
    fireEvent.change(filter(), { target: { value: 'csi' } });
    expect(options()).toEqual([['Cobalt Systems', 'Cobalt Systems — matching alias: CSI']]);
  });

  it('a name query still works (case-insensitive)', async () => {
    await open();
    fireEvent.change(filter(), { target: { value: 'BOREAL' } });
    expect(options()).toEqual([['Borealis Energy', 'Borealis Energy']]);
  });

  it('matches names and aliases despite case and internal whitespace differences', async () => {
    apiMock.listCustomers.mockResolvedValueOnce([
      cust(1, 'Acme  Corp', ['Roadrunner\t Supply']),
      cust(2, 'Borealis Energy'),
    ]);
    render(<VMwareRvToolsPane />);
    await waitFor(() => expect(options()).toHaveLength(2));
    fireEvent.change(filter(), { target: { value: '  ACME\t CORP  ' } });
    expect(options()).toEqual([['Acme  Corp', 'Acme  Corp']]);
    fireEvent.change(filter(), { target: { value: 'roadRUNNER   supply' } });
    expect(options()).toEqual([['Acme  Corp', 'Acme  Corp — matching alias: Roadrunner\t Supply']]);
  });

  it('an empty query shows all options', async () => {
    await open();
    fireEvent.change(filter(), { target: { value: 'zzz' } });
    expect(options()).toEqual([]);
    fireEvent.change(filter(), { target: { value: '' } });
    expect(options().map(o => o[0])).toEqual(['Acme Corp', 'Borealis Energy', 'Cobalt Systems']);
  });

  it('clears the selected import target when the filter changes', async () => {
    await open();
    fireEvent.change(screen.getByTestId('rvtools-import-file'), { target: { files: [new File(['x'], 'a.xlsx')] } });
    fireEvent.change(select(), { target: { value: 'Acme Corp' } });
    const submit = screen.getByTestId('rvtools-import-submit') as HTMLButtonElement;
    expect(submit.disabled).toBe(false);
    fireEvent.change(filter(), { target: { value: 'boreal' } });
    expect(select().value).toBe('');
    expect(options()).toEqual([['Borealis Energy', 'Borealis Energy']]);
    expect(submit.disabled).toBe(true);
    fireEvent.change(select(), { target: { value: 'Borealis Energy' } });
    expect(submit.disabled).toBe(false);
    fireEvent.change(filter(), { target: { value: 'no matches' } });
    expect(select().value).toBe('');
    expect(options()).toEqual([]);
    expect(submit.disabled).toBe(true);
    fireEvent.click(submit);
    expect(apiMock.uploadRvToolsImport).not.toHaveBeenCalled();
  });

  it('submits customer_name exactly as before after an alias-filtered pick', async () => {
    apiMock.uploadRvToolsImport.mockResolvedValue({
      import_id: 9, file_name: 'a.xlsx', customer_id: 1, customer_name: 'Acme Corp', created_customer: false,
      host_count: 0, vm_count: 0, datastore_count: 0, license_count: 0, esxi_versions: [], technologies: [],
      created_at: '', imported_by: 'x', hosts: [], licenses: [], vms: [], clusters: [], datastores: [],
      datacenters: [], guest_os_summary: {}, summary: {}, vm_total: 0, vm_limit: 100, vm_offset: 0,
    });
    await open();
    const file = new File(['x'], 'a.xlsx');
    fireEvent.change(screen.getByTestId('rvtools-import-file'), { target: { files: [file] } });
    fireEvent.change(filter(), { target: { value: 'roadrunner' } });
    fireEvent.change(select(), { target: { value: 'Acme Corp' } });
    fireEvent.click(screen.getByTestId('rvtools-import-submit'));
    await waitFor(() => expect(apiMock.uploadRvToolsImport).toHaveBeenCalledWith(file, { customer_name: 'Acme Corp' }));
  });
});
