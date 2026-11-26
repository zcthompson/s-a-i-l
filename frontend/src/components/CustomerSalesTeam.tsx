/**
 * Admin-only per-customer Sales team editor (0.2.10).
 *
 * The operator's pre-reseed correction surface: primary rep, sales manager,
 * inside sales and sales ops for ONE customer. Backed by
 * GET/PUT /api/customers/{name}/sales-team/ (system admin only; the backend
 * is the authorization boundary — this component merely hides itself).
 *
 * Inside-sales is rendered as a list view: every current assignment is a row
 * showing the rep name, an auto-linked badge + link rationale when the row
 * was auto-linked at golden-seed time, and a Remove action on EVERY row —
 * any assigned inside-sales person can be removed before saving (including
 * seeded rows), which the golden pull relies on for pre-seed cleanup. An Add
 * dropdown lets the operator append a new inside-sales assignment;
 * manually-added rows are never auto-linked. Sales ops remains a
 * single-select dropdown.
 */
import { useEffect, useState } from 'react';
import { api, getAuthIsAdmin } from '../lib/api';
import type { CustomerSalesTeam as SalesTeamState, UserResponse } from '../types/use_case';

interface CustomerSalesTeamProps {
  customerName: string;
  /** Called after a successful save so the read-only header can refresh. */
  onSaved?: () => void | Promise<void>;
}

interface InsideAssignment {
  user_id: number;
  name: string;
  auto_linked: boolean;
  link_reason: string | null;
}

const sectionStyle: React.CSSProperties = {
  background: 'var(--neutral-0)', borderRadius: 'var(--radius)',
  boxShadow: 'var(--shadow-sm)', padding: '16px 20px', marginBottom: '24px',
};
const labelStyle: React.CSSProperties = {
  display: 'flex', flexDirection: 'column', gap: '4px',
  fontSize: '0.82rem', color: 'var(--neutral-700)', fontWeight: 600,
};
const selectStyle: React.CSSProperties = {
  padding: '6px 8px', borderRadius: 'var(--radius)', border: '1px solid var(--divider)',
  fontSize: '0.88rem', minWidth: '220px', background: 'var(--neutral-0)', color: 'var(--ink)',
};
const rowStyle: React.CSSProperties = {
  display: 'flex', alignItems: 'center', gap: '10px', padding: '6px 10px',
  borderRadius: 'var(--radius)', border: '1px solid var(--divider)', background: 'var(--neutral-0)',
};
const badgeStyle: React.CSSProperties = {
  display: 'inline-block', padding: '2px 6px', borderRadius: 'var(--radius)',
  fontSize: '0.72rem', fontWeight: 600, marginLeft: '6px',
};
const reasonStyle: React.CSSProperties = {
  fontSize: '0.74rem', color: 'var(--neutral-600)', marginTop: '2px',
};
const btnStyle: React.CSSProperties = {
  padding: '4px 8px', borderRadius: 'var(--radius)', border: '1px solid var(--divider)',
  background: 'var(--neutral-0)', fontSize: '0.78rem', cursor: 'pointer',
};
const removeBtnStyle: React.CSSProperties = {
  ...btnStyle,
  color: 'var(--status-warning)',
  border: '1px solid var(--status-warning)',
};

function userLabel(u: UserResponse): string {
  return u.display_name || u.username;
}

