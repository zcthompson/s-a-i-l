/**
 * GlobalAdminDashboard.tsx — System-wide admin dashboard
 *
 * Layout follows the application-administrator flow:
 * 1. Global Totals          — customer count + account impact (account-impact contract)
 * 2. Customer Portfolio     — the per-customer account table (no use-case/readiness data)
 * 3. Users                  — the operational/identity domain (user management)
 * 4. Third-party services   — cross-account services administration
 * 5. App Health (footer)    — system vitals (API health card)
 *
 * Requires admin privileges (user.is_admin == true)
 */
import { useState, useEffect } from 'react';
import { api } from '../lib/api';
import { AppHealthCard } from './AppHealthCard';
import { formatImpact, formatPipelineAmount, loadPortfolioImpact, pipelineKpi, PIPELINE_KPI_LABEL, renewalKpi, RENEWAL_KPI_LABEL } from '../lib/accountImpact';
import type { PortfolioAccountImpact } from '../types/use_case';
import {
  ENGAGEMENT_STATUSES,
  SERVICE_CATEGORIES,
  ThirdPartyService,
  formatBillingModel,
  formatEngagementStatus,
  formatServiceCategory,
} from '../types/sail';

interface AdminStats {
  total_customers: number;
  customers: AdminCustomer[];
  total_users?: number;
  active_users?: number;
  pending_users?: number;
  admin_count?: number;
  role_breakdown?: Record<string, number>;
}

interface AdminCustomer {
  customer_id: number;
  customer_name: string;
  user_count: number;
}

interface GlobalAdminDashboardProps {
  userIsAdmin: boolean;
  userRole?: string;
}

const styles: Record<string, React.CSSProperties> = {
  centerPadded: {
    textAlign: 'center' as const,
    padding: '32px 0',
  },
  error: {
    color: 'var(--status-negative)',
    fontWeight: 600,
  },
  loading: {
    color: 'var(--neutral-500)',
  },
  spaceY: {
    display: 'flex',
    flexDirection: 'column' as const,
    gap: '1.5rem',
  },
  grid: {
    display: 'grid',
    gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))',
    gap: '1rem',
  },
  card: {
    background: 'var(--neutral-0)',
    borderRadius: 'var(--radius)',
    boxShadow: 'var(--shadow-sm)',
    padding: '1.5rem',
  },
  smallLabel: {
    fontSize: '0.875rem',
    fontWeight: 500,
    color: 'var(--neutral-500)',
  },
  largeBold: {
    fontSize: '1.875rem',
    fontWeight: 700,
    marginTop: '0.5rem',
  },
  table: {
    width: '100%',
    borderCollapse: 'collapse' as const,
  },
  th: {
    textAlign: 'left' as const,
    padding: '0.5rem',
    borderBottom: '1px solid var(--divider)',
  },
  td: {
    padding: '0.5rem',
    borderBottom: '1px solid var(--divider)',
  },
  tableHeader: {
    padding: '0.5rem',
    textAlign: 'center' as const,
  },
  totalsGrid: {
    display: 'grid',
    gridTemplateColumns: 'repeat(auto-fit, minmax(160px, 1fr))',
    gap: '1rem',
  },
};

