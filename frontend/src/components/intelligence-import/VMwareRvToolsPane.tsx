/**
 * VMware — RVTools (XLSX) pane of the Intelligence Import surface: upload an
 * RVTools export against an existing customer (picked by name or alias —
 * imports never create a customer),
 * review import history, inspect an import's footprint (hosts, licenses,
 * clusters, datastores, guest OS, paginated VMs, technologies) and delete it.
 * Manager-or-above: the API 403s for other roles → clean access-denied state.
 */
import { useCallback, useEffect, useRef, useState } from 'react';
import type { CSSProperties } from 'react';
import { api } from '../../lib/api';
import { useImportDetailLink } from './useImportDetailLink';
import { formatDate } from '../../lib/pipelineFormat';
import type { Customer } from '../../types/use_case';
import type {
  RVToolsImportDetail,
  RVToolsImportSummary,
} from '../../types/rvtools_import';
import { rvtoolsMetric } from '../../types/rvtools_import';
import { cardStyle, thStyle, tdStyle, numStyle, linkBtn, isForbidden } from './shared';

interface VMwareRvToolsPaneProps {
  /** Open a customer's dashboard (sets the selected customer + view). */
  onOpenCustomer?: (name: string) => void;
}

const VM_PAGE_SIZE = 100;
const h3Style: CSSProperties = { margin: '0 0 8px', fontSize: '1rem', color: 'var(--neutral-700)' };
const dash = '—';

const fmtNum = (v: number | null | undefined) => (v == null ? dash : v.toLocaleString('en-US'));
const fmtText = (v: string | null | undefined) => (v ? v : dash);
const fmtBool = (v: boolean | null | undefined) => (v == null ? dash : v ? 'Yes' : 'No');
const mbToGb = (mb: number | null | undefined) => (mb == null ? dash : `${(mb / 1024).toFixed(1)} GB`);
const mibToGb = (mib: number | null | undefined) => (mib == null ? dash : `${(mib / 1024).toFixed(1)} GB`);
const mibToTb = (mib: number | null | undefined) => (mib == null ? dash : `${(mib / 1024 / 1024).toFixed(2)} TB`);

function Table({ testId, label, heads, children }: { testId: string; label: string; heads: Array<{ t: string; num?: boolean }>; children: React.ReactNode }) {
  return (
    <div style={{ overflowX: 'auto' }}>
      <table style={{ width: '100%', borderCollapse: 'collapse' }} data-testid={testId} aria-label={label}>
        <thead>
          <tr style={{ borderBottom: '2px solid var(--divider)' }}>
            {heads.map((h) => <th key={h.t} style={h.num ? { ...thStyle, textAlign: 'right' } : thStyle}>{h.t}</th>)}
          </tr>
        </thead>
        <tbody>{children}</tbody>
      </table>
    </div>
  );
}

