import React, { useEffect, useState } from 'react';
import { api } from '../lib/api';
import { GlobalAdminStats, Customer } from '../types/use_case';
import {
  activeFilterSummary, applyNavPatch, defaultNavState, filterRows, resetNavState, sortRows,
} from '../lib/portfolioNav';
import type { PortfolioNavState } from '../lib/portfolioNav';
import { paginateNav } from '../lib/usePortfolioNavState';
import { PortfolioFilterBar } from './PortfolioFilterBar';
import { CustomerListPager } from './CustomerListPager';

interface AdminConsoleProps {
  onNavigate: (view: string, customerName?: string) => void;
  showPortfolio?: boolean;
}

interface AdminUser {
  id: number;
  username: string;
  /** Nullable: name-only pending owners (prod-seed) have no email until filled in. */
  email: string | null;
  display_name?: string | null;
  department?: string | null;
  role?: string;
  is_admin: number;
  approved: number;
  is_active: number;
}

/** the console table is a summary: the first 10 (matching) users;
 *  full management stays on the All Users view. */
const USERS_CAP = 10;
/** the console Portfolio summary shows the first 10 accounts by
 *  default (H2 v1: filter/sort the complete admin list, paginate locally). */
const PORTFOLIO_NAV_DEFAULTS = { defaultPageSize: 10 };
const PORTFOLIO_SORT_KEYS = ['newest', 'name', 'vertical', 'branch', 'owner'] as const;
const userRoleText = (u: AdminUser) => (u.is_admin ? '👑 Admin' : (u.role || 'member'));
const userStatusText = (u: AdminUser) => (u.approved ? 'Active' : 'Pending');
/** Client-side case-insensitive substring over the displayed columns
 *  (username/email/role/department/status), My Dashboard search semantics. */
const userMatches = (u: AdminUser, needle: string) =>
  needle === '' || [u.username, u.email, userRoleText(u), u.department, userStatusText(u)]
    .filter((v): v is string => typeof v === 'string' && v !== '')
    .join('\n')
    .toLowerCase()
    .includes(needle);

