/**
 * VMware Footprint panel (Intelligence Import) — the latest RVTools import
 * for one account, from GET /api/customers/{name}/rvtools/. Read-only; an
 * honest empty state when nothing has been imported for the account. The
 * full host/VM/license data lives in the import detail (Intelligence Import).
 */
import { useEffect, useState } from 'react';
import { api } from '../lib/api';
import { formatDate } from '../lib/pipelineFormat';
import type { CustomerRvTools as CustomerRvToolsData } from '../types/rvtools_import';
import { rvtoolsMetric } from '../types/rvtools_import';

interface CustomerRvToolsProps {
  customerName: string;
}

const HOST_PREVIEW = 5;

const cardStyle = {
  background: 'var(--neutral-0)', borderRadius: 'var(--radius)', boxShadow: 'var(--shadow-card)',
  overflow: 'hidden', marginTop: '16px',
} as const;
const thStyle = { padding: '8px 12px', textAlign: 'left', fontSize: '0.8rem', fontWeight: 600, color: 'var(--neutral-500)' } as const;
const tdStyle = { padding: '8px 12px', fontSize: '0.85rem', verticalAlign: 'top' } as const;

export function CustomerRvTools({ customerName }: CustomerRvToolsProps) {
  const [data, setData] = useState<CustomerRvToolsData | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setData(null);
    setError(null);
    api.getCustomerRvTools(customerName)
      .then((d) => { if (!cancelled) setData(d); })
      .catch((e: unknown) => {
        if (!cancelled) setError(e instanceof Error ? e.message : 'Failed to load VMware footprint');
      });
    return () => { cancelled = true; };
  }, [customerName]);

  const hasData = !!data && data.import_id != null;
  const hosts = data?.hosts_preview ?? [];
  const clusters = data?.clusters ?? [];
  const guestOs = Object.entries(data?.guest_os_summary ?? {}).sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0])).slice(0, HOST_PREVIEW);
  const esxi = data?.esxi_versions ?? [];

  return (
    <section style={cardStyle} data-testid="customer-rvtools" aria-label="VMware footprint">
      <div style={{ padding: '16px 20px', borderBottom: '1px solid var(--divider)' }}>
        <h3 style={{ margin: 0, fontSize: '1rem', color: 'var(--neutral-700)' }}>VMware Footprint</h3>
      </div>
      <div style={{ padding: '16px 20px' }}>
        {error && (
          <div role="alert" data-testid="customer-rvtools-error" style={{ color: 'var(--status-negative)', fontSize: '0.9rem' }}>{error}</div>
        )}
        {!error && !data && (
          <div role="status" style={{ color: 'var(--neutral-500)', fontSize: '0.9rem' }}>Loading VMware footprint…</div>
        )}
        {data && !hasData && (
          <p data-testid="customer-rvtools-empty" style={{ margin: 0, color: 'var(--neutral-500)', fontSize: '0.9rem' }}>
            No VMware footprint imported for this account
          </p>
        )}
        {data && hasData && (
          <>
            <div data-testid="customer-rvtotals" style={{ display: 'flex', gap: '20px', flexWrap: 'wrap', marginBottom: '12px', fontSize: '0.85rem', color: 'var(--neutral-700)' }}>
              <span><strong>{data.host_count}</strong> hosts</span>
              <span><strong>{data.vm_count}</strong> VMs</span>
              <span><strong>{data.datastore_count}</strong> datastores</span>
              <span>ESXi <strong data-testid="customer-rvtools-esxi">{esxi.length ? esxi.join(', ') : '—'}</strong></span>
              <span data-testid="customer-rvtools-vcenter">
                vCenter <strong>{data.vcenter_version ?? '—'}</strong>{data.vcenter ? <> ({data.vcenter})</> : null}
              </span>
            </div>
            <p data-testid="customer-rvtools-summary" style={{ margin: '0 0 12px', fontSize: '0.85rem', color: 'var(--neutral-700)' }}>
              {rvtoolsMetric(data.summary, 'total_cores')} cores · {rvtoolsMetric(data.summary, 'total_memory_gb')} GB RAM · {rvtoolsMetric(data.summary, 'total_vcpus')} vCPUs · {rvtoolsMetric(data.summary, 'powered_on_vms')} VMs powered on · {data.summary.cluster_count} cluster{data.summary.cluster_count === 1 ? '' : 's'} · {data.summary.datacenter_count} datacenter{data.summary.datacenter_count === 1 ? '' : 's'}
            </p>
            {(data.technologies ?? []).length > 0 && (
              <p data-testid="customer-rvtools-technologies" style={{ margin: '0 0 12px', fontSize: '0.85rem', color: 'var(--neutral-700)' }}>
                <strong>{data.technologies.length}</strong> technology record{data.technologies.length === 1 ? '' : 's'} from RVTools: {data.technologies.join(', ')}
              </p>
            )}
            {hosts.length > 0 && (
              <div style={{ overflowX: 'auto' }} data-testid="customer-rvtools-hosts">
                <table style={{ width: '100%', borderCollapse: 'collapse' }}>
                  <thead>
                    <tr style={{ borderBottom: '2px solid var(--divider)' }}>
                      <th style={thStyle}>Host</th>
                      <th style={thStyle}>Model</th>
                      <th style={thStyle}>CPU</th>
                      <th style={{ ...thStyle, textAlign: 'right' }}>Cores</th>
                      <th style={{ ...thStyle, textAlign: 'right' }}>RAM</th>
                      <th style={{ ...thStyle, textAlign: 'right' }}>VMs</th>
                      <th style={thStyle}>ESXi</th>
                    </tr>
                  </thead>
                  <tbody>
                    {hosts.map((h) => (
                      <tr key={h.id} data-testid={`customer-rvtools-host-${h.id}`} style={{ borderBottom: '1px solid var(--neutral-100)' }}>
                        <td style={tdStyle}>{h.host_name}</td>
                        <td style={tdStyle}>{h.model ?? h.vendor ?? '—'}</td>
                        <td style={tdStyle}>{h.cpu_model ?? '—'}</td>
                        <td style={{ ...tdStyle, textAlign: 'right' }}>{h.cores ?? '—'}</td>
                        <td style={{ ...tdStyle, textAlign: 'right' }}>{h.memory_mb == null ? '—' : `${(h.memory_mb / 1024).toFixed(1)} GB`}</td>
                        <td style={{ ...tdStyle, textAlign: 'right' }}>{h.vm_count ?? '—'}</td>
                        <td style={tdStyle}>{h.esxi_version ?? '—'}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                {data.host_count > hosts.length && (
                  <p style={{ margin: '6px 0 0', fontSize: '0.75rem', color: 'var(--neutral-500)' }}>
                    +{data.host_count - hosts.length} more host{data.host_count - hosts.length === 1 ? '' : 's'} — see the import detail
                  </p>
                )}
              </div>
            )}
            {clusters.length > 0 && (
              <div style={{ overflowX: 'auto' }} data-testid="customer-rvtools-clusters">
                <table style={{ width: '100%', borderCollapse: 'collapse' }}>
                  <thead>
                    <tr style={{ borderBottom: '2px solid var(--divider)' }}>
                      <th style={thStyle}>Cluster</th>
                      <th style={{ ...thStyle, textAlign: 'right' }}>Hosts</th>
                      <th style={{ ...thStyle, textAlign: 'right' }}>CPU cores</th>
                      <th style={{ ...thStyle, textAlign: 'right' }}>Memory</th>
                      <th style={thStyle}>HA</th>
                    </tr>
                  </thead>
                  <tbody>
                    {clusters.slice(0, HOST_PREVIEW).map((c) => (
                      <tr key={c.name} data-testid={`customer-rvtools-cluster-${c.name}`} style={{ borderBottom: '1px solid var(--neutral-100)' }}>
                        <td style={tdStyle}>{c.name}</td>
                        <td style={{ ...tdStyle, textAlign: 'right' }}>{c.hosts ?? '—'}</td>
                        <td style={{ ...tdStyle, textAlign: 'right' }}>{c.cpu_cores ?? '—'}</td>
                        <td style={{ ...tdStyle, textAlign: 'right' }}>{c.memory_mb == null ? '—' : `${(c.memory_mb / 1024).toFixed(1)} GB`}</td>
                        <td style={tdStyle}>{c.ha == null ? '—' : c.ha ? 'Yes' : 'No'}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                {clusters.length > HOST_PREVIEW && (
                  <p style={{ margin: '6px 0 0', fontSize: '0.75rem', color: 'var(--neutral-500)' }}>
                    +{clusters.length - HOST_PREVIEW} more cluster{clusters.length - HOST_PREVIEW === 1 ? '' : 's'} — see the import detail
                  </p>
                )}
              </div>
            )}
            {guestOs.length > 0 && (
              <p data-testid="customer-rvtools-guestos" style={{ margin: '12px 0 0', fontSize: '0.85rem', color: 'var(--neutral-700)' }}>
                Top guest OS: {guestOs.map(([os, n]) => `${os} (${n})`).join(', ')}
              </p>
            )}
            <p data-testid="customer-rvtools-source" style={{ margin: '10px 0 0', fontSize: '0.75rem', color: 'var(--neutral-500)' }}>
              Source: {data.source_file ?? 'unknown file'} · imported {formatDate(data.imported_at)}
            </p>
          </>
        )}
      </div>
    </section>
  );
}

export default CustomerRvTools;
