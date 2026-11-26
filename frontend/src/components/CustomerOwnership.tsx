/**
 * Customer Ownership — the admin review queue for placeholder accounts.
 *
 * Accounts whose seed row named "admin" (or a name-only rep with no email)
 * as the owner are placeholders, not real ownership. They land here flagged
 * ``needs_review`` with admin as the temporary primary owner. A Sales Admin /
 * Global Admin resolves each by naming the real primary owner; the change
 * runs as a standard audited ownership transfer (old temporary owner becomes
 * co_owner, never dropped).
 *
 * Backed by GET/POST /api/admin/ownership-review/. The backend is the
 * authorization boundary — this component hides itself for non-admins.
 *
 * The queue is paginated (10/20/50/100 per page, default 20) via the shared
 * ListPager control.
 */
import { useCallback, useEffect, useState } from 'react';
import type { CSSProperties } from 'react';
import { api, getAuthIsAdmin } from '../lib/api';
import { ListPager, useListPager } from './ListPager';
import type { OwnershipReviewItem, UserResponse } from '../types/use_case';

interface CustomerOwnershipProps {
  /** Open a customer's dashboard (sets the selected customer + view). */
  onOpenCustomer?: (name: string) => void;
}

const cardStyle: CSSProperties = {
  background: 'var(--neutral-0)', borderRadius: 'var(--radius)',
  boxShadow: 'var(--shadow-card)', padding: '16px 20px',
};
const headingCellStyle: CSSProperties = {
  padding: '12px 16px', textAlign: 'left', fontSize: '0.85rem',
  fontWeight: 600, color: 'var(--neutral-500)',
};
const cellStyle: CSSProperties = { padding: '12px 16px', verticalAlign: 'middle' };
const selectStyle: CSSProperties = {
  padding: '8px 10px', borderRadius: 'var(--radius)', border: '1px solid var(--divider)',
  fontSize: '0.85rem', minWidth: '220px',
};