export function AdminConsole({ onNavigate, showPortfolio = true }: AdminConsoleProps) {
  const [stats, setStats] = useState<GlobalAdminStats | null>(null);
  const [database, setDatabase] = useState<string | null>(null);
  const [databaseUnavailable, setDatabaseUnavailable] = useState(false);
  const [users, setUsers] = useState<AdminUser[]>([]);
  const [userForm, setUserForm] = useState({ username: '', email: '', password: '' });
  const [userError, setUserError] = useState<string | null>(null);
  const [userSuccess, setUserSuccess] = useState<string | null>(null);
  // Local state only (no URL sync — the console is a summary surface).
  const [userQuery, setUserQuery] = useState('');
  const [accounts, setAccounts] = useState<Customer[]>([]);
  const [portfolioNav, setPortfolioNav] = useState<PortfolioNavState>(
    () => defaultNavState(null, PORTFOLIO_NAV_DEFAULTS));
  const userNeedle = userQuery.trim().toLowerCase();
  const matchedUsers = users.filter((u) => userMatches(u, userNeedle));
  const visibleUsers = matchedUsers.slice(0, USERS_CAP);
  const userCountLine = userNeedle !== ''
    ? `${matchedUsers.length} of ${users.length} users match${matchedUsers.length > USERS_CAP ? ` — showing the first ${USERS_CAP}` : ''}`
    : users.length > USERS_CAP ? `Showing the first ${USERS_CAP} of ${users.length} users` : `${users.length} user${users.length === 1 ? '' : 's'}`;

  useEffect(() => {
    api.getGlobalAdminStats().then(setStats).catch(() => {});
    api.getAllUsers().then(setUsers).catch(() => {});
    // the complete admin customer list (admin scope = all).
    if (showPortfolio) api.listCustomers().then((rows) => setAccounts(rows ?? [])).catch(() => {});
  }, [showPortfolio]);

  useEffect(() => {
    let active = true;
    if (typeof api.getDatabaseDiagnostics === 'function') {
      api.getDatabaseDiagnostics().then(result => {
        if (active) setDatabase(result.database?.backend || 'unavailable');
      }).catch(() => { if (active) setDatabaseUnavailable(true); });
    } else setDatabaseUnavailable(true);
    return () => { active = false; };
  }, []);

  // console Portfolio summary nav. LOCAL state (no URL sync):
  // on ?view=dashboard HomeDashboard's own Portfolio table already owns the
  // URL nav state, and a second URL-synced surface on the same route would
  // share one state with conflicting page-size defaults (primary ruling on
  // the worker's SR-1). The URL-driven full-portfolio H2 nav stays with that
  // table; this block is the operator-directed first-10 summary.
  const updatePortfolioNav = (patch: Partial<PortfolioNavState>) =>
    setPortfolioNav((s) => applyNavPatch(s, patch));
  const resetPortfolioNav = () =>
    setPortfolioNav((s) => resetNavState(s, PORTFOLIO_NAV_DEFAULTS));
  const portfolioRows = accounts.map((c) => ({
    id: c.id, name: c.name, description: c.description ?? null,
    vertical: c.vertical ?? null, branch: c.branch ?? null,
    salesArea: c.sales_area ?? null, primarySubsidiary: c.primary_subsidiary ?? null,
    primaryRep: c.primary_rep ?? null, managerName: c.manager_name ?? null,
    aliases: c.aliases ?? [], knownMetadata: true,
  }));
  const shownAccounts = sortRows(filterRows(portfolioRows, portfolioNav), portfolioNav);
  const portfolioPager = paginateNav(shownAccounts, portfolioNav, updatePortfolioNav);

  const refreshUsers = () => api.getAllUsers().then(setUsers).catch(() => {});

  const handleCreateUser = async (e: React.FormEvent) => {
    e.preventDefault();
    setUserError(null);
    setUserSuccess(null);
    if (!userForm.username || !userForm.email || !userForm.password) {
      setUserError('All fields are required');
      return;
    }
    // UX audit #13: the form previously validated only non-empty. Check
    // email format + password length client-side so bad input never reaches
    // api.register (mirrors the backend schema: email, password >= 12).
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(userForm.email)) {
      setUserError('Enter a valid email address');
      return;
    }
    if (userForm.password.length < 8) {
      setUserError('Password must be at least 8 characters');
      return;
    }
    try {
      await api.register({
        username: userForm.username,
        email: userForm.email,
        password: userForm.password,
      });
      setUserSuccess(`User ${userForm.username} created (pending approval)`);
      setUserForm({ username: '', email: '', password: '' });
      refreshUsers();
    } catch (err: any) {
      setUserError(err.message || 'Failed to create user');
    }
  };

  const handleApproveUser = async (username: string) => {
    try {
      await api.approveUser(username);
      refreshUsers();
    } catch (err: any) {
      setUserError(err.message || 'Failed to approve user');
    }
  };

  const handleDeleteUser = async (id: number, username: string) => {
    if (!confirm(`Delete user "${username}"? This cannot be undone.`)) return;
    try {
      await api.deleteUser(id);
      refreshUsers();
    } catch (err: any) {
      setUserError(err.message || 'Failed to delete user');
    }
  };

  return (
    <div>
      <div style={{ marginBottom: 24 }}>
        <h1 style={{ margin: 0, fontSize: '1.6rem', color: 'var(--ink)' }}>🛡️ Admin Console</h1>
        <p role="status">Database: {databaseUnavailable ? 'Unavailable' : database === 'postgresql' ? 'PostgreSQL' : database === 'sqlite' ? 'SQLite' : database || 'Loading…'}</p>
        <p style={{ margin: '4px 0 0', color: 'var(--neutral-500)', fontSize: '0.95rem' }}>
          Global system functions, users and application settings
        </p>
      </div>

      {userError && (
        <div style={{ background: 'var(--status-negative-soft)', border: '1px solid var(--status-negative-soft)', color: 'var(--status-negative)', padding: '10px 16px', borderRadius: 'var(--radius)', marginBottom: 16, fontSize: '0.9rem' }}>
          {userError}
        </div>
      )}
      {userSuccess && (
        <div style={{ background: 'var(--status-positive-soft)', border: '1px solid var(--status-positive-soft)', color: 'var(--status-positive)', padding: '10px 16px', borderRadius: 'var(--radius)', marginBottom: 16, fontSize: '0.9rem' }}>
          {userSuccess}
        </div>
      )}

      {/* Stat cards */}
      {stats && (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(min(100%, 150px), 1fr))', gap: 16, marginBottom: 24 }}>
          <StatCard label="Total Users" value={stats.total_users} />
          <StatCard label="Active Users" value={stats.active_users} />
          <StatCard label="Pending" value={stats.pending_users} color="var(--status-warning)" />
          <StatCard label="Admins" value={stats.admin_count ?? 0} />
          <StatCard label="Customers" value={stats.total_customers} />
          <StatCard label="Use Cases" value={stats.total_use_cases} />
        </div>
      )}

      {/* Application functions */}
      <div style={{ background: 'var(--neutral-0)', border: '1px solid var(--divider)', borderRadius: 'var(--radius)', padding: 'clamp(8px, 2vw, 20px)', minWidth: 0, marginBottom: 24 }}>
        <h2 style={{ margin: '0 0 12px', fontSize: '1.1rem', color: 'var(--neutral-700)' }}>⚙️ Application Functions</h2>
        <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap' }}>
          <button
            onClick={() => onNavigate('admin-pending')}
            style={{ padding: '10px 18px', background: 'var(--brand-700)', color: 'var(--neutral-0)', border: 'none', borderRadius: 'var(--radius)', cursor: 'pointer', fontSize: '0.9rem', fontWeight: 600 }}
          >
            Pending Approvals
          </button>
          <button
            onClick={() => onNavigate('admin-users')}
            style={{ padding: '10px 18px', background: 'var(--brand-700)', color: 'var(--neutral-0)', border: 'none', borderRadius: 'var(--radius)', cursor: 'pointer', fontSize: '0.9rem', fontWeight: 600 }}
          >
            All Users
          </button>
          <button
            onClick={() => onNavigate('admin-integrations')}
            style={{ padding: '10px 18px', background: 'var(--brand-700)', color: 'var(--neutral-0)', border: 'none', borderRadius: 'var(--radius)', cursor: 'pointer', fontSize: '0.9rem', fontWeight: 600 }}
          >
            Application Settings
          </button>
        </div>
      </div>

      {/* Portfolio summary: the first 10 accounts, H2 controls,
          click-through to the customer. LOCAL nav state — see the ruling
          note above (no URL sync on this surface). */}
      {showPortfolio && accounts.length > 0 && (
        <div data-testid="admin-console-portfolio" style={{ background: 'var(--neutral-0)', border: '1px solid var(--divider)', borderRadius: 'var(--radius)', padding: 'clamp(8px, 2vw, 20px)', minWidth: 0, marginBottom: 24 }}>
          <h2 style={{ margin: '0 0 12px', fontSize: '1.1rem', color: 'var(--neutral-700)' }}>📊 Portfolio</h2>
          <PortfolioFilterBar
            rows={portfolioRows}
            state={portfolioNav}
            onChange={updatePortfolioNav}
            onReset={resetPortfolioNav}
            filteredCount={shownAccounts.length}
            sortKeys={PORTFOLIO_SORT_KEYS}
            defaults={PORTFOLIO_NAV_DEFAULTS}
            alwaysShowCount
          />
          <CustomerListPager {...portfolioPager.pagerProps} />
          {portfolioPager.visible.length === 0 ? (
            <p data-testid="no-matches" style={{ margin: '8px 0 0', color: 'var(--neutral-500)', fontSize: '0.9rem' }}>
              {activeFilterSummary(portfolioNav)}
            </p>
          ) : (
            <div style={{ marginTop: 12, display: 'flex', flexDirection: 'column', gap: 6 }}>
              {portfolioPager.visible.map((row) => (
                <div
                  key={row.id}
                  role="button"
                  tabIndex={0}
                  aria-label={`Open ${row.name}`}
                  onClick={() => onNavigate('customers', row.name)}
                  onKeyDown={(event) => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); onNavigate('customers', row.name); } }}
                  style={{ padding: '10px 12px', background: 'var(--neutral-0)', border: '1px solid var(--divider)', borderRadius: 'var(--radius)', cursor: 'pointer', fontSize: '0.9rem', display: 'flex', justifyContent: 'space-between', gap: '12px' }}
                >
                  <span style={{ fontWeight: 600, color: 'var(--neutral-900)' }}>{row.name}</span>
                  <span style={{ color: 'var(--neutral-500)', fontSize: '0.8rem', whiteSpace: 'nowrap' }}>
                    {[row.primaryRep, row.vertical, row.branch].filter(Boolean).join(' · ') || '—'}
                  </span>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Users management */}
      <div style={{ background: 'var(--neutral-0)', border: '1px solid var(--divider)', borderRadius: 'var(--radius)', padding: 'clamp(8px, 2vw, 20px)', minWidth: 0, marginBottom: 24 }}>
        <h2 style={{ margin: '0 0 16px', fontSize: '1.1rem', color: 'var(--neutral-700)' }}>👥 Users Management</h2>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(min(100%, 220px), 1fr))', gap: 12, marginBottom: 16 }}>
          <input
            placeholder="Username"
            value={userForm.username}
            onChange={(e) => setUserForm({ ...userForm, username: e.target.value })}
            style={{ padding: '10px 12px', border: '1px solid var(--neutral-300)', borderRadius: 'var(--radius)', fontSize: '0.9rem', minWidth: 0, maxWidth: '100%', boxSizing: 'border-box' }}
          />
          <input
            placeholder="Email"
            type="email"
            value={userForm.email}
            onChange={(e) => setUserForm({ ...userForm, email: e.target.value })}
            style={{ padding: '10px 12px', border: '1px solid var(--neutral-300)', borderRadius: 'var(--radius)', fontSize: '0.9rem', minWidth: 0, maxWidth: '100%', boxSizing: 'border-box' }}
          />
          <input
            placeholder="Password"
            type="password"
            value={userForm.password}
            onChange={(e) => setUserForm({ ...userForm, password: e.target.value })}
            style={{ padding: '10px 12px', border: '1px solid var(--neutral-300)', borderRadius: 'var(--radius)', fontSize: '0.9rem', minWidth: 0, maxWidth: '100%', boxSizing: 'border-box' }}
          />
          <button
            onClick={handleCreateUser}
            style={{ padding: '10px 18px', background: 'var(--brand-500)', color: 'var(--neutral-0)', border: 'none', borderRadius: 'var(--radius)', cursor: 'pointer', fontSize: '0.9rem', fontWeight: 600 }}
          >
            + Add User
          </button>
        </div>

        {users.length > 0 && (
          <div style={{ display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap', marginBottom: 8 }}>
            <input
              type="search"
              aria-label="Search users"
              placeholder="Username, email, role, department, status…"
              value={userQuery}
              onChange={(e) => setUserQuery(e.target.value)}
              style={{ flex: '1 1 260px', minWidth: 0, maxWidth: '100%', boxSizing: 'border-box', padding: '6px 10px', border: '1px solid var(--divider)', borderRadius: 'var(--radius-sm)', fontSize: '0.85rem' }}
            />
            <span role="status" aria-live="polite" data-testid="admin-users-match-count" style={{ fontSize: '0.8rem', color: 'var(--neutral-500)' }}>
              {userCountLine}
            </span>
            {userNeedle !== '' && (
              <button
                type="button"
                aria-label="Reset user search"
                onClick={() => setUserQuery('')}
                style={{ padding: '3px 10px', background: 'var(--neutral-0)', color: 'var(--brand-700)', border: '1px solid var(--brand-500)', borderRadius: 'var(--radius-sm)', cursor: 'pointer', fontSize: '0.8rem' }}
              >
                Reset
              </button>
            )}
            <button
              type="button"
              aria-label="View all users"
              onClick={() => onNavigate('admin-users')}
              style={{ marginLeft: 'auto', padding: '3px 10px', background: 'none', color: 'var(--brand-700)', border: '1px solid var(--divider)', borderRadius: 'var(--radius-sm)', cursor: 'pointer', fontSize: '0.8rem', fontWeight: 600 }}
            >
              View all users
            </button>
          </div>
        )}

        {users.length > 0 && (
          <div style={{ overflowX: 'auto', maxWidth: '100%' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.85rem' }}>
            <thead>
              <tr style={{ background: 'var(--neutral-50)', color: 'var(--neutral-500)' }}>
                <th style={{ padding: '8px 10px', textAlign: 'left', borderBottom: '1px solid var(--divider)' }}>User</th>
                <th style={{ padding: '8px 10px', textAlign: 'left', borderBottom: '1px solid var(--divider)' }}>Email</th>
                <th style={{ padding: '8px 10px', textAlign: 'left', borderBottom: '1px solid var(--divider)' }}>Role</th>
                <th style={{ padding: '8px 10px', textAlign: 'left', borderBottom: '1px solid var(--divider)' }}>Department</th>
                <th style={{ padding: '8px 10px', textAlign: 'center', borderBottom: '1px solid var(--divider)' }}>Status</th>
                <th style={{ padding: '8px 10px', textAlign: 'right', borderBottom: '1px solid var(--divider)' }}>Actions</th>
              </tr>
              </thead>
              <tbody>
              {visibleUsers.map((u) => (
                <tr key={u.id} style={{ borderBottom: '1px solid var(--neutral-100)' }}>
                  <td style={{ padding: '8px 10px', fontWeight: 600, color: 'var(--neutral-900)' }}>
                    {u.display_name || u.username}
                  </td>
                  <td style={{ padding: '8px 10px', color: 'var(--neutral-700)' }}>{u.email || '— (not set yet)'}</td>
                  <td style={{ padding: '8px 10px', color: 'var(--neutral-700)' }}>{u.is_admin ? '👑 Admin' : (u.role || 'member')}</td>
                  <td style={{ padding: '8px 10px', color: 'var(--neutral-700)' }}>{u.department || '—'}</td>
                  <td style={{ padding: '8px 10px', textAlign: 'center' }}>
                    {u.approved ? (
                      <span style={{ color: 'var(--status-positive)', fontWeight: 600 }}>● Active</span>
                    ) : (
                      <span style={{ color: 'var(--status-warning)', fontWeight: 600 }}>◐ Pending</span>
                    )}
                  </td>
                  <td style={{ padding: '8px 10px', textAlign: 'right', whiteSpace: 'nowrap' }}>
                    {!u.approved && (
                      <button
                        onClick={() => handleApproveUser(u.username)}
                        style={{ marginRight: 8, padding: '4px 10px', background: 'var(--status-positive)', color: 'var(--neutral-0)', border: 'none', borderRadius: 'var(--radius)', cursor: 'pointer', fontSize: '0.75rem' }}
                      >
                        Approve
                      </button>
                    )}
                    {!u.is_admin && (
                      <button
                        onClick={() => handleDeleteUser(u.id, u.username)}
                        style={{ padding: '4px 10px', background: 'var(--status-negative)', color: 'var(--neutral-0)', border: 'none', borderRadius: 'var(--radius)', cursor: 'pointer', fontSize: '0.75rem' }}
                      >
                        Delete
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          </div>
        )}
      </div>
    </div>
  );
}

function StatCard({ label, value, color }: { label: string; value: number; color?: string }) {
  return (
    <div style={{ background: 'var(--neutral-0)', border: '1px solid var(--divider)', borderRadius: 'var(--radius)', padding: '16px', textAlign: 'center' }}>
      <div style={{ fontSize: '1.8rem', fontWeight: 700, color: color || 'var(--brand-700)' }}>{value}</div>
      <div style={{ fontSize: '0.8rem', color: 'var(--neutral-500)', marginTop: 4 }}>{label}</div>
    </div>
  );
}
