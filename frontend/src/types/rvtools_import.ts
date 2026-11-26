/** RVTools (VMware) Intelligence Import contract (.hermes/scratch/rvtools_import_contract.md,
 *  "API response shapes"). RVTools xlsx export → customer VMware footprint. */

export interface RVToolsHost {
  id: number;
  host_name: string;
  datacenter: string | null;
  cluster: string | null;
  config_status: string | null;
  maintenance_mode: boolean | null;
  cpu_model: string | null;
  cpu_mhz: number | null;
  sockets: number | null;
  cores_per_socket: number | null;
  cores: number | null;
  memory_mb: number | null;
  nics: number | null;
  hbas: number | null;
  vm_count: number | null;
  vcpu_count: number | null;
  vmotion: boolean | null;
  storage_vmotion: boolean | null;
  evc_mode: string | null;
  esxi_version: string | null;
  vendor: string | null;
  model: string | null;
  service_tag: string | null;
}

export interface RVToolsVm {
  id: number;
  name: string;
  power_state: string | null;
  cpus: number | null;
  memory_mb: number | null;
  disks: number | null;
  disk_capacity_mib: number | null;
  guest_os: string | null;
  host: string | null;
  cluster: string | null;
  datacenter: string | null;
  datastore: string | null;
  primary_ip: string | null;
}

export interface RVToolsLicense {
  id: number;
  name: string;
  cost_unit: string | null;
  total: number | null;
  used: number | null;
  /** Raw cell: "Never" / "Expired" / a datetime string. */
  expiration: string | null;
  features: string | null;
}

export interface RVToolsCluster {
  name: string;
  hosts: number | null;
  cpu_cores: number | null;
  cpu_threads: number | null;
  memory_mb: number | null;
  ha: boolean | null;
}

export interface RVToolsDatastore {
  name: string;
  type: string | null;
  capacity_mib: number | null;
  used_mib: number | null;
  free_mib: number | null;
  host_count: number | null;
}

export interface RVToolsSummary {
  total_cores: number | null;
  total_memory_gb: number | null;
  total_vcpus: number | null;
  total_vm_memory_gb: number | null;
  powered_on_vms: number | null;
  datacenter_count: number;
  cluster_count: number;
  coverage?: Record<string, { known: number; total: number }>;
}

export function rvtoolsMetric(summary: RVToolsSummary, key: 'total_cores' | 'total_memory_gb' | 'total_vcpus' | 'total_vm_memory_gb' | 'powered_on_vms'): string {
  const value = summary[key];
  const coverage = summary.coverage?.[key];
  return value == null ? coverage && coverage.total > 0 ? `Unavailable (${coverage.known} of ${coverage.total} recorded)` : 'Unavailable' : String(value);
}

/** GET /api/rvtools-import/ list row. */
export interface RVToolsImportSummary {
  import_id: number;
  file_name: string;
  customer_id: number;
  customer_name: string;
  created_customer: boolean;
  host_count: number;
  vm_count: number;
  vcenter: string | null;
  vcenter_version: string | null;
  esxi_versions: string[];
  created_at: string;
  imported_by: string;
}

/** POST (201) and GET /{id}/ response. */
export interface RVToolsImportDetail {
  import_id: number;
  file_name: string;
  created_at: string;
  imported_by: string;
  customer_id: number;
  customer_name: string;
  /** Legacy: true only on imports made by the removed temporary-customer path. */
  created_customer: boolean;
  /** POST only — how the target resolved. */
  matched_by?: 'name' | 'alias';
  rvtools_version: string | null;
  collection_at: string | null;
  vcenter: string | null;
  vcenter_version: string | null;
  host_count: number;
  vm_count: number;
  datastore_count: number;
  license_count: number;
  datacenters: string[];
  esxi_versions: string[];
  clusters: RVToolsCluster[];
  datastores: RVToolsDatastore[];
  guest_os_summary: Record<string, number>;
  summary: RVToolsSummary;
  technologies: string[];
  hosts: RVToolsHost[];
  licenses: RVToolsLicense[];
  vms: RVToolsVm[];
  vm_total: number;
  vm_limit: number;
  vm_offset: number;
}

export interface RVToolsImportDeleteResult {
  detail: string;
  deleted_hosts: number;
  deleted_vms: number;
  deleted_licenses: number;
  deleted_knowledge: number;
  deleted_technologies: number;
  temp_customer_kept: boolean;
}

/** The target customer's name or alias (case-insensitive). Imports never
 *  create a customer (Part 14 import remediation). */
export interface RVToolsImportTarget {
  customer_name: string;
}

/** GET /api/customers/{name}/rvtools/ (latest import only). */
export interface CustomerRvTools {
  customer_name: string;
  import_id: number | null;
  source_file: string | null;
  imported_at: string | null;
  rvtools_version: string | null;
  vcenter: string | null;
  vcenter_version: string | null;
  esxi_versions: string[];
  host_count: number;
  vm_count: number;
  datastore_count: number;
  license_count: number;
  datacenters: string[];
  clusters: RVToolsCluster[];
  hosts_preview: RVToolsHost[];
  guest_os_summary: Record<string, number>;
  technologies: string[];
  summary: RVToolsSummary;
}