export function VMwareRvToolsPane({ onOpenCustomer }: VMwareRvToolsPaneProps = {}) {
  const [history, setHistory] = useState<RVToolsImportSummary[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [denied, setDenied] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [customers, setCustomers] = useState<Customer[]>([]);
  const [customerLoadState, setCustomerLoadState] = useState<'loading' | 'error' | 'ready'>('loading');
  const [customerRetry, setCustomerRetry] = useState(0);
  const [file, setFile] = useState<File | null>(null);
  const [customerName, setCustomerName] = useState('');
  const [customerFilter, setCustomerFilter] = useState('');
  const [uploading, setUploading] = useState(false);
  const [result, setResult] = useState<RVToolsImportDetail | null>(null);
  const [detail, setDetail] = useState<RVToolsImportDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailId, setDetailId] = useImportDetailLink();
  const [page, setPage] = useState<{ id: number | null; offset: number }>({ id: null, offset: 0 });
  const detailOffset = page.id === detailId ? page.offset : 0;
  const [deleting, setDeleting] = useState(false);
  const fileInputRef = useRef<HTMLInputElement | null>(null);

  const loadHistory = useCallback(async () => {
    try {
      setHistory(await api.listRvToolsImports());
    } catch (err) {
      if (isForbidden(err)) setDenied(true);
      else setError(err instanceof Error ? err.message : 'Failed to load import history');
    } finally {
      setLoaded(true);
    }
  }, []);

  useEffect(() => { void loadHistory(); }, [loadHistory]);
  useEffect(() => {
    let cancelled = false;
    setCustomerLoadState('loading');
    setCustomerName('');
    api.listCustomers()
      .then((c) => { if (!cancelled) { setCustomers(c ?? []); setCustomerLoadState('ready'); } })
      .catch(() => { if (!cancelled) { setCustomers([]); setCustomerLoadState('error'); } });
    return () => { cancelled = true; };
  }, [customerRetry]);

  // narrow the existing-customer options by name OR alias
  // (case-insensitive substring). Option values remain the canonical customer name.
  // Changing the filter clears the target so every import requires an explicit pick.
  const normalizeFilter = (value: string) => value.trim().replace(/\s+/g, ' ').toLowerCase();
  const filterNeedle = normalizeFilter(customerFilter);
  const customerOptions = filterNeedle === ''
    ? customers
    : customers.filter((c) => normalizeFilter(c.name).includes(filterNeedle)
      || (c.aliases ?? []).some((a) => normalizeFilter(a).includes(filterNeedle)));
  const hasTarget = customerName !== '';
  const canSubmit = !!file && hasTarget && !uploading && customerLoadState === 'ready';

  const handleUpload = async () => {
    if (!file || !hasTarget || customerLoadState !== 'ready') return;
    setUploading(true);
    setError(null);
    setNotice(null);
    try {
      const res = await api.uploadRvToolsImport(file, { customer_name: customerName });
      setResult(res);
      setFile(null);
      setCustomerName('');
      if (fileInputRef.current) fileInputRef.current.value = '';
      await loadHistory();
    } catch (err) {
      if (isForbidden(err)) setDenied(true);
      else setError(err instanceof Error ? err.message : 'Import failed');
    } finally {
      setUploading(false);
    }
  };

  useEffect(() => {
    let active = true;
    setDetail(null);
    setError(null);
    if (detailId === null) { setDetailLoading(false); return () => { active = false; }; }
    setDetailLoading(true);
    api.getRvToolsImport(detailId, VM_PAGE_SIZE, detailOffset)
      .then((value) => { if (active) setDetail(value); })
      .catch((err: unknown) => {
        if (!active) return;
        if (isForbidden(err)) setDenied(true);
        else if ((err as { status?: number } | null)?.status === 404) setError('Import not found, or its customer is outside your scope.');
        else setError(err instanceof Error ? err.message : 'Failed to load import detail');
      })
      .finally(() => { if (active) setDetailLoading(false); });
    return () => { active = false; };
  }, [detailId, detailOffset]);

  const openDetail = (id: number) => { setPage({ id, offset: 0 }); setDetailId(id); };

  const handleDelete = async () => {
    if (!detail) return;
    if (!window.confirm(`Delete import "${detail.file_name}"? This removes its hosts, VMs, licenses, the knowledge document it created, and the technology records it generated. The customer account is kept.`)) return;
    setDeleting(true);
    setError(null);
    try {
      const res = await api.deleteRvToolsImport(detail.import_id);
      setNotice(`Import deleted (${res.deleted_hosts} hosts, ${res.deleted_vms} VMs, ${res.deleted_licenses} licenses, ${res.deleted_knowledge} knowledge documents, ${res.deleted_technologies} technology records removed).${res.temp_customer_kept ? ' The customer account was kept.' : ''}`);
      if (result?.import_id === detail.import_id) setResult(null);
      setDetail(null);
      setDetailId(null);
      await loadHistory();
    } catch (err) {
      if (isForbidden(err)) setDenied(true);
      else setError(err instanceof Error ? err.message : 'Delete failed');
    } finally {
      setDeleting(false);
    }
  };

  if (denied) {
    return (
      <div role="alert" data-testid="rvtools-import-denied" style={{ ...cardStyle, color: 'var(--neutral-700)' }}>
        Requires sales manager or higher.
      </div>
    );
  }

  const disabledBtn = (off: boolean): CSSProperties => ({
    padding: '8px 16px', borderRadius: 'var(--radius)', border: 'none', background: 'var(--brand-500)', color: 'var(--neutral-0)',
    cursor: off ? 'not-allowed' : 'pointer', opacity: off ? 0.6 : 1,
  });
  const pagerBtn = (off: boolean): CSSProperties => ({
    padding: '4px 12px', borderRadius: 'var(--radius)', border: '1px solid var(--divider)', background: 'var(--neutral-0)', color: 'var(--ink)',
    cursor: off ? 'not-allowed' : 'pointer', opacity: off ? 0.5 : 1,
  });

  const vmStart = detail && detail.vm_total > 0 ? detail.vm_offset + 1 : 0;
  const vmEnd = detail ? detail.vm_offset + detail.vms.length : 0;
  const guestOs = detail ? Object.entries(detail.guest_os_summary ?? {}).sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0])) : [];

  return (
    <div data-testid="rvtools-import">
      <p style={{ color: 'var(--neutral-500)', margin: '0 0 16px', fontSize: '0.9rem' }}>
        Upload an RVTools export (.xlsx). The VMware footprint — hosts, VMs, clusters, datastores, licenses — is recorded against the chosen customer and populates its technology inventory. License keys and serial numbers are never stored.
      </p>

      {error && (
        <div role="alert" aria-live="assertive" data-testid="rvtools-import-error" style={{ padding: '10px 14px', background: 'var(--status-negative-soft)', color: 'var(--status-negative)', borderLeft: '4px solid var(--status-negative)', marginBottom: '16px', fontWeight: 500 }}>
          {error}
        </div>
      )}
      {notice && (
        <div role="status" aria-live="polite" data-testid="rvtools-import-notice" style={{ padding: '10px 14px', background: 'var(--status-positive-soft)', color: 'var(--status-positive)', borderLeft: '4px solid var(--status-positive)', marginBottom: '16px', fontWeight: 500 }}>
          {notice}
        </div>
      )}

      <section style={cardStyle} data-testid="rvtools-import-upload" aria-label="Upload RVTools export">
        <div style={{ display: 'flex', gap: '12px', alignItems: 'center', flexWrap: 'wrap' }}>
          <input
            ref={fileInputRef}
            type="file"
            accept=".xlsx,.xlsm"
            aria-label="RVTools export XLSX"
            data-testid="rvtools-import-file"
            onChange={(e) => setFile(e.target.files?.[0] ?? null)}
          />
          <input
            type="search"
            aria-label="Filter customers by name or alias"
            placeholder="Filter by name or alias"
            data-testid="rvtools-import-customer-filter"
            value={customerFilter}
            disabled={customerLoadState !== 'ready'}
            onChange={(e) => { setCustomerFilter(e.target.value); setCustomerName(''); }}
            style={{ padding: '7px 10px', minWidth: '180px' }}
          />
          <select
            aria-label="Existing customer"
            data-testid="rvtools-import-customer"
            value={customerName}
            disabled={customerLoadState !== 'ready'}
            onChange={(e) => setCustomerName(e.target.value)}
            style={{ padding: '7px 10px', minWidth: '220px' }}
          >
            <option value="">— Select existing customer —</option>
            {customerOptions.map((c) => {
              const matches = filterNeedle ? (c.aliases ?? []).filter((alias) => normalizeFilter(alias).includes(filterNeedle)) : [];
              return <option key={c.id} value={c.name}>{c.name}{matches.length > 0 ? ` — matching alias: ${matches.join(', ')}` : ''}</option>;
            })}
          </select>
          <button
            role="button"
            aria-label="Import"
            data-testid="rvtools-import-submit"
            disabled={!canSubmit}
            onClick={handleUpload}
            style={disabledBtn(!canSubmit)}
          >
            {uploading ? 'Importing…' : 'Import'}
          </button>
        </div>
        {customerLoadState === 'loading' && <p role="status">Loading customers…</p>}
        {customerLoadState === 'error' && (
          <div role="alert" style={{ marginTop: 10, color: 'var(--status-negative)' }}>
            Could not load customers. <button type="button" onClick={() => setCustomerRetry((n) => n + 1)}>Retry loading customers</button>
          </div>
        )}
        {customerLoadState === 'ready' && customers.length === 0 && <p role="status">No accessible customers are available.</p>}
        {customerLoadState === 'ready' && customers.length > 0 && customerOptions.length === 0 && <p role="status">No customers match this filter.</p>}
        <p data-testid="rvtools-import-target-help" style={{ margin: '10px 0 0', fontSize: '0.8rem', color: 'var(--neutral-500)' }}>
          Filter accessible customers by name or alias, then select the customer from the list. Filtering does not choose a customer or match the workbook automatically. Changing the filter clears your selection. Imports never create customers; add aliases under More → Edit Customer → Aliases.
        </p>
        {result && (
          <div data-testid="rvtools-import-summary" role="status" style={{ marginTop: '14px', fontSize: '0.9rem', color: 'var(--neutral-700)' }}>
            Imported <strong>{result.file_name}</strong> into <strong>{result.customer_name}</strong>: {result.host_count} hosts, {result.vm_count} VMs, {result.datastore_count} datastores, {result.license_count} licenses.
            <div data-testid="rvtools-import-summary-versions" style={{ marginTop: '4px' }}>
              vCenter {fmtText(result.vcenter_version)} · ESXi {result.esxi_versions.length ? result.esxi_versions.join(', ') : dash}
            </div>
            <div data-testid="rvtools-import-summary-tech" style={{ marginTop: '4px' }}>
              {result.technologies.length} technolog{result.technologies.length === 1 ? 'y' : 'ies'} recorded{result.technologies.length ? `: ${result.technologies.join(', ')}` : ''}
            </div>
          </div>
        )}
      </section>

      <section style={cardStyle} data-testid="rvtools-import-history" aria-label="RVTools import history">
        <h3 style={h3Style}>Import history</h3>
        {!loaded ? (
          <div role="status" style={{ color: 'var(--neutral-500)' }}>Loading import history…</div>
        ) : history.length === 0 ? (
          <p data-testid="rvtools-import-history-empty" style={{ margin: 0, color: 'var(--neutral-500)' }}>No imports yet.</p>
        ) : (
          <div style={{ overflowX: 'auto' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse' }}>
              <thead>
                <tr style={{ borderBottom: '2px solid var(--divider)' }}>
                  <th style={thStyle}>File</th>
                  <th style={thStyle}>Customer</th>
                  <th style={{ ...thStyle, textAlign: 'right' }}>Hosts</th>
                  <th style={{ ...thStyle, textAlign: 'right' }}>VMs</th>
                  <th style={thStyle}>vCenter</th>
                  <th style={thStyle}>ESXi</th>
                  <th style={thStyle}>Imported at</th>
                  <th style={thStyle}>Imported by</th>
                  <th style={thStyle} aria-hidden="true"></th>
                </tr>
              </thead>
              <tbody>
                {history.map((h) => (
                  <tr
                    key={h.import_id}
                    data-testid={`rvtools-import-row-${h.import_id}`}
                    onClick={() => openDetail(h.import_id)}
                    style={{ borderBottom: '1px solid var(--neutral-100)', cursor: 'pointer', background: detail?.import_id === h.import_id ? 'var(--neutral-50, #f5f9fa)' : undefined }}
                  >
                    <td style={tdStyle}>{h.file_name}</td>
                    <td style={tdStyle}>
                      {onOpenCustomer ? (
                        <button role="button" aria-label={`Open ${h.customer_name}`} style={linkBtn} onClick={(e) => { e.stopPropagation(); onOpenCustomer(h.customer_name); }}>
                          {h.customer_name}
                        </button>
                      ) : h.customer_name}
                      {h.created_customer && (
                        <span data-testid={`rvtools-import-created-${h.import_id}`} style={{ marginLeft: '6px', fontSize: '0.7rem', padding: '1px 6px', borderRadius: '8px', background: 'var(--neutral-100)', color: 'var(--neutral-700)' }}>
                          created
                        </span>
                      )}
                    </td>
                    <td style={numStyle}>{h.host_count}</td>
                    <td style={numStyle}>{h.vm_count}</td>
                    <td style={tdStyle}>{fmtText(h.vcenter_version)}</td>
                    <td style={tdStyle}>{h.esxi_versions?.length ? h.esxi_versions.join(', ') : dash}</td>
                    <td style={tdStyle}>{formatDate(h.created_at)}</td>
                    <td style={tdStyle}>{h.imported_by}</td>
                    <td style={tdStyle}>
                      <button
                        role="button"
                        aria-label={`Open import ${h.file_name}`}
                        style={linkBtn}
                        onClick={(e) => { e.stopPropagation(); openDetail(h.import_id); }}
                      >
                        Open
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {detailLoading && <div role="status" style={{ color: 'var(--neutral-500)' }}>Loading import detail…</div>}

      {detail && (
        <div data-testid="rvtools-import-detail">
          <section style={cardStyle} data-testid="rvtools-import-detail-footprint" aria-label="VMware footprint">
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: '12px', flexWrap: 'wrap', marginBottom: '8px' }}>
              <h3 style={{ ...h3Style, margin: 0 }}>Footprint — {detail.file_name}</h3>
              <button
                role="button"
                aria-label="Delete import"
                data-testid="rvtools-import-delete"
                disabled={deleting}
                onClick={handleDelete}
                style={{ padding: '6px 14px', borderRadius: 'var(--radius)', border: '1px solid var(--status-negative)', background: 'var(--neutral-0)', color: 'var(--status-negative)', cursor: deleting ? 'not-allowed' : 'pointer' }}
              >
                {deleting ? 'Deleting…' : 'Delete'}
              </button>
            </div>
            <p style={{ margin: '0 0 10px', fontSize: '0.85rem', color: 'var(--neutral-700)' }}>
              {detail.customer_name} · vCenter {fmtText(detail.vcenter_version)}{detail.vcenter ? ` (${detail.vcenter})` : ''} · RVTools {fmtText(detail.rvtools_version)} · collected {formatDate(detail.collection_at)}
            </p>
            <div data-testid="rvtools-import-detail-strip" style={{ display: 'flex', gap: '20px', flexWrap: 'wrap', fontSize: '0.85rem', color: 'var(--neutral-700)' }}>
              <span><strong>{detail.host_count}</strong> hosts</span>
              <span><strong>{detail.vm_count}</strong> VMs ({rvtoolsMetric(detail.summary, 'powered_on_vms')} powered on)</span>
              <span><strong>{rvtoolsMetric(detail.summary, 'total_cores')}</strong> cores</span>
              <span><strong>{rvtoolsMetric(detail.summary, 'total_memory_gb')}</strong> GB host RAM</span>
              <span><strong>{rvtoolsMetric(detail.summary, 'total_vcpus')}</strong> vCPUs</span>
              <span><strong>{rvtoolsMetric(detail.summary, 'total_vm_memory_gb')}</strong> GB VM RAM</span>
              <span><strong>{detail.summary.datacenter_count}</strong> datacenters</span>
              <span><strong>{detail.summary.cluster_count}</strong> clusters</span>
              <span><strong>{detail.datastore_count}</strong> datastores</span>
              <span><strong>{detail.license_count}</strong> licenses</span>
            </div>
          </section>

          <section style={cardStyle} data-testid="rvtools-import-detail-hosts" aria-label="Hosts">
            <h3 style={h3Style}>Hosts ({detail.hosts.length})</h3>
            {detail.hosts.length === 0 ? <p style={{ margin: 0, color: 'var(--neutral-500)' }}>No hosts.</p> : (
              <Table testId="rvtools-import-hosts-table" label="Hosts" heads={[
                { t: 'Host' }, { t: 'Datacenter' }, { t: 'Cluster' }, { t: 'Status' }, { t: 'Maint.' }, { t: 'Vendor / model' },
                { t: 'CPU model' }, { t: 'MHz', num: true }, { t: 'Sockets', num: true }, { t: 'Cores/socket', num: true }, { t: 'Cores', num: true },
                { t: 'Memory', num: true }, { t: 'NICs', num: true }, { t: 'HBAs', num: true }, { t: 'VMs', num: true }, { t: 'vCPUs', num: true },
                { t: 'vMotion' }, { t: 'Storage vMotion' }, { t: 'EVC' }, { t: 'ESXi' }, { t: 'Service tag' },
              ]}>
                {detail.hosts.map((h) => (
                  <tr key={h.id} data-testid={`rvtools-import-host-${h.id}`} style={{ borderBottom: '1px solid var(--neutral-100)' }}>
                    <td style={tdStyle}>{h.host_name}</td>
                    <td style={tdStyle}>{fmtText(h.datacenter)}</td>
                    <td style={tdStyle}>{fmtText(h.cluster)}</td>
                    <td style={tdStyle}>{fmtText(h.config_status)}</td>
                    <td style={tdStyle}>{fmtBool(h.maintenance_mode)}</td>
                    <td style={tdStyle}>{[h.vendor, h.model].filter(Boolean).join(' ') || dash}</td>
                    <td style={tdStyle}>{fmtText(h.cpu_model)}</td>
                    <td style={numStyle}>{fmtNum(h.cpu_mhz)}</td>
                    <td style={numStyle}>{fmtNum(h.sockets)}</td>
                    <td style={numStyle}>{fmtNum(h.cores_per_socket)}</td>
                    <td style={numStyle}>{fmtNum(h.cores)}</td>
                    <td style={numStyle}>{mbToGb(h.memory_mb)}</td>
                    <td style={numStyle}>{fmtNum(h.nics)}</td>
                    <td style={numStyle}>{fmtNum(h.hbas)}</td>
                    <td style={numStyle}>{fmtNum(h.vm_count)}</td>
                    <td style={numStyle}>{fmtNum(h.vcpu_count)}</td>
                    <td style={tdStyle}>{fmtBool(h.vmotion)}</td>
                    <td style={tdStyle}>{fmtBool(h.storage_vmotion)}</td>
                    <td style={tdStyle}>{fmtText(h.evc_mode)}</td>
                    <td style={tdStyle}>{fmtText(h.esxi_version)}</td>
                    <td style={tdStyle}>{fmtText(h.service_tag)}</td>
                  </tr>
                ))}
              </Table>
            )}
          </section>

          <section style={cardStyle} data-testid="rvtools-import-detail-licenses" aria-label="Licenses">
            <h3 style={h3Style}>Licenses ({detail.licenses.length})</h3>
            {detail.licenses.length === 0 ? <p data-testid="rvtools-import-licenses-empty" style={{ margin: 0, color: 'var(--neutral-500)' }}>No license data in this export.</p> : (
              <Table testId="rvtools-import-licenses-table" label="Licenses" heads={[
                { t: 'License' }, { t: 'Cost unit' }, { t: 'Total', num: true }, { t: 'Used', num: true }, { t: 'Expiration' }, { t: 'Features' },
              ]}>
                {detail.licenses.map((l) => (
                  <tr key={l.id} data-testid={`rvtools-import-license-${l.id}`} style={{ borderBottom: '1px solid var(--neutral-100)' }}>
                    <td style={tdStyle}>{l.name}</td>
                    <td style={tdStyle}>{fmtText(l.cost_unit)}</td>
                    <td style={numStyle}>{fmtNum(l.total)}</td>
                    <td style={numStyle}>{fmtNum(l.used)}</td>
                    <td style={tdStyle}>{fmtText(l.expiration)}</td>
                    <td style={tdStyle}>{fmtText(l.features)}</td>
                  </tr>
                ))}
              </Table>
            )}
          </section>

          <section style={cardStyle} data-testid="rvtools-import-detail-clusters" aria-label="Clusters">
            <h3 style={h3Style}>Clusters ({detail.clusters.length})</h3>
            {detail.clusters.length === 0 ? <p style={{ margin: 0, color: 'var(--neutral-500)' }}>No cluster data in this export.</p> : (
              <Table testId="rvtools-import-clusters-table" label="Clusters" heads={[
                { t: 'Cluster' }, { t: 'Hosts', num: true }, { t: 'CPU cores', num: true }, { t: 'CPU threads', num: true }, { t: 'Memory', num: true }, { t: 'HA' },
              ]}>
                {detail.clusters.map((c) => (
                  <tr key={c.name} data-testid={`rvtools-import-cluster-${c.name}`} style={{ borderBottom: '1px solid var(--neutral-100)' }}>
                    <td style={tdStyle}>{c.name}</td>
                    <td style={numStyle}>{fmtNum(c.hosts)}</td>
                    <td style={numStyle}>{fmtNum(c.cpu_cores)}</td>
                    <td style={numStyle}>{fmtNum(c.cpu_threads)}</td>
                    <td style={numStyle}>{mbToGb(c.memory_mb)}</td>
                    <td style={tdStyle}>{fmtBool(c.ha)}</td>
                  </tr>
                ))}
              </Table>
            )}
          </section>

          <section style={cardStyle} data-testid="rvtools-import-detail-datastores" aria-label="Datastores">
            <h3 style={h3Style}>Datastores ({detail.datastores.length})</h3>
            {detail.datastores.length === 0 ? <p style={{ margin: 0, color: 'var(--neutral-500)' }}>No datastore data in this export.</p> : (
              <Table testId="rvtools-import-datastores-table" label="Datastores" heads={[
                { t: 'Datastore' }, { t: 'Type' }, { t: 'Capacity', num: true }, { t: 'In use', num: true }, { t: 'Free', num: true }, { t: 'Hosts', num: true },
              ]}>
                {detail.datastores.map((d) => (
                  <tr key={d.name} data-testid={`rvtools-import-datastore-${d.name}`} style={{ borderBottom: '1px solid var(--neutral-100)' }}>
                    <td style={tdStyle}>{d.name}</td>
                    <td style={tdStyle}>{fmtText(d.type)}</td>
                    <td style={numStyle}>{mibToTb(d.capacity_mib)}</td>
                    <td style={numStyle}>{mibToTb(d.used_mib)}</td>
                    <td style={numStyle}>{mibToTb(d.free_mib)}</td>
                    <td style={numStyle}>{fmtNum(d.host_count)}</td>
                  </tr>
                ))}
              </Table>
            )}
          </section>

          <section style={cardStyle} data-testid="rvtools-import-detail-guestos" aria-label="Guest OS summary">
            <h3 style={h3Style}>Guest OS summary ({guestOs.length})</h3>
            {guestOs.length === 0 ? <p style={{ margin: 0, color: 'var(--neutral-500)' }}>No guest OS data.</p> : (
              <Table testId="rvtools-import-guestos-table" label="Guest OS" heads={[{ t: 'Guest OS' }, { t: 'VMs', num: true }]}>
                {guestOs.map(([os, n]) => (
                  <tr key={os} style={{ borderBottom: '1px solid var(--neutral-100)' }}>
                    <td style={tdStyle}>{os}</td>
                    <td style={numStyle}>{n}</td>
                  </tr>
                ))}
              </Table>
            )}
          </section>

          <section style={cardStyle} data-testid="rvtools-import-detail-vms" aria-label="Virtual machines">
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: '12px', flexWrap: 'wrap', marginBottom: '8px' }}>
              <h3 style={{ ...h3Style, margin: 0 }}>Virtual machines ({detail.vm_total})</h3>
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px', fontSize: '0.85rem', color: 'var(--neutral-700)' }}>
                <span data-testid="rvtools-import-vm-range">{vmStart}–{vmEnd} of {detail.vm_total}</span>
                <button
                  role="button" aria-label="Previous VM page" data-testid="rvtools-import-vm-prev"
                  disabled={detail.vm_offset <= 0 || detailLoading}
                  onClick={() => setPage({ id: detail.import_id, offset: Math.max(0, detail.vm_offset - detail.vm_limit) })}
                  style={pagerBtn(detail.vm_offset <= 0 || detailLoading)}
                >
                  Prev
                </button>
                <button
                  role="button" aria-label="Next VM page" data-testid="rvtools-import-vm-next"
                  disabled={detail.vm_offset + detail.vm_limit >= detail.vm_total || detailLoading}
                  onClick={() => setPage({ id: detail.import_id, offset: detail.vm_offset + detail.vm_limit })}
                  style={pagerBtn(detail.vm_offset + detail.vm_limit >= detail.vm_total || detailLoading)}
                >
                  Next
                </button>
              </div>
            </div>
            {detail.vms.length === 0 ? <p style={{ margin: 0, color: 'var(--neutral-500)' }}>No VMs.</p> : (
              <Table testId="rvtools-import-vms-table" label="Virtual machines" heads={[
                { t: 'VM' }, { t: 'Power' }, { t: 'vCPUs', num: true }, { t: 'Memory', num: true }, { t: 'Disks', num: true }, { t: 'Disk capacity', num: true },
                { t: 'Guest OS' }, { t: 'Host' }, { t: 'Cluster' }, { t: 'Datacenter' }, { t: 'Datastore' }, { t: 'IP' },
              ]}>
                {detail.vms.map((v) => (
                  <tr key={v.id} data-testid={`rvtools-import-vm-${v.id}`} style={{ borderBottom: '1px solid var(--neutral-100)' }}>
                    <td style={tdStyle}>{v.name}</td>
                    <td style={tdStyle}>{fmtText(v.power_state)}</td>
                    <td style={numStyle}>{fmtNum(v.cpus)}</td>
                    <td style={numStyle}>{mbToGb(v.memory_mb)}</td>
                    <td style={numStyle}>{fmtNum(v.disks)}</td>
                    <td style={numStyle}>{mibToGb(v.disk_capacity_mib)}</td>
                    <td style={tdStyle}>{fmtText(v.guest_os)}</td>
                    <td style={tdStyle}>{fmtText(v.host)}</td>
                    <td style={tdStyle}>{fmtText(v.cluster)}</td>
                    <td style={tdStyle}>{fmtText(v.datacenter)}</td>
                    <td style={tdStyle}>{fmtText(v.datastore)}</td>
                    <td style={tdStyle}>{fmtText(v.primary_ip)}</td>
                  </tr>
                ))}
              </Table>
            )}
          </section>

          <section style={cardStyle} data-testid="rvtools-import-detail-technologies" aria-label="Technologies recorded">
            <h3 style={h3Style}>Technologies recorded ({detail.technologies.length})</h3>
            {detail.technologies.length === 0 ? <p style={{ margin: 0, color: 'var(--neutral-500)' }}>No technology records.</p> : (
              <ul style={{ margin: 0, paddingLeft: '20px', fontSize: '0.85rem', color: 'var(--neutral-700)' }}>
                {detail.technologies.map((t) => <li key={t}>{t}</li>)}
              </ul>
            )}
          </section>
        </div>
      )}
    </div>
  );
}

export default VMwareRvToolsPane;