function ThirdPartyServicesAdminSection({ customers = [] }: { customers?: AdminCustomer[] }) {
  const [services, setServices] = useState<ThirdPartyService[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [status, setStatus] = useState('');
  const [category, setCategory] = useState('');
  const [search, setSearch] = useState('');

  useEffect(() => {
    let active = true;
    setLoading(true);
    setError(null);
    api.listAllThirdPartyServices({ status, category, search })
      .then((items) => { if (active) setServices(items); })
      .catch((err: any) => { if (active) setError(err?.message || 'Failed to load third-party services'); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [status, category, search]);

  const customerNames = new Map(customers.map((customer) => [customer.customer_id, customer.customer_name]));
  const controlStyle: React.CSSProperties = {
    padding: '8px', border: '1px solid var(--divider)', borderRadius: 'var(--radius)', background: 'var(--neutral-0)', color: 'var(--ink)', fontSize: '0.85rem',
  };
  return (
    <div style={styles.card}>
      <h2 style={{ fontSize: '1.25rem', fontWeight: 600, color: 'var(--neutral-800)', margin: '0 0 0.35rem' }}>Third-Party Services</h2>
      <p style={{ color: 'var(--neutral-500)', fontSize: '0.85rem', margin: '0 0 1rem' }}>Cross-account professional-service engagements. This view is read-only.</p>
      <div style={{ display: 'flex', gap: '0.65rem', flexWrap: 'wrap', marginBottom: '1rem' }}>
        <select aria-label="Filter global third-party services by status" value={status} onChange={(event) => setStatus(event.target.value)} style={{ ...controlStyle, minWidth: '150px' }}>
          <option value="">All statuses</option>
          {ENGAGEMENT_STATUSES.map((value) => <option key={value} value={value}>{formatEngagementStatus(value)}</option>)}
        </select>
        <select aria-label="Filter global third-party services by category" value={category} onChange={(event) => setCategory(event.target.value)} style={{ ...controlStyle, minWidth: '190px' }}>
          <option value="">All categories</option>
          {SERVICE_CATEGORIES.map((value) => <option key={value} value={value}>{formatServiceCategory(value)}</option>)}
        </select>
        <input aria-label="Search global third-party services" placeholder="Search vendor / description / SOW…" value={search} onChange={(event) => setSearch(event.target.value)} style={{ ...controlStyle, flex: '1 1 240px' }} />
      </div>
      {error && <div role="alert" style={{ ...styles.error, padding: '10px 0' }}>{error}</div>}
      {loading ? <div role="status" style={styles.loading}>Loading third-party services...</div> : services.length === 0 ? <div style={{ color: 'var(--neutral-500)', padding: '12px 0' }}>No third-party services found.</div> : (
        <div style={{ overflowX: 'auto' }}>
          <table style={styles.table}>
            <thead><tr>
              <th style={styles.th}>Vendor</th><th style={styles.th}>Customer</th><th style={styles.th}>Category</th><th style={styles.th}>Status</th><th style={styles.th}>Billing</th><th style={styles.th}>Monthly Fee</th><th style={styles.th}>Start</th><th style={styles.th}>End</th>
            </tr></thead>
            <tbody>{services.map((service) => <tr key={service.id}>
              <td style={{ ...styles.td, fontWeight: 600 }}>{service.vendor_name}</td>
              <td style={styles.td}><div>{customerNames.get(service.customer_id) || '—'}</div><div style={{ fontSize: '0.72rem', color: 'var(--neutral-500)' }}>ID {service.customer_id}</div></td>
              <td style={styles.td}>{formatServiceCategory(service.service_category)}</td>
              <td style={styles.td}>{formatEngagementStatus(service.engagement_status)}</td>
              <td style={styles.td}>{formatBillingModel(service.billing_model)}</td>
              <td style={{ ...styles.td, textAlign: 'right' }}>{service.billing_model === null || service.fee_amount === null ? '—' : new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' }).format(service.fee_amount)}</td>
              <td style={styles.td}>{service.started_on || '—'}</td>
              <td style={styles.td}>{service.ended_on || '—'}</td>
            </tr>)}</tbody>
          </table>
        </div>
      )}
    </div>
  );
}

export function GlobalAdminDashboard({ userIsAdmin, userRole }: GlobalAdminDashboardProps) {
  const [stats, setStats] = useState<AdminStats | null>(null);
  const [impact, setImpact] = useState<PortfolioAccountImpact | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  
  const isAdmin = userIsAdmin;
  const canViewServices = isAdmin || userRole === 'ps_admin';
  
  useEffect(() => {
    if (!isAdmin) {
      setLoading(false);
      return;
    }
    
    loadPortfolioImpact().then(setImpact);
    api.getGlobalAdminStats()
      .then((data) => {
        setStats(data);
        setLoading(false);
      })
      .catch((err) => {
        if (err.response?.status === 403) {
          setError('Access denied: Admin privileges required');
        } else {
          setError(err.message);
        }
        setLoading(false);
      });
  }, [isAdmin]);
  
  if (!canViewServices) {
    return (
      <div style={styles.centerPadded}>
        <div style={styles.error}>
          Admin or third-party services administrator privileges required to access this dashboard
        </div>
      </div>
    );
  }

  if (!isAdmin) {
    return <div style={styles.spaceY}><ThirdPartyServicesAdminSection /></div>;
  }
  
  if (loading) {
    return (
      <div style={styles.centerPadded}>
        <div style={styles.loading}>Loading global admin statistics...</div>
      </div>
    );
  }
  
  if (error) {
    return (
      <div style={styles.centerPadded}>
        <div style={styles.error}>{error}</div>
      </div>
    );
  }
  
  if (!stats) return null;
  
  return (
    <div style={styles.spaceY}>
      {/* 1. Global totals — customer count + account impact */}
      <div style={styles.card}>
        <h2 style={{ fontSize: '1.25rem', fontWeight: 600, color: 'var(--neutral-800)', marginBottom: '1rem' }}>Global Totals</h2>
        <div style={styles.totalsGrid}>
          <div>
            <div style={styles.smallLabel}>Total Customers</div>
            <div style={{ ...styles.largeBold, color: 'var(--brand-700)' }}>{stats.total_customers}</div>
          </div>
          <div>
            <div style={styles.smallLabel}>Account Impact</div>
            <div style={{ ...styles.largeBold, color: 'var(--status-positive)' }}>
              {formatImpact(impact?.total_impact.value, impact?.coverage, impact?.total_impact.currency)}
            </div>
            <div style={{ ...styles.smallLabel, marginTop: '0.25rem' }}>
              {impact ? `${impact.total_impact.perspective.replace('_', ' ')}, ${impact.total_impact.realization_basis}` : 'Not quantified'}
            </div>
          </div>
          <div data-testid="pipeline-kpi">
            <div style={styles.smallLabel}>{PIPELINE_KPI_LABEL}</div>
            <div style={{ ...styles.largeBold, color: 'var(--brand-700)' }}>
              {pipelineKpi(impact?.pipeline).value}
            </div>
            <div style={{ ...styles.smallLabel, marginTop: '0.25rem' }}>{pipelineKpi(impact?.pipeline).detail}</div>
          </div>
          <div data-testid="renewals-kpi">
            <div style={styles.smallLabel}>{RENEWAL_KPI_LABEL}</div>
            <div style={{ ...styles.largeBold, color: 'var(--brand-700)' }}>
              {renewalKpi(impact?.renewals).value}
            </div>
            <div style={{ ...styles.smallLabel, marginTop: '0.25rem' }}>{renewalKpi(impact?.renewals).detail}</div>
          </div>
        </div>
      </div>

      {/* 2. Customer portfolio — per-customer account table */}
      <div style={styles.card}>
        <h2 style={{ fontSize: '1.25rem', fontWeight: 600, color: 'var(--neutral-800)', marginBottom: '1rem' }}>Customer Portfolio</h2>
        <table style={styles.table}>
          <thead>
            <tr style={{ borderBottom: '1px solid var(--divider)' }}>
              <th style={styles.th}>Customer</th>
              <th style={styles.th}>Account Impact</th>
              <th style={styles.th}>Users</th>
            </tr>
          </thead>
          <tbody>
            {stats.customers.map((customer) => {
              const row = impact?.customers.find((c) => c.customer_id === customer.customer_id);
              return (
                <tr key={customer.customer_id} style={{ borderBottom: '1px solid var(--divider)' }}>
                  <td style={{ ...styles.td, fontWeight: 500 }}>{customer.customer_name || 'Unnamed'}</td>
                  <td style={{ ...styles.td, color: row?.total_impact != null ? 'var(--status-positive)' : 'var(--neutral-500)' }}>
                    {formatImpact(row?.total_impact, row?.coverage)}
                    <div data-testid={`customer-pipeline-line-${customer.customer_id}`} style={{ fontSize: '0.75rem', color: 'var(--neutral-500)' }}>
                      Pipeline: {formatPipelineAmount(row?.pipeline?.acv, row?.pipeline?.coverage)}
                    </div>
                  </td>
                  <td style={{ ...styles.td, textAlign: 'right' }}>{customer.user_count || 0}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {/* 3. Users — the operational/identity domain */}
      {typeof stats.total_users === 'number' && (
        <div style={styles.card}>
          <h2 style={{ fontSize: '1.25rem', fontWeight: 600, color: 'var(--neutral-800)', marginBottom: '1rem' }}>Users</h2>
          <div style={styles.grid}>
            <div>
              <div style={styles.smallLabel}>Total Users</div>
              <div style={{ ...styles.largeBold, color: 'var(--brand-700)' }}>{stats.total_users}</div>
            </div>
            <div>
              <div style={styles.smallLabel}>Active</div>
              <div style={{ ...styles.largeBold, color: 'var(--status-positive)' }}>{stats.active_users ?? 0}</div>
            </div>
            <div>
              <div style={styles.smallLabel}>Pending Approval</div>
              <div style={{ ...styles.largeBold, color: 'var(--status-warning)' }}>{stats.pending_users ?? 0}</div>
            </div>
            <div>
              <div style={styles.smallLabel}>Admins</div>
              <div style={{ ...styles.largeBold, color: 'var(--brand-700)' }}>{stats.admin_count ?? 0}</div>
            </div>
          </div>
          {stats.role_breakdown && (
            <div style={{ marginTop: '1rem', display: 'flex', gap: '1rem', flexWrap: 'wrap', fontSize: '0.9rem', color: 'var(--neutral-700)' }}>
              <span>Admin: <strong>{stats.role_breakdown['admin'] ?? 0}</strong></span>
              <span>User: <strong>{stats.role_breakdown['user'] ?? 0}</strong></span>
              <span>Auditor: <strong>{stats.role_breakdown['auditor'] ?? 0}</strong></span>
            </div>
          )}
        </div>
      )}

      <ThirdPartyServicesAdminSection customers={stats.customers} />

      {/* 5. App health — system vitals as the footer */}
      <AppHealthCard />
    </div>
  );
}
export default GlobalAdminDashboard;
