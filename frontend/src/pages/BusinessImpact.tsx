import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { api } from '../lib/api';
import { UseCase, StatsResponse, Customer } from '../types/use_case';
import { ImpactMatrix } from '../components/ImpactMatrix';
import { AnalyticsDashboard } from '../components/AnalyticsDashboard';

export function BusinessImpact({ onBack, customer, embedded }: { onBack?: () => void; customer?: { id: number; name: string }; embedded?: boolean } = {}) {
  const navigate = useNavigate();
  const [useCases, setUseCases] = useState<UseCase[]>([]);
  const [stats, setStats] = useState<StatsResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedCustomerId, setSelectedCustomerId] = useState<number | null>(customer ? customer.id : null);
  const [allCustomers, setAllCustomers] = useState<Customer[]>([]);

  useEffect(() => {
    if (!customer) loadCustomersForMapping();
  // eslint-disable-next-line react-hooks/exhaustive-deps -- pre-existing dependency list; change only with UI verification
  }, []);

  useEffect(() => {
    loadData();
  // eslint-disable-next-line react-hooks/exhaustive-deps -- pre-existing dependency list; change only with UI verification
  }, [selectedCustomerId]);

  const loadCustomersForMapping = async () => {
    try {
      const customers = await api.listCustomers();
      setAllCustomers(customers);
    } catch {
      // Ignore
    }
  };

  const loadData = async () => {
    try {
      setLoading(true);
      const scopeId = customer ? customer.id : selectedCustomerId;
      const listParams: any = { status: '' };
      if (scopeId !== null) {
        listParams.customer_id = String(scopeId);
      }
      
      const [useCasesData, statsData] = await Promise.all([
        api.list(listParams),
        api.aggregateStats(),
      ]);
      setUseCases(useCasesData);
      if (scopeId !== null) {
        // /stats/aggregate/ is global and has no customer filter —
        // compute the impact totals from this customer's use cases.
        const totals = useCasesData.reduce(
          (acc, uc) => {
            acc.total_savings += uc.estimated_savings || 0;
            acc.total_revenue += uc.estimated_revenue || 0;
            return acc;
          },
          { total_savings: 0, total_revenue: 0, total_impact: 0 },
        );
        totals.total_impact = totals.total_savings + totals.total_revenue;
        setStats({ ...statsData, impact_summary: totals });
      } else {
        setStats(statsData);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load business impact');
    } finally {
      setLoading(false);
    }
  };

  if (loading) return <div role="status" aria-live="polite" style={{ padding: '40px', textAlign: 'center', color: 'var(--neutral-500)' }}>Loading business impact analysis...</div>;
  if (error) return <div role="alert" aria-live="assertive" style={{ padding: '16px', background: 'var(--status-negative-soft)', borderLeft: '4px solid var(--status-negative)', borderRadius: 'var(--radius-sm)', color: 'var(--status-negative)', marginBottom: '24px' }}>
    <span aria-hidden="true">⚠️ </span>{error}
    <button role="button" aria-label="Retry loading business impact" onClick={loadData} style={{ marginLeft: '12px', padding: '6px 12px', border: '1px solid var(--status-negative)', borderRadius: 'var(--radius-sm)', background: 'var(--neutral-0)', color: 'var(--status-negative)', cursor: 'pointer', fontWeight: 600 }}>Retry</button>
  </div>;
  if (!stats) return <div role="alert" aria-live="polite" style={{ padding: '40px', textAlign: 'center', color: 'var(--neutral-500)' }}>No data available for business impact analysis.</div>;

  const scored = useCases.filter(uc => uc.overall_score != null);
  const avgSavings = scored.length > 0 ? (stats.impact_summary.total_savings / scored.length) : 0;
  const avgRevenue = scored.length > 0 ? (stats.impact_summary.total_revenue / scored.length) : 0;

  const getScoreColor = (score: number) => {
    if (score >= 70) return 'var(--status-positive)';
    if (score >= 35) return 'var(--status-warning)';
    return 'var(--status-negative)';
  };

  return (
    <div style={{ padding: '24px', maxWidth: '1400px', margin: '0 auto' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '24px' }}>
        <div>
          <h1 style={{ margin: '0 0 4px 0', fontSize: '1.8rem', color: 'var(--ink)' }}>
            {customer ? `Business Impact — ${customer.name}` : 'Business Impact Analysis'}
          </h1>
          <p style={{ margin: 0, color: 'var(--neutral-500)', fontSize: '0.95rem' }}>
            {customer
              ? `ROI analysis, savings, and revenue projections from ${customer.name}'s AI assessments`
              : 'ROI analysis, savings, and revenue projections from AI assessments'}
          </p>
        </div>
        {embedded ? null : onBack ? (
          <button role="button" aria-label="Back to dashboard" onClick={onBack} style={{ padding: '8px 16px', background: 'var(--neutral-500)', color: 'var(--neutral-0)', border: 'none', borderRadius: 'var(--radius)', cursor: 'pointer', fontSize: '0.85rem', fontWeight: 500 }}>
            ← Back to Dashboard
          </button>
        ) : (
          <button role="button" aria-label="Go to dashboard" onClick={() => { navigate('/?view=dashboard'); }} style={{ padding: '8px 16px', background: 'var(--neutral-100)', color: 'var(--neutral-500)', border: '1px solid var(--divider)', borderRadius: 'var(--radius)', cursor: 'pointer', fontSize: '0.85rem', fontWeight: 500 }}>
            ← Back to Dashboard
          </button>
        )}
        {!customer && (
        <select aria-label="Business Impact selection"
          style={{ padding: '8px 12px', border: '1px solid var(--divider)', borderRadius: 'var(--radius)', fontSize: '0.9rem' }}
          value={selectedCustomerId?.toString() ?? 'all'}
          onChange={(e) => setSelectedCustomerId(e.target.value === 'all' ? null : Number(e.target.value))}
        >
          <option value="all">My Customers</option>
          {allCustomers.map(c => (
            <option key={c.id} value={c.id}>{c.name}</option>
          ))}
        </select>
        )}
      </div>

      {/* Business Impact Matrix + Quadrant — customer-scoped only, at the top
          of the customer section (moved here from the customer analytics tab) */}
      {(customer ? customer.id : selectedCustomerId) != null && (
        <ImpactMatrix
          key={`impact-matrix-biz-${customer ? customer.id : selectedCustomerId}`}
          customerId={customer ? customer.id : selectedCustomerId}
          section="all"
        />
      )}

      {/* KPI Cards */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: '16px', marginBottom: '28px' }}>
        <ImpactCard
          value={`$${stats.impact_summary.total_savings.toLocaleString()}`}
          label="Total Savings"
          subtext={`Avg: $${avgSavings.toLocaleString()}/use case`}
          color="var(--status-positive)"
          icon="💰"
        />
        <ImpactCard
          value={`$${stats.impact_summary.total_revenue.toLocaleString()}`}
          label="Total Revenue"
          subtext={`Avg: $${avgRevenue.toLocaleString()}/use case`}
          color="var(--brand-500)"
          icon="📈"
        />
        <ImpactCard
          value={`$${stats.impact_summary.total_impact.toLocaleString()}`}
          label="Total Impact"
          subtext={`${scored.length} scored use cases`}
          color="var(--status-warning)"
          icon="🎯"
        />
        <ImpactCard
          value={scored.length > 0 ? (scored.reduce((s, uc) => s + (uc.overall_score || 0), 0) / scored.length).toFixed(1) : '—'}
          label="Avg Readiness"
          subtext={`organization average across ${scored.length} scored use case${scored.length === 1 ? '' : 's'}`}
          color="var(--brand-500)"
          icon="📊"
        />
      </div>

      {/* Impact by Category */}
      <div style={{ background: 'var(--neutral-0)', borderRadius: 'var(--radius)', padding: '24px', boxShadow: 'var(--shadow-card)', marginBottom: '20px' }}>
        <h3 style={{ margin: '0 0 16px 0', fontSize: '1.1rem', color: 'var(--neutral-700)' }}>Impact by Use Case Category</h3>
        <div style={{ overflowX: 'auto' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse' }}>
            <thead>
              <tr style={{ borderBottom: '2px solid var(--divider)' }}>
                {['Use Case', 'Customer', 'Department', 'Score', 'Savings', 'Revenue', 'Impact', 'Timeline'].map(h => (
                  <th key={h} style={{ padding: '12px', textAlign: 'left', fontSize: '0.85rem', color: 'var(--neutral-500)', fontWeight: 600 }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {scored.sort((a, b) => (b.overall_score || 0) - (a.overall_score || 0)).map(uc => (
                <tr key={uc.id} style={{ borderBottom: '1px solid var(--divider)' }}>
                  <td style={{ padding: '12px', fontWeight: 500 }}>{uc.title}</td>
                  <td style={{ padding: '12px', color: 'var(--neutral-500)' }}>{uc.customer_name || '-'}</td>
                  <td style={{ padding: '12px', color: 'var(--neutral-500)' }}>{uc.department || '-'}</td>
                  <td style={{ padding: '12px', fontWeight: 'bold', color: getScoreColor(uc.overall_score || 0) }}>
                    {uc.overall_score?.toFixed(1)}
                  </td>
                  <td style={{ padding: '12px', color: 'var(--status-positive)' }}>
                    ${uc.estimated_savings?.toLocaleString() || '0'}
                  </td>
                  <td style={{ padding: '12px', color: 'var(--brand-700)' }}>
                    ${uc.estimated_revenue?.toLocaleString() || '0'}
                  </td>
                  <td style={{ padding: '12px', fontWeight: 600 }}>
                    ${((uc.estimated_savings || 0) + (uc.estimated_revenue || 0)).toLocaleString()}
                  </td>
                  <td style={{ padding: '12px', color: 'var(--neutral-500)' }}>{uc.timeline_estimate || '-'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* Top 5 Impact / Revenue Candidates */}
      <h3 style={{ margin: '0 0 12px 0', fontSize: '1.1rem', color: 'var(--neutral-700)' }}>Top 5 Impact / Revenue Candidates</h3>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(300px, 1fr))', gap: '16px' }}>
        {scored.sort((a, b) => ((b.estimated_savings || 0) + (b.estimated_revenue || 0)) - ((a.estimated_savings || 0) + (a.estimated_revenue || 0))).slice(0, 5).map(uc => (
          <div key={uc.id} style={{
            background: 'var(--neutral-0)',
            borderRadius: 'var(--radius)',
            padding: '20px',
            boxShadow: 'var(--shadow-card)',
            border: '1px solid var(--divider)',
          }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: '12px' }}>
              <div>
                <h4 style={{ margin: '0 0 4px 0', fontSize: '1rem', color: 'var(--ink)' }}>{uc.title}</h4>
                <div style={{ fontSize: '0.8rem', color: 'var(--neutral-500)' }}>{uc.customer_name || '-'} · {uc.department || 'No department'}</div>
              </div>
              <div style={{
                padding: '4px 12px',
                borderRadius: 'var(--radius)',
                background: getScoreColor(uc.overall_score || 0) + '20',
                color: getScoreColor(uc.overall_score || 0),
                fontWeight: 'bold',
                fontSize: '0.9rem',
              }}>
                {uc.overall_score?.toFixed(1)}
              </div>
            </div>
            <div style={{ display: 'flex', gap: '12px', marginBottom: '12px' }}>
              <div style={{ flex: 1, textAlign: 'center', padding: '8px', background: 'var(--neutral-0)', borderRadius: 'var(--radius)' }}>
                <div style={{ fontSize: '0.7rem', color: 'var(--neutral-500)', marginBottom: '2px' }}>Savings</div>
                <div style={{ fontSize: '1rem', fontWeight: 'bold', color: 'var(--status-positive)' }}>
                  ${uc.estimated_savings?.toLocaleString() || '0'}
                </div>
              </div>
              <div style={{ flex: 1, textAlign: 'center', padding: '8px', background: 'var(--neutral-0)', borderRadius: 'var(--radius)' }}>
                <div style={{ fontSize: '0.7rem', color: 'var(--neutral-500)', marginBottom: '2px' }}>Revenue</div>
                <div style={{ fontSize: '1rem', fontWeight: 'bold', color: 'var(--brand-700)' }}>
                  ${uc.estimated_revenue?.toLocaleString() || '0'}
                </div>
              </div>
            </div>
            <div style={{ fontSize: '0.8rem', color: 'var(--neutral-500)' }}>
              Impact: <strong>${((uc.estimated_savings || 0) + (uc.estimated_revenue || 0)).toLocaleString()}</strong>
              {uc.impact_category && <span> · Category: {uc.impact_category}</span>}
            </div>
          </div>
        ))}
      </div>

      {/* Readiness Insights (customer-scoped only) */}
      {customer && (
        <AnalyticsDashboard
          key={`biz-correlation-${customer.id}`}
          selectedCustomerId={customer.id}
          selectedCustomerName={customer.name}
          section="correlation"
        />
      )}
    </div>
  );
}

function ImpactCard({ value, label, subtext, color, icon }: { value: string; label: string; subtext: string; color: string; icon: string }) {
  return (
    <div style={{ background: 'var(--neutral-0)', borderRadius: 'var(--radius)', padding: '20px', boxShadow: 'var(--shadow-card)', border: '1px solid var(--divider)' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '8px' }}>
        <span style={{ fontSize: '1.5rem' }}>{icon}</span>
        <span style={{ fontSize: '0.7rem', color: 'var(--neutral-500)', background: `color-mix(in srgb, ${color} 10%, transparent)`, padding: '4px 8px', borderRadius: 'var(--radius-sm)' }}>{label}</span>
      </div>
      <div style={{ fontSize: '1.8rem', fontWeight: 'bold', color }}>{value}</div>
      <div style={{ fontSize: '0.8rem', color: 'var(--neutral-500)', marginTop: '4px' }}>{subtext}</div>
    </div>
  );
}
export default BusinessImpact;
