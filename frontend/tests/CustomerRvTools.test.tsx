// CustomerRvTools panel — totals strip, clusters, technologies, source line,
// empty state, and error surface.
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, cleanup } from '@testing-library/react';
import { CustomerRvTools } from '../src/components/CustomerRvTools';

const { apiMock } = vi.hoisted(() => ({ apiMock: { getCustomerRvTools: vi.fn() } }));
vi.mock('../src/lib/api', () => ({ api: apiMock }));

const summary = { total_cores: 24, total_memory_gb: 256, total_vcpus: 60, total_vm_memory_gb: 120.5, powered_on_vms: 11, datacenter_count: 1, cluster_count: 1 };
const full = (over: Record<string, unknown> = {}) => ({
  customer_name: 'Acme', import_id: 5, source_file: 'waltham.xlsx', imported_at: '2026-10-23T15:00:00+00:00',
  rvtools_version: '4.4.5', vcenter: 'vc.example.com', vcenter_version: 'VMware vCenter Server 7.0.3',
  esxi_versions: ['6.7.0', '7.0.3'], host_count: 3, vm_count: 13, datastore_count: 2, license_count: 1,
  datacenters: ['DC1'], clusters: [{ name: 'CL1', hosts: 3, cpu_cores: 24, cpu_threads: 48, memory_mb: 262144, ha: true }],
  hosts_preview: [
    { id: 1, host_name: 'esx-01', datacenter: 'DC1', cluster: 'CL1', config_status: 'green', maintenance_mode: false,
      cpu_model: 'Intel Xeon Silver 4110', cpu_mhz: 2100, sockets: 2, cores_per_socket: 8, cores: 16, memory_mb: 196608,
      nics: 8, hbas: 9, vm_count: 5, vcpu_count: 20, vmotion: true, storage_vmotion: true, evc_mode: null,
      esxi_version: '6.7.0', vendor: 'HPE', model: 'ProLiant DL360 Gen10', service_tag: 'T1' },
  ],
  guest_os_summary: { 'Ubuntu Linux': 5, 'Windows Server 2019': 8 },
  technologies: ['VMware ESXi 6.7.0'], summary, ...over,
});

beforeEach(() => { apiMock.getCustomerRvTools.mockReset(); });
afterEach(cleanup);

describe('CustomerRvTools', () => {
  it('renders totals, versions, clusters, technologies and source line', async () => {
    apiMock.getCustomerRvTools.mockResolvedValue(full());
    render(<CustomerRvTools customerName="Acme" />);
    const totals = await screen.findByTestId('customer-rvtotals');
    expect(apiMock.getCustomerRvTools).toHaveBeenCalledWith('Acme');
    expect(totals.textContent).toContain('3 hosts');
    expect(totals.textContent).toContain('13 VMs');
    expect(totals.textContent).toContain('2 datastores');
    expect(screen.getByTestId('customer-rvtools-esxi').textContent).toBe('6.7.0, 7.0.3');
    expect(screen.getByTestId('customer-rvtools-vcenter').textContent).toContain('VMware vCenter Server 7.0.3 (vc.example.com)');
    expect(screen.getByTestId('customer-rvtools-summary').textContent).toContain('24 cores · 256 GB RAM');
    expect(screen.getByTestId('customer-rvtools-cluster-CL1').textContent).toContain('256.0 GB');
    expect(screen.getByTestId('customer-rvtools-host-1').textContent).toContain('esx-01');
    expect(screen.getByTestId('customer-rvtools-host-1').textContent).toContain('ProLiant DL360 Gen10');
    expect(screen.getByTestId('customer-rvtools-host-1').textContent).toContain('192.0 GB');
    expect(screen.getByTestId('customer-rvtools-hosts').textContent).toContain('+2 more hosts — see the import detail');
    expect(screen.getByTestId('customer-rvtools-guestos').textContent).toBe('Top guest OS: Windows Server 2019 (8), Ubuntu Linux (5)');
    expect(screen.getByTestId('customer-rvtools-technologies').textContent).toBe('1 technology record from RVTools: VMware ESXi 6.7.0');
    expect(screen.getByTestId('customer-rvtools-source').textContent).toContain('waltham.xlsx');
    expect(screen.getByTestId('customer-rvtools-source').textContent).toContain('Oct 23, 2026');
    expect(screen.queryByTestId('customer-rvtools-empty')).toBeNull();
  });

  it('shows the empty state when nothing was imported', async () => {
    apiMock.getCustomerRvTools.mockResolvedValue(full({
      import_id: null, source_file: null, imported_at: null, vcenter: null, vcenter_version: null,
      esxi_versions: [], host_count: 0, vm_count: 0, datastore_count: 0, license_count: 0, datacenters: [],
      clusters: [], hosts_preview: [], guest_os_summary: {}, technologies: [],
    }));
    render(<CustomerRvTools customerName="Acme" />);
    expect((await screen.findByTestId('customer-rvtools-empty')).textContent)
      .toContain('No VMware footprint imported for this account');
    expect(screen.queryByTestId('customer-rvtotals')).toBeNull();
    expect(screen.queryByTestId('customer-rvtools-technologies')).toBeNull();
  });

  it('labels incomplete totals while retaining a recorded zero', async () => {
    apiMock.getCustomerRvTools.mockResolvedValue(full({ summary: {
      ...summary, total_cores: null, total_memory_gb: 0,
      coverage: { total_cores: { known: 1, total: 2 } },
    } }));
    render(<CustomerRvTools customerName="Acme" />);
    expect((await screen.findByTestId('customer-rvtools-summary')).textContent)
      .toContain('Unavailable (1 of 2 recorded) cores · 0 GB RAM');
  });

  it('omits the technologies line when there are none', async () => {
    apiMock.getCustomerRvTools.mockResolvedValue(full({ technologies: [] }));
    render(<CustomerRvTools customerName="Acme" />);
    await screen.findByTestId('customer-rvtotals');
    expect(screen.queryByTestId('customer-rvtools-technologies')).toBeNull();
  });

  it('surfaces the error message', async () => {
    apiMock.getCustomerRvTools.mockRejectedValue(new Error('Customer not found'));
    render(<CustomerRvTools customerName="Nope" />);
    expect((await screen.findByTestId('customer-rvtools-error')).textContent).toBe('Customer not found');
    expect(screen.queryByTestId('customer-rvtools-empty')).toBeNull();
  });

  it('reloads when the customer changes', async () => {
    apiMock.getCustomerRvTools.mockResolvedValue(full());
    const { rerender } = render(<CustomerRvTools customerName="Acme" />);
    await screen.findByTestId('customer-rvtotals');
    rerender(<CustomerRvTools customerName="Other" />);
    expect(apiMock.getCustomerRvTools).toHaveBeenLastCalledWith('Other');
  });
});