export function CustomerOwnership({ onOpenCustomer }: CustomerOwnershipProps) {
  const isAdmin = getAuthIsAdmin();
  const [items, setItems] = useState<OwnershipReviewItem[]>([]);
  const [users, setUsers] = useState<UserResponse[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const [choice, setChoice] = useState<Record<number, number>>({});
  const [busy, setBusy] = useState<number | null>(null);

  const load = useCallback(async () => {
    setError(null);
    try {
      const [rev, allUsers] = await Promise.all([
        api.getOwnershipReview(),
        api.getAllUsers(),
      ]);
      setItems(rev.items);
      setUsers(allUsers);
      setLoaded(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load the customer ownership queue');
    }
  }, []);

  useEffect(() => {
    if (!isAdmin) return;
    void load();
  }, [isAdmin, load]);

  const pager = useListPager(items);

  if (!isAdmin) return null;

  const resolve = async (item: OwnershipReviewItem) => {
    const uid = choice[item.customer_id];
    if (!uid) return;
    setBusy(item.customer_id);
    setSuccess(null);
    setError(null);
    try {
      await api.resolveOwnershipReview(item.customer_id, uid);
      setSuccess(`${item.name} resolved — ownership transferred and audited.`);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to resolve ownership');
    } finally {
      setBusy(null);
    }
  };

  const userLabel = (u: UserResponse) => u.display_name || u.username;

  return (
    <div style={{ padding: '24px', maxWidth: '1100px', margin: '0 auto' }}>
      <div style={{ marginBottom: '20px' }}>
        <h1 style={{ margin: '0 0 4px 0', fontSize: '1.5rem', color: 'var(--ink)' }}>Customer Ownership</h1>
        <p style={{ margin: 0, color: 'var(--neutral-500)', fontSize: '0.9rem' }}>
          Placeholder accounts — the seed named <strong>admin</strong> (or a rep with no email) as owner.
          Assign the real primary owner; each change is a standard audited transfer.
        </p>
      </div>

      {error && (
        <div role="alert" aria-live="assertive" style={{ padding: '10px 14px', background: 'var(--status-negative-soft)', color: 'var(--status-negative)', borderLeft: '4px solid var(--status-negative)', marginBottom: '16px', fontWeight: 500 }}>
          {error}
        </div>
      )}
      {success && (
        <div role="status" aria-live="polite" style={{ padding: '10px 14px', background: 'var(--status-positive-soft)', color: 'var(--status-positive)', borderLeft: '4px solid var(--status-positive)', marginBottom: '16px', fontWeight: 500 }}>
          {success}
        </div>
      )}

      {!loaded ? (
        <div role="status" style={{ padding: '40px', textAlign: 'center', color: 'var(--neutral-500)' }}>Loading customer ownership…</div>
      ) : items.length === 0 ? (
        <div style={cardStyle}>
          <p style={{ margin: 0, textAlign: 'center', color: 'var(--neutral-500)' }}>No accounts awaiting ownership review.</p>
        </div>
      ) : (
        <div style={{ ...cardStyle, padding: '8px 20px 16px 20px' }}>
          <ListPager {...pager.pagerProps} ariaLabel="Accounts per page" />
          <div style={{ overflowX: 'auto' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse' }}>
              <thead>
                <tr style={{ borderBottom: '2px solid var(--divider)' }}>
                  <th style={headingCellStyle}>Account</th>
                  <th style={headingCellStyle}>Temporary owner</th>
                  <th style={headingCellStyle}>New primary owner</th>
                  <th style={headingCellStyle} aria-hidden="true"></th>
                </tr>
              </thead>
              <tbody>
                {pager.visible.map((item) => (
                  <tr key={item.customer_id} style={{ borderBottom: '1px solid var(--neutral-100)' }}>
                    <td style={cellStyle}>
                      <div style={{ fontWeight: 600, color: 'var(--ink)' }}>
                        {item.name}
                        {onOpenCustomer && (
                          <button
                            role="button"
                            aria-label={`Open ${item.name}`}
                            onClick={() => onOpenCustomer(item.name)}
                            style={{ marginLeft: '8px', background: 'none', border: 'none', color: 'var(--brand-700)', cursor: 'pointer', fontSize: '0.8rem', textDecoration: 'underline' }}
                          >
                            open →
                          </button>
                        )}
                      </div>
                    </td>
                    <td style={{ ...cellStyle, color: 'var(--neutral-500)', fontSize: '0.85rem' }}>
                      {item.current_owner || '—'}
                    </td>
                    <td style={cellStyle}>
                      <select
                        aria-label={`New primary owner for ${item.name}`}
                        value={choice[item.customer_id] ?? ''}
                        onChange={(e) => setChoice((c) => ({ ...c, [item.customer_id]: Number(e.target.value) || 0 }))}
                        style={selectStyle}
                      >
                        <option value="">Select primary owner…</option>
                        {users.map((u) => (
                          <option key={u.id} value={u.id}>{userLabel(u)}{u.email ? ` <${u.email}>` : ''}</option>
                        ))}
                      </select>
                    </td>
                    <td style={{ ...cellStyle, textAlign: 'right', whiteSpace: 'nowrap' }}>
                      <button
                        role="button"
                        aria-label={`Resolve ownership for ${item.name}`}
                        onClick={() => void resolve(item)}
                        disabled={!choice[item.customer_id] || busy === item.customer_id}
                        style={{
                          padding: '8px 18px', borderRadius: 'var(--radius)', border: 'none',
                          background: choice[item.customer_id] && busy !== item.customer_id ? 'var(--brand-500)' : 'var(--neutral-400)',
                          color: 'var(--neutral-0)', fontWeight: 600, cursor: choice[item.customer_id] ? 'pointer' : 'not-allowed',
                        }}
                      >
                        {busy === item.customer_id ? 'Saving…' : 'Resolve'}
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}

export default CustomerOwnership;