export function CustomerSalesTeam({ customerName, onSaved }: CustomerSalesTeamProps) {
  const isAdmin = getAuthIsAdmin();
  const [users, setUsers] = useState<UserResponse[]>([]);
  const [rep, setRep] = useState<number | null>(null);
  const [manager, setManager] = useState<number | null>(null);
  const [insideAssignments, setInsideAssignments] = useState<InsideAssignment[]>([]);
  const [ops, setOps] = useState<number | null>(null);
  const [insideSelect, setInsideSelect] = useState<number | null>(null);
  const [loaded, setLoaded] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  const apply = (team: SalesTeamState) => {
    setRep(team.primary_rep?.user_id ?? null);
    setManager(team.manager?.user_id ?? null);
    setInsideAssignments(team.inside_sales.map((u) => ({
      user_id: u.user_id,
      name: u.name,
      auto_linked: u.auto_linked,
      link_reason: u.link_reason,
    })));
    setOps(team.sales_ops[0]?.user_id ?? null);
  };

  useEffect(() => {
    if (!isAdmin) return;
    let cancelled = false;
    setLoaded(false);
    setError(null);
    setSuccess(null);
    (async () => {
      try {
        const [allUsers, team] = await Promise.all([
          api.getAllUsers(),
          api.getCustomerSalesTeam(customerName),
        ]);
        if (cancelled) return;
        setUsers(allUsers);
        apply(team);
        setLoaded(true);
      } catch (err) {
        if (cancelled) return;
        setError(err instanceof Error ? err.message : 'Failed to load sales team');
      }
    })();
    return () => { cancelled = true; };
  }, [customerName, isAdmin]);

  if (!isAdmin) return null;

  const insideAvailable = users.filter(
    (u) => u.sales_role === 'inside_sales' &&
      !insideAssignments.some((a) => a.user_id === u.id),
  );

  const save = async () => {
    setError(null);
    setSuccess(null);
    if (rep === null) {
      setError('Select a primary rep');
      return;
    }
    setSaving(true);
    try {
      const insideIds = insideAssignments.map((a) => a.user_id);
      const opsIds = ops == null ? [] : [ops];
      const team = await api.updateCustomerSalesTeam(customerName, {
        primary_rep_user_id: rep,
        manager_user_id: manager,
        inside_sales_user_ids: insideIds,
        sales_ops_user_ids: opsIds,
      });
      apply(team);
      setSuccess('Sales team saved');
      if (onSaved) await onSaved();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to save sales team');
    } finally {
      setSaving(false);
    }
  };

  const removeInside = (user_id: number) => {
    setInsideAssignments((prev) => prev.filter((a) => a.user_id !== user_id));
  };

  const addInside = () => {
    if (insideSelect == null) return;
    if (insideAssignments.some((a) => a.user_id === insideSelect)) return;
    const user = users.find((u) => u.id === insideSelect);
    if (!user) return;
    setInsideAssignments((prev) => [...prev, {
      user_id: user.id,
      name: user.display_name || user.username,
      auto_linked: false,
      link_reason: null,
    }]);
    setInsideSelect(null);
  };

  const dropdown = (
    testId: string,
    label: string,
    selected: number | null,
    setList: (v: number | null) => void,
    available: UserResponse[],
  ) => (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
      <span style={{ fontSize: '0.82rem', color: 'var(--neutral-700)', fontWeight: 600 }}>{label}</span>
      <select
        data-testid={testId}
        aria-label={label}
        style={selectStyle}
        value={selected == null ? '' : String(selected)}
        onChange={(e) => {
          const v = e.target.value;
          setList(v === '' ? null : Number(v));
        }}
      >
        <option value="">— none —</option>
        {available.map((u) => (
          <option key={u.id} value={String(u.id)}>{userLabel(u)}</option>
        ))}
      </select>
    </div>
  );

  const addControl = () => (
    <div style={{ display: 'flex', gap: '6px', alignItems: 'center' }}>
      <select
        data-testid="sales-team-inside-add"
        aria-label="Add inside sales"
        style={{ ...selectStyle, minWidth: '200px' }}
        value={insideSelect == null ? '' : String(insideSelect)}
        onChange={(e) => {
          const v = e.target.value;
          setInsideSelect(v === '' ? null : Number(v));
        }}
      >
        <option value="">+ Add inside sales</option>
        {insideAvailable.map((u) => (
          <option key={u.id} value={String(u.id)}>{userLabel(u)}</option>
        ))}
      </select>
      {insideSelect != null && (
        <button
          type="button"
          onClick={addInside}
          disabled={saving}
          style={{ ...btnStyle, background: 'var(--brand-500)', color: 'var(--neutral-0)' }}
        >
          Add
        </button>
      )}
    </div>
  );

  return (
    <section aria-label="Sales team" style={sectionStyle}>
      <h3 style={{ margin: '0 0 12px 0', fontSize: '1rem', color: 'var(--neutral-700)' }}>Sales team</h3>
      {error && (
        <div role="alert" style={{ color: 'var(--status-warning)', fontSize: '0.85rem', marginBottom: '8px' }}>{error}</div>
      )}
      {success && (
        <div role="status" style={{ color: 'var(--status-positive)', fontSize: '0.85rem', marginBottom: '8px' }}>{success}</div>
      )}
      {loaded && (
        <>
          <div style={{ display: 'flex', gap: '20px', flexWrap: 'wrap', alignItems: 'flex-start' }}>
            <label style={labelStyle}>
              Primary rep
              <select
                data-testid="sales-team-rep-select"
                aria-label="Primary rep"
                style={selectStyle}
                value={rep ?? ''}
                onChange={(e) => setRep(e.target.value ? Number(e.target.value) : null)}
              >
                <option value="">—</option>
                {users.map((u) => (
                  <option key={u.id} value={u.id}>{userLabel(u)}</option>
                ))}
              </select>
            </label>
            <label style={labelStyle}>
              Sales manager
              <select
                data-testid="sales-team-manager-select"
                aria-label="Sales manager"
                style={selectStyle}
                value={manager ?? ''}
                onChange={(e) => setManager(e.target.value ? Number(e.target.value) : null)}
              >
                <option value="">—</option>
                {users.map((u) => (
                  <option key={u.id} value={u.id}>{userLabel(u)}</option>
                ))}
              </select>
            </label>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
              <label style={labelStyle}>Inside sales</label>
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: '8px', alignItems: 'flex-start' }}>
                {insideAssignments.length === 0 && (
                  <div style={{ color: 'var(--neutral-600)', fontSize: '0.8rem' }}>None assigned</div>
                )}
                {insideAssignments.map((a) => (
                  <div key={a.user_id} style={rowStyle} data-testid={`sales-team-inside-row-${a.user_id}`}>
                    <span>{a.name}</span>
                    {a.auto_linked && (
                      <span style={{ ...badgeStyle, background: 'var(--brand-100)', color: 'var(--brand-700)' }}>
                        Auto-linked
                      </span>
                    )}
                    {a.link_reason && (
                      <span style={reasonStyle}>{a.link_reason}</span>
                    )}
                    <button
                      type="button"
                      data-testid={`sales-team-inside-remove-${a.user_id}`}
                      onClick={() => removeInside(a.user_id)}
                      disabled={saving}
                      style={removeBtnStyle}
                    >
                      Remove
                    </button>
                  </div>
                ))}
                {insideAssignments.length > 0 && (
                  <div style={{ display: 'flex', alignItems: 'center' }}>
                    {addControl()}
                  </div>
                )}
                {insideAssignments.length === 0 && (
                  <div style={{ display: 'flex', alignItems: 'center' }}>
                    {addControl()}
                  </div>
                )}
              </div>
            </div>
            {dropdown('sales-team-sales-ops', 'Sales ops', ops, setOps,
              users.filter((u) => u.sales_role === 'sales_ops' || (ops != null && ops === u.id)))}
          </div>
          <div style={{ marginTop: '12px' }}>
            <button
              type="button"
              aria-label="Save sales team"
              onClick={save}
              disabled={saving}
              style={{
                padding: '6px 16px', borderRadius: 'var(--radius)', border: 'none',
                background: 'var(--brand-500)', color: 'var(--neutral-0)', fontWeight: 600,
                cursor: saving ? 'default' : 'pointer',
              }}
            >
              {saving ? 'Saving…' : 'Save'}
            </button>
          </div>
        </>
      )}
    </section>
  );
}
