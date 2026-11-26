import { useEffect, useState } from 'react';
import { api } from '../lib/api';
import type { RedHatOpportunityReport } from '../types/redhatOpportunity';

export function CustomerRedHatOpportunities({ customerId }: { customerId: number }) {
  const [data, setData] = useState<RedHatOpportunityReport | null>(null);
  const [error, setError] = useState(false);
  useEffect(() => {
    let active = true;
    setData(null); setError(false);
    Promise.resolve().then(() => api.getRedHatOpportunityReport(customerId))
      .then(value => { if (active) setData(value); }).catch(() => { if (active) setError(true); });
    return () => { active = false; };
  }, [customerId]);
  if (!data?.import && !error) return null;
  return <section aria-label="Red Hat opportunities" style={{ margin: '24px 0', overflowWrap: 'anywhere' }}>
    <h3 style={{ fontSize: '1.1rem', color: 'var(--neutral-700)' }}>Red Hat Opportunities</h3>
    {error ? <p role="status">Red Hat opportunity information is unavailable.</p> : <>
      <p style={{ color: 'var(--neutral-600)', fontSize: '0.85rem' }}>Reported by Red Hat · {data?.import?.created_at.slice(0, 10)}. These are potential opportunities, not confirmed deals.</p>
      {data?.opportunities.length === 0 ? <p>No opportunities reported in the latest import.</p> :
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(min(280px, 100%), 1fr))', gap: 12 }}>
          {data?.opportunities.map(op => <article key={op.type} style={{ background: 'var(--neutral-0)', border: '1px solid var(--divider)', borderRadius: 'var(--radius)', padding: 14, boxShadow: 'var(--shadow-card)' }}>
            <span style={{ fontSize: '0.72rem', color: 'var(--brand-700)', fontWeight: 600, background: 'var(--brand-50)', padding: '2px 10px', borderRadius: 'var(--radius-pill)' }}>RED HAT OPPORTUNITY</span>
            <h4 style={{ color: 'var(--ink)', margin: '10px 0 8px' }}>{op.title}</h4>
            <p style={{ fontSize: '0.85rem', margin: '4px 0' }}><strong>Matched account:</strong> {data.matched_account}</p>
            <p style={{ fontSize: '0.85rem', margin: '4px 0' }}><strong>Reported vendors:</strong> {op.vendors.length ? op.vendors.join(', ') : 'Not recorded'}</p>
            <p style={{ fontSize: '0.85rem', margin: '4px 0' }}><strong>Red Hat representative:</strong> {op.redhat_representatives.length ? op.redhat_representatives.join(', ') : 'Not recorded'}</p>
          </article>)}
        </div>}
    </>}
  </section>;
}
