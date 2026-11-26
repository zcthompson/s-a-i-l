import { ActionButton } from '../components/ActionButton';
import { SectionIcon } from '../components/SectionIcon';
import { useDialogFocus } from '../lib/useDialogFocus';
import { useRef } from 'react';
import { useState, useEffect } from 'react';
import { createPortal } from 'react-dom';
import { api } from '../lib/api';
import { getAuthUsername } from '../lib/auth';
import type { UserResponse } from '../types/use_case';

type AdminView = 'pending' | 'all-users';

interface AdminPageProps {
  onNavigate?: (view: string) => void;
  // Authoritative tab from the parent view (?view=admin-pending /
  // ?view=admin-users). The page previously kept its own tab state seeded
  // from this prop at mount only — but Home serves ONE <AdminPage> element
  // for every admin-* view, so the instance survives view changes and the
  // stale tab stuck (sidebar All Users -> Pending did nothing). The parent
  // view is the single source of truth; the in-page tabs drive it back.
  activeView?: AdminView;
}

const ROLE_STYLES: Record<string, { bg: string; color: string; label: string }> = {
  admin: { bg: 'var(--brand-50)', color: 'var(--brand-700)', label: 'Admin' },
  user: { bg: 'var(--brand-50)', color: 'var(--brand-700)', label: 'User' },
  auditor: { bg: 'var(--neutral-100)', color: 'var(--neutral-700)', label: 'Auditor' },
  ps_admin: { bg: 'var(--brand-100)', color: 'var(--brand-700)', label: 'PS Admin' },
};

// Fixed table layout needs explicit widths; Actions must fit its 2x2 button grid.
const PENDING_COLUMN_WIDTHS: Record<string, string> = { Username: '190px', 'Display Name': '180px', Email: '180px', Department: '130px', 'Sales Role': '140px', Registered: '110px', Actions: '200px' };
// Fixed-width columns; User, Email and Department share the remaining width and truncate (full value in the tooltip).
const ALL_USERS_COLUMN_WIDTHS: Record<string, string | undefined> = { Registered: '105px', Department: '110px', Access: '115px', Status: '105px', Actions: '205px' };

function roleBadge(role: string) {
  return ROLE_STYLES[role] || ROLE_STYLES.user;
}

export function AdminPage({ onNavigate, activeView = 'pending' }: AdminPageProps) {
  const [pendingUsers, setPendingUsers] = useState<UserResponse[]>([]);
  const [allUsers, setAllUsers] = useState<UserResponse[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const [actionLoading, setActionLoading] = useState<string | null>(null);
  const [searchTerm, setSearchTerm] = useState('');
  const [statusFilter, setStatusFilter] = useState<string>('all');
  const [roleFilter, setRoleFilter] = useState<string>('all');

  // Edit modal state
  const [editingUser, setEditingUser] = useState<UserResponse | null>(null);
  const [editDisplayName, setEditDisplayName] = useState('');
  const [editEmail, setEditEmail] = useState('');
  const [editDepartment, setEditDepartment] = useState('');
  const [editRole, setEditRole] = useState('user');
  const [editSalesRole, setEditSalesRole] = useState('');

  // Password-reset modal state
  const [resetUser, setResetUser] = useState<UserResponse | null>(null);
  const [newPassword, setNewPassword] = useState('');

  const [addingUser, setAddingUser] = useState(false);
  const [createError, setCreateError] = useState<string | null>(null);
  const [createUsername, setCreateUsername] = useState('');
  const [createDisplayName, setCreateDisplayName] = useState('');
  const [createEmail, setCreateEmail] = useState('');
  const [createPassword, setCreatePassword] = useState('');
  const [createDepartment, setCreateDepartment] = useState('');
  const [createRole, setCreateRole] = useState('user');
  const [createSalesRole, setCreateSalesRole] = useState('');
  const [createActive, setCreateActive] = useState(false);

  const dialogRef = useRef<HTMLDivElement>(null);
  const dialogIdentity = addingUser && activeView === 'all-users' ? 'create' : editingUser && activeView === 'all-users' ? `edit-${editingUser.id}` : resetUser ? `reset-${resetUser.id}` : null;
  useDialogFocus(dialogRef, dialogIdentity, () => {
    if (actionLoading) return;
    setAddingUser(false); setEditingUser(null); setResetUser(null);
  });

  const meUsername = getAuthUsername();

  // Effective role: is_admin is the source of admin authority, so an
  // account with is_admin=1 always shows as Admin regardless of its label.
  const effRole = (user: UserResponse) =>
    user.is_admin === 1 ? 'admin' : (user.role || 'user');

  const loadUsers = async () => {
    try {
      setLoading(true);
      setError(null);
      const [pending, all] = await Promise.all([
        api.getPendingUsers(),
        api.getAllUsers(),
      ]);
      setPendingUsers(pending);
      setAllUsers(all);
    } catch (err: any) {
      setError(err.message || 'Failed to load users');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadUsers();
  }, []);

  const handleApprove = async (username: string) => {
    setActionLoading(username);
    setError(null);
    try {
      await api.approveUser(username);
      await loadUsers();
    } catch (err: any) {
      setError(err.message || 'Approval failed');
    } finally {
      setActionLoading(null);
    }
  };

  const isSelf = (user: UserResponse) => user.username === meUsername;

  const openEdit = (user: UserResponse) => {
    setEditingUser(user);
    setEditDisplayName(user.display_name || '');
    setEditEmail(user.email || '');
    setEditDepartment(user.department || '');
    setEditRole(effRole(user));
    setEditSalesRole(user.sales_role || '');
  };

  const saveEdit = async () => {
    if (!editingUser) return;
    setActionLoading(`edit-${editingUser.id}`);
    setError(null);
    setSuccess(null);
    try {
      const payload: {
        display_name: string;
        email: string;
        department: string;
        role?: string;
        sales_role: string | null;
      } = {
        display_name: editDisplayName,
        email: editEmail,
        department: editDepartment,
        sales_role: editSalesRole || null,
      };
      // Role is editable for other users only (backend enforces this too).
      if (!isSelf(editingUser)) {
        payload.role = editRole;
      }
      await api.updateUser(editingUser.id, payload);
      const updatedUsername = editingUser.username;
      setEditingUser(null);
      await loadUsers();
      setSuccess(`Saved ${updatedUsername}.`);
    } catch (err: any) {
      setError(err.message || 'Update failed');
    } finally {
      setActionLoading(null);
    }
  };

  const openReset = (user: UserResponse) => {
    setResetUser(user);
    setNewPassword('');
  };

  const saveReset = async () => {
    if (!resetUser) return;
    setActionLoading(`reset-${resetUser.id}`);
    setError(null);
    try {
      await api.resetUserPassword(resetUser.id, newPassword);
      const username = resetUser.username;
      setResetUser(null);
      setNewPassword('');
      setSuccess(`Password reset for ${username}.`);
    } catch (err: any) {
      setError(err.message || 'Password reset failed');
    } finally {
      setActionLoading(null);
    }
  };

  const handleSetActive = async (user: UserResponse, active: boolean) => {
    const verb = active ? 'activate' : 'deactivate';
    if (!window.confirm(`${active ? 'Activate' : 'Deactivate'} account "${user.username}"?`)) {
      return;
    }
    setActionLoading(`${verb}-${user.id}`);
    setError(null);
    try {
      if (active) {
        await api.activateUser(user.id);
      } else {
        await api.deactivateUser(user.id);
      }
      await loadUsers();
    } catch (err: any) {
      setError(err.message || 'Action failed');
    } finally {
      setActionLoading(null);
    }
  };

  const handleDelete = async (user: UserResponse) => {
    if (!window.confirm(`Delete user "${user.username}"? This removes the account and its customer access.`)) {
      return;
    }
    setActionLoading(`delete-${user.id}`);
    setError(null);
    try {
      await api.deleteUser(user.id);
      await loadUsers();
    } catch (err: any) {
      setError(err.message || 'Delete failed');
    } finally {
      setActionLoading(null);
    }
  };

  const openCreate = () => {
    setCreateError(null);
    setCreateUsername('');
    setCreateDisplayName('');
    setCreateEmail('');
    setCreatePassword('');
    setCreateDepartment('');
    setCreateRole('user');
    setCreateSalesRole('');
    setCreateActive(false);
    setAddingUser(true);
  };

  const saveCreate = async () => {
    setActionLoading('create-user');
    setCreateError(null);
    setSuccess(null);
    try {
      await api.createUser({
        username: createUsername.trim(),
        ...(createDisplayName.trim() ? { display_name: createDisplayName.trim() } : {}),
        ...(createEmail.trim() ? { email: createEmail.trim() } : {}),
        password: createPassword,
        ...(createDepartment ? { department: createDepartment } : {}),
        role: createRole,
        ...(createSalesRole ? { sales_role: createSalesRole } : {}),
        approved: createActive,
        is_active: createActive,
      });
      const username = createUsername.trim();
      setAddingUser(false);
      setSuccess(`Created ${username}.`);
      await loadUsers();
    } catch (err: any) {
      setCreateError(err.message || 'User creation failed');
    } finally {
      setActionLoading(null);
    }
  };

  const filteredAllUsers = allUsers.filter(u => {
    const matchesSearch = u.username.toLowerCase().includes(searchTerm.toLowerCase()) ||
      (u.email || '').toLowerCase().includes(searchTerm.toLowerCase()) ||
      (u.display_name && u.display_name.toLowerCase().includes(searchTerm.toLowerCase()));
    const matchesStatus = statusFilter === 'all' ||
      (statusFilter === 'active' && u.is_active === 1) ||
      (statusFilter === 'inactive' && u.is_active === 0) ||
      (statusFilter === 'approved' && u.approved === 1) ||
      (statusFilter === 'pending' && u.approved === 0);
    const matchesRole = roleFilter === 'all' || effRole(u) === roleFilter;
    return matchesSearch && matchesStatus && matchesRole;
  });

  const pendingFiltered = pendingUsers.filter(u => {
    const matchesSearch = u.username.toLowerCase().includes(searchTerm.toLowerCase()) ||
      (u.email || '').toLowerCase().includes(searchTerm.toLowerCase()) ||
      (u.display_name && u.display_name.toLowerCase().includes(searchTerm.toLowerCase()));
    return matchesSearch;
  });

  const tabButtonStyle = (active: boolean): React.CSSProperties => ({
    padding: '10px 20px',
    background: active ? 'var(--brand-500)' : 'var(--neutral-100)',
    color: active ? 'var(--neutral-0)' : 'var(--neutral-500)',
    border: 'none',
    borderRadius: 'var(--radius)',
    cursor: 'pointer',
    fontSize: '0.9rem',
    fontWeight: 600,
  });


  const modalOverlayStyle: React.CSSProperties = {
    position: 'fixed',
    inset: 0,
    background: 'rgba(0,0,0,0.45)',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    zIndex: 1000,
  };

  const modalInputStyle: React.CSSProperties = {
    width: '100%',
    padding: '8px 10px',
    border: '1px solid var(--divider)',
    borderRadius: 'var(--radius)',
    fontSize: '0.9rem',
    boxSizing: 'border-box',
    background: 'var(--neutral-0)', color: 'var(--ink)',
    marginBottom: '12px',
  };

  return (
    <div style={{ padding: '24px', maxWidth: '1400px', margin: '0 auto' }}>
      <div style={{ marginBottom: '24px' }}>
        <h1 style={{ margin: '0 0 4px 0', fontSize: '1.8rem', color: 'var(--ink)' }}><SectionIcon name="🛡️" /> Admin Dashboard</h1>
        <p style={{ margin: 0, color: 'var(--neutral-500)', fontSize: '0.95rem' }}>Manage users, roles, and account status</p>
      </div>

      {/* View Tabs — drive the parent view (?view= param is the single
          source of truth), so sidebar nav, in-page tabs, refresh, and
          back/forward all agree on the active tab. */}
      <div style={{ display: 'flex', gap: '8px', marginBottom: '24px' }}>
        <button role="button" aria-label="Switch to Pending Approvals tab"
          onClick={() => onNavigate?.('admin-pending')}
          style={tabButtonStyle(activeView === 'pending')}
        >
          Pending Approvals ({pendingUsers.length})
        </button>
        <button role="button" aria-label="Switch to All Users tab"
          onClick={() => onNavigate?.('admin-users')}
          style={tabButtonStyle(activeView === 'all-users')}
        >
          All Users ({allUsers.length})
        </button>
      </div>

      {loading ? (
        <div role="status" aria-live="polite" style={{ padding: '40px', textAlign: 'center', color: 'var(--neutral-500)' }}>Loading users…</div>
      ) : error ? (
        <div role="alert" aria-live="assertive" style={{ padding: '16px', background: 'var(--status-negative-soft)', borderLeft: '4px solid var(--status-negative)', marginBottom: '16px' }}>
          <span aria-hidden="true">⚠️ </span><span style={{ color: 'var(--status-negative)', fontWeight: 500 }}>{error}</span>
          <button role="button" aria-label="Retry loading users" onClick={loadUsers} style={{ marginLeft: '16px', background: 'var(--neutral-0)', border: '1px solid var(--status-negative)', borderRadius: 'var(--radius-sm)', color: 'var(--status-negative)', cursor: 'pointer' }}>Retry</button>
        </div>
      ) : null}
      {success && (
        <div role="status" aria-live="polite" style={{ padding: '10px 14px', background: 'var(--status-positive-soft)', color: 'var(--status-positive)', borderLeft: '4px solid var(--status-positive)', marginBottom: '16px', fontWeight: 500 }}>
          {success}
        </div>
      )}

      {/* Pending Approvals View */}
      {activeView === 'pending' && (
        <div style={{ background: 'var(--neutral-0)', borderRadius: 'var(--radius)', border: '1px solid var(--divider)', overflow: 'hidden' }}>
          <div style={{ padding: '20px 24px', borderBottom: '1px solid var(--divider)' }}>
            <h3 style={{ margin: 0, fontSize: '1.1rem', color: 'var(--neutral-700)' }}>
              Pending User Approvals
            </h3>
          </div>
          {pendingFiltered.length === 0 ? (
            <div style={{ padding: '40px', textAlign: 'center', color: 'var(--neutral-500)' }}>
              <p style={{ margin: 0, fontSize: '1rem' }}>No pending users</p>
              <p style={{ margin: '8px 0 0 0', fontSize: '0.85rem' }}>All registrations have been processed</p>
            </div>
          ) : (
            <div style={{ overflowX: 'auto' }}>
            <table style={{ width: '100%', minWidth: '1130px', tableLayout: 'fixed', borderCollapse: 'collapse' }}>
              <thead>
                <tr style={{ borderBottom: '2px solid var(--divider)' }}>
                  {['Username', 'Display Name', 'Email', 'Department', 'Sales Role', 'Registered', 'Actions'].map(h => (
                    <th key={h} data-ui={h === 'Username' ? 'sticky-user-cell' : h === 'Actions' ? 'sticky-actions-cell' : undefined} style={{ padding: '12px 12px', textAlign: 'left', fontSize: '0.85rem', fontWeight: 600, color: 'var(--neutral-500)', whiteSpace: 'nowrap', width: PENDING_COLUMN_WIDTHS[h], position: h === 'Username' || h === 'Actions' ? 'sticky' : undefined, left: h === 'Username' ? 0 : undefined, right: h === 'Actions' ? 0 : undefined, zIndex: h === 'Username' || h === 'Actions' ? 2 : undefined, background: 'var(--neutral-0)' }}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {pendingFiltered.map(user => {
                  const inlineEditing = editingUser?.id === user.id;
                  const inlineInputStyle: React.CSSProperties = {
                    width: '100%', minWidth: '110px', padding: '6px 8px',
                    border: '1px solid var(--divider)', borderRadius: 'var(--radius-sm)',
                    fontSize: '0.82rem', boxSizing: 'border-box',
                  };
                  return (
                    <tr key={user.id} style={{ borderBottom: '1px solid var(--neutral-100)' }}>
                      <td title={user.username} data-ui="sticky-user-cell" style={{ padding: '12px 12px', fontWeight: 500, color: 'var(--ink)', maxWidth: '190px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', position: 'sticky', left: 0, zIndex: 1, background: 'var(--neutral-0)' }}>{user.username}</td>
                      <td title={user.display_name || undefined} style={{ padding: '12px 12px', color: 'var(--neutral-500)', maxWidth: '180px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                        {inlineEditing ? <input aria-label={`Display name for ${user.username}`} value={editDisplayName} onChange={e => setEditDisplayName(e.target.value)} style={inlineInputStyle} /> : (user.display_name || '—')}
                      </td>
                      <td title={user.email || undefined} style={{ padding: '12px 12px', color: 'var(--neutral-500)', maxWidth: '180px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                        {inlineEditing ? <input type="email" aria-label={`Email for ${user.username}`} value={editEmail} onChange={e => setEditEmail(e.target.value)} style={inlineInputStyle} /> : (user.email || '— (not set yet)')}
                      </td>
                      <td style={{ padding: '12px 12px', color: 'var(--neutral-500)' }}>
                        {inlineEditing ? (
                          <select aria-label={`Department for ${user.username}`} value={editDepartment} onChange={e => setEditDepartment(e.target.value)} style={inlineInputStyle}>
                            <option value="">—</option>
                            <option value="Sales">Sales</option>
                            <option value="PS">PS</option>
                            <option value="MS">MS</option>
                            <option value="Global Administrator">Global Administrator</option>
                          </select>
                        ) : (user.department || '—')}
                      </td>
                      <td style={{ padding: '12px 12px', color: 'var(--neutral-500)' }}>
                        {inlineEditing ? (
                          <select aria-label={`Sales role for ${user.username}`} value={editSalesRole} onChange={e => setEditSalesRole(e.target.value)} style={inlineInputStyle}>
                            <option value="">—</option>
                            <option value="rep">Rep</option>
                            <option value="inside_sales">Inside Sales</option>
                            <option value="sales_manager">Sales Manager</option>
                            <option value="sales_ops">Sales Ops</option>
                            <option value="sales_admin">Sales Admin</option>
                            <option value="auditor">Auditor</option>
                          </select>
                        ) : (user.sales_role || '—')}
                      </td>
                      <td style={{ padding: '12px 12px', color: 'var(--neutral-500)', fontSize: '0.85rem' }}>
                        {new Date(user.created_at).toLocaleDateString()}
                      </td>
                      <td data-ui="sticky-actions-cell" style={{ padding: '12px 12px', whiteSpace: 'nowrap', position: 'sticky', right: 0, zIndex: 1, background: 'var(--neutral-0)' }}>
                        {inlineEditing ? (
                          <div style={{ display: 'flex', gap: '6px', alignItems: 'center' }}>
                            <ActionButton variant="primary" density="compact" busy={actionLoading === `edit-${user.id}`} aria-label={`Save user ${user.username}`} onClick={saveEdit}>Save</ActionButton>
                            <ActionButton variant="quiet" density="compact" aria-label={`Cancel editing ${user.username}`} onClick={() => setEditingUser(null)}>Cancel</ActionButton>
                          </div>
                        ) : (
                          <div style={{ display: 'flex', gap: '6px', alignItems: 'center' }}>
                            <ActionButton variant="secondary" density="compact" aria-label={`Edit user ${user.username}`} onClick={() => openEdit(user)}>Edit</ActionButton>
                            <ActionButton variant="primary" density="compact" busy={actionLoading === user.username} aria-label={`Approve user ${user.username}`} onClick={() => handleApprove(user.username)}>Approve</ActionButton>
                          </div>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
            </div>
          )}
        </div>
      )}

      {/* All Users View */}
      {activeView === 'all-users' && (
        <div>
          {/* Filters */}
          <div style={{ background: 'var(--neutral-0)', borderRadius: 'var(--radius)', boxShadow: 'var(--shadow-card)', padding: '16px 24px', marginBottom: '16px', display: 'flex', gap: '12px', alignItems: 'center', flexWrap: 'wrap' }}>
            <input aria-label="Search users..."
              placeholder="Search users..."
              value={searchTerm}
              onChange={e => setSearchTerm(e.target.value)}
              style={{ padding: '8px 12px', border: '1px solid var(--divider)', borderRadius: 'var(--radius)', fontSize: '0.9rem', background: 'var(--neutral-0)', color: 'var(--ink)', flex: 1, minWidth: '160px' }}
            />
            <select aria-label="Filter by status"
              value={statusFilter}
              onChange={e => setStatusFilter(e.target.value)}
              style={{ padding: '8px 12px', border: '1px solid var(--divider)', borderRadius: 'var(--radius)', fontSize: '0.9rem', background: 'var(--neutral-0)', color: 'var(--ink)' }}
            >
              <option value="all">All Status</option>
              <option value="active">Active</option>
              <option value="inactive">Inactive</option>
              <option value="approved">Approved</option>
              <option value="pending">Pending</option>
            </select>
            <select aria-label="Filter by role"
              value={roleFilter}
              onChange={e => setRoleFilter(e.target.value)}
              style={{ padding: '8px 12px', border: '1px solid var(--divider)', borderRadius: 'var(--radius)', fontSize: '0.9rem', background: 'var(--neutral-0)', color: 'var(--ink)' }}
            >
              <option value="all">All Roles</option>
              <option value="admin">Admin</option>
              <option value="user">User</option>
              <option value="auditor">Auditor</option>
              <option value="ps_admin">PS Admin</option>
            </select>
            {(searchTerm || statusFilter !== 'all' || roleFilter !== 'all') && (
              <ActionButton variant="quiet" role="button" aria-label="Clear filters"
                onClick={() => { setSearchTerm(''); setStatusFilter('all'); setRoleFilter('all'); }}
              >
                Clear
              </ActionButton>
            )}
            <ActionButton variant="primary" role="button" aria-label="Add user" onClick={openCreate}>
              + Add User
            </ActionButton>
          </div>

          {/* User Table */}
          <div style={{ background: 'var(--neutral-0)', borderRadius: 'var(--radius)', border: '1px solid var(--divider)', overflow: 'hidden' }}>
            {filteredAllUsers.length === 0 ? (
              <div style={{ padding: '40px', textAlign: 'center', color: 'var(--neutral-500)' }}>
                <p style={{ margin: 0, fontSize: '1rem' }}>No users found</p>
              </div>
            ) : (
              <div style={{ overflowX: 'auto' }}>
                <table style={{ width: '100%', minWidth: '900px', tableLayout: 'fixed', borderCollapse: 'collapse' }}>
                  <thead>
                    <tr style={{ borderBottom: '2px solid var(--divider)' }}>
                      {['User', 'Email', 'Registered', 'Department', 'Access', 'Status', 'Actions'].map(h => (
                        <th key={h} data-ui={h === 'User' ? 'sticky-user-cell' : h === 'Actions' ? 'sticky-actions-cell' : undefined} style={{ padding: '12px 12px', textAlign: 'left', fontSize: '0.85rem', fontWeight: 600, color: 'var(--neutral-500)', whiteSpace: 'nowrap', width: ALL_USERS_COLUMN_WIDTHS[h], position: h === 'User' || h === 'Actions' ? 'sticky' : undefined, left: h === 'User' ? 0 : undefined, right: h === 'Actions' ? 0 : undefined, zIndex: h === 'User' || h === 'Actions' ? 2 : undefined, background: 'var(--neutral-0)' }}>{h}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {filteredAllUsers.map(user => {
                      const self = isSelf(user);
                      const badge = roleBadge(effRole(user));
                      const busy = actionLoading !== null && actionLoading.endsWith(`-${user.id}`);
                      return (
                        <tr key={user.id} style={{ borderBottom: '1px solid var(--neutral-100)', background: self ? 'var(--brand-50)' : 'transparent' }}>
                          <td title={user.display_name ? `${user.username} — ${user.display_name}` : user.username} data-ui="sticky-user-cell" style={{ padding: '12px 12px', fontWeight: 500, color: 'var(--ink)', overflow: 'hidden', position: 'sticky', left: 0, zIndex: 1, background: self ? 'var(--brand-50)' : 'var(--neutral-0)' }}>
                            <span style={{ display: 'flex', maxWidth: '100%', alignItems: 'center', gap: '6px' }}><span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{user.username}</span>{self && <span style={{ fontSize: '0.7rem', color: 'var(--brand-700)', fontWeight: 700, flexShrink: 0 }}>YOU</span>}</span>
                            <span style={{ display: 'block', fontSize: '0.8rem', fontWeight: 400, color: 'var(--neutral-500)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{user.display_name || 'No display name'}</span>
                          </td>
                          <td title={user.email || undefined} style={{ padding: '12px 12px', color: 'var(--neutral-500)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{user.email || 'Not set'}</td>
                          <td style={{ padding: '12px 12px', color: 'var(--neutral-500)', fontSize: '0.85rem', whiteSpace: 'nowrap' }}>
                            {new Date(user.created_at).toLocaleDateString()}
                          </td>
                          <td title={user.department || undefined} style={{ padding: '12px 12px', color: 'var(--neutral-500)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{user.department || '—'}</td>
                          <td style={{ padding: '12px 12px' }}>
                            <span style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-start', gap: '4px' }}>
                              <span title="Role" style={{ padding: '2px 8px', borderRadius: 'var(--radius)', fontSize: '0.75rem', fontWeight: 600, background: badge.bg, color: badge.color }}>{badge.label}</span>
                              <span title="Sign-in provider" style={{ padding: '2px 8px', borderRadius: 'var(--radius)', fontSize: '0.75rem', fontWeight: 600, background: user.auth_provider === 'ldap' ? 'var(--brand-50)' : 'var(--neutral-100)', color: user.auth_provider === 'ldap' ? 'var(--brand-700)' : 'var(--neutral-700)' }}>{user.auth_provider === 'ldap' ? 'Directory' : 'Local'}</span>
                            </span>
                          </td>
                          <td style={{ padding: '12px 12px' }}>
                            <span style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-start', gap: '4px' }}>
                              <span style={{ padding: '2px 8px', borderRadius: 'var(--radius)', fontSize: '0.75rem', fontWeight: 600, background: user.is_active === 1 ? 'var(--status-positive-soft)' : 'var(--status-negative-soft)', color: user.is_active === 1 ? 'var(--status-positive)' : 'var(--status-negative)' }}>{user.is_active === 1 ? 'Active' : 'Inactive'}</span>
                              <span style={{ padding: '2px 8px', borderRadius: 'var(--radius)', fontSize: '0.75rem', fontWeight: 600, background: user.approved === 1 ? 'var(--brand-100)' : 'var(--status-warning-soft)', color: user.approved === 1 ? 'var(--brand-700)' : 'var(--status-warning)' }}>{user.approved === 1 ? 'Approved' : 'Pending'}</span>
                            </span>
                          </td>
                          <td data-ui="sticky-actions-cell" style={{ padding: '12px 12px', whiteSpace: 'nowrap', position: 'sticky', right: 0, zIndex: 1, background: self ? 'var(--brand-50)' : 'var(--neutral-0)' }}>
                            {/* 2x2 grid: the four inline actions made this
                                column ~390px wide, so the 9-column table
                                exceeded the card on laptop-sized viewports
                                and the last button (Delete) rendered
                                off-screen behind a horizontal scroll.
                                Stacked 2x2, every action stays fully
                                visible at any width (the wrapper's
                                overflowX scroll remains the narrow-screen
                                fallback). */}
                            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, max-content)', gap: '6px' }}>
                              <ActionButton variant="secondary" density="compact" aria-label={`Edit user ${user.username}`} onClick={() => openEdit(user)}>Edit</ActionButton>
                              <ActionButton variant="secondary" density="compact" aria-label={`Reset password for ${user.username}`}
                                onClick={() => openReset(user)}
                                disabled={user.auth_provider === 'ldap'}
                                title={user.auth_provider === 'ldap' ? 'Managed by the corporate directory' : undefined}>Reset PW</ActionButton>
                              {!self && (
                                <>
                                  <ActionButton variant="secondary" density="compact" data-tone={user.is_active === 1 ? 'danger' : undefined}
                                    aria-label={`${user.is_active === 1 ? 'Deactivate' : 'Activate'} ${user.username}`}
                                    onClick={() => handleSetActive(user, user.is_active !== 1)} disabled={busy}>
                                    {user.is_active === 1 ? 'Deactivate' : 'Activate'}
                                  </ActionButton>
                                  <ActionButton variant="danger" density="compact" aria-label={`Delete user ${user.username}`} onClick={() => handleDelete(user)} disabled={busy}>Delete</ActionButton>
                                </>
                              )}
                            </div>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </div>
      )}

      {/* Edit User Modal (portaled to <body> so it stays viewport-anchored
          under the dark-theme filter, which makes #root a containing block) */}
      {editingUser && activeView === 'all-users' && createPortal(
        <div data-ui="admin-dialog" ref={dialogRef} tabIndex={-1} style={modalOverlayStyle} role="dialog" aria-modal="true" aria-label={`Edit user ${editingUser.username}`}>
          <div style={{ background: 'var(--neutral-0)', borderRadius: 'var(--radius)', padding: '24px', width: '420px', maxWidth: '90vw', maxHeight: 'calc(100dvh - 32px)', overflowY: 'auto', boxShadow: 'var(--shadow-raised)' }}>
            <h3 style={{ margin: '0 0 16px 0', fontSize: '1.1rem', color: 'var(--ink)' }}>Edit {editingUser.username}</h3>
            <label style={{ fontSize: '0.85rem', fontWeight: 600, color: 'var(--neutral-700)', display: 'block', marginBottom: '4px' }} htmlFor="edit-display-name">Display Name</label>
            <input id="edit-display-name" aria-label="Display name"
              value={editDisplayName}
              onChange={e => setEditDisplayName(e.target.value)}
              style={modalInputStyle}
            />
            <label style={{ fontSize: '0.85rem', fontWeight: 600, color: 'var(--neutral-700)', display: 'block', marginBottom: '4px' }} htmlFor="edit-email">Email</label>
            <input id="edit-email" type="email" aria-label="Email"
              value={editEmail}
              onChange={e => setEditEmail(e.target.value)}
              style={modalInputStyle}
            />
            <label style={{ fontSize: '0.85rem', fontWeight: 600, color: 'var(--neutral-700)', display: 'block', marginBottom: '4px' }} htmlFor="edit-department">Department</label>
            <select id="edit-department" aria-label="Department"
              value={editDepartment}
              onChange={e => setEditDepartment(e.target.value)}
              style={modalInputStyle}
            >
              <option value="">—</option>
              <option value="Sales">Sales</option>
              <option value="PS">PS</option>
              <option value="MS">MS</option>
              <option value="Global Administrator">Global Administrator</option>
            </select>
            <label style={{ fontSize: '0.85rem', fontWeight: 600, color: 'var(--neutral-700)', display: 'block', marginBottom: '4px' }} htmlFor="edit-role">Role</label>
            <select id="edit-role" aria-label="Role"
              value={editRole}
              onChange={e => setEditRole(e.target.value)}
              disabled={isSelf(editingUser)}
              style={{ ...modalInputStyle, opacity: isSelf(editingUser) ? 0.6 : 1 }}
            >
              <option value="admin">Admin (global privileges)</option>
              <option value="user">User (assigned customers)</option>
              <option value="auditor">Auditor (read-only)</option>
              <option value="ps_admin">PS Admin</option>
            </select>
            {isSelf(editingUser) && (
              <p style={{ fontSize: '0.8rem', color: 'var(--neutral-500)', margin: '0 0 12px 0' }}>You cannot change your own role.</p>
            )}
            <label style={{ fontSize: '0.85rem', fontWeight: 600, color: 'var(--neutral-700)', display: 'block', marginBottom: '4px' }} htmlFor="edit-sales-role">Sales Role</label>
            <select id="edit-sales-role" aria-label="Sales role"
              value={editSalesRole}
              onChange={e => setEditSalesRole(e.target.value)}
              style={modalInputStyle}
            >
              <option value="">—</option>
              <option value="rep">Rep</option>
              <option value="inside_sales">Inside Sales</option>
              <option value="sales_manager">Sales Manager</option>
              <option value="sales_ops">Sales Ops</option>
              <option value="sales_admin">Sales Admin</option>
              <option value="auditor">Auditor</option>
            </select>
            <div style={{ display: 'flex', gap: '8px', justifyContent: 'flex-end' }}>
              <ActionButton variant="quiet" role="button" aria-label="Cancel edit"
                disabled={actionLoading !== null} onClick={() => setEditingUser(null)}
              >
                Cancel
              </ActionButton>
              <ActionButton variant="primary" busy={actionLoading === `edit-${editingUser.id}`} role="button" aria-label="Save changes"
                onClick={saveEdit}
                disabled={actionLoading === `edit-${editingUser.id}`}
              >
                Save Changes
              </ActionButton>
            </div>
          </div>
        </div>,
        document.body
      )}

      {addingUser && activeView === 'all-users' && createPortal(
        <div data-ui="admin-dialog" ref={dialogRef} tabIndex={-1} style={modalOverlayStyle} role="dialog" aria-modal="true" aria-label="Add user">
          <div style={{ background: 'var(--neutral-0)', borderRadius: 'var(--radius)', padding: '24px', width: '460px', maxWidth: '90vw', maxHeight: '90vh', overflowY: 'auto', boxShadow: 'var(--shadow-raised)' }}>
            <h3 style={{ margin: '0 0 16px', fontSize: '1.1rem', color: 'var(--ink)' }}><SectionIcon name="👥" /> Add User</h3>
            {createError && <div role="alert" style={{ padding: '10px 12px', marginBottom: '12px', color: 'var(--status-negative)', background: 'var(--status-negative-soft)', borderRadius: 'var(--radius)' }}>{createError}</div>}
            <label htmlFor="create-username" style={{ fontSize: '0.85rem', fontWeight: 600, color: 'var(--neutral-700)' }}>Username</label>
            <input id="create-username" aria-label="New user username" value={createUsername} onChange={e => setCreateUsername(e.target.value)} style={modalInputStyle} />
            <label htmlFor="create-display-name" style={{ fontSize: '0.85rem', fontWeight: 600, color: 'var(--neutral-700)' }}>Display Name</label>
            <input id="create-display-name" aria-label="New user display name" value={createDisplayName} onChange={e => setCreateDisplayName(e.target.value)} style={modalInputStyle} />
            <label htmlFor="create-email" style={{ fontSize: '0.85rem', fontWeight: 600, color: 'var(--neutral-700)' }}>Email (optional)</label>
            <input id="create-email" type="email" aria-label="New user email" value={createEmail} onChange={e => setCreateEmail(e.target.value)} style={modalInputStyle} />
            <label htmlFor="create-password" style={{ fontSize: '0.85rem', fontWeight: 600, color: 'var(--neutral-700)' }}>Password</label>
            <input id="create-password" type="password" aria-label="New user password" value={createPassword} onChange={e => setCreatePassword(e.target.value)} style={modalInputStyle} />
            <label htmlFor="create-department" style={{ fontSize: '0.85rem', fontWeight: 600, color: 'var(--neutral-700)' }}>Department</label>
            <select id="create-department" aria-label="New user department" value={createDepartment} onChange={e => setCreateDepartment(e.target.value)} style={modalInputStyle}>
              <option value="">—</option><option value="Sales">Sales</option><option value="PS">PS</option><option value="MS">MS</option><option value="Global Administrator">Global Administrator</option>
            </select>
            <label htmlFor="create-role" style={{ fontSize: '0.85rem', fontWeight: 600, color: 'var(--neutral-700)' }}>Role</label>
            <select id="create-role" aria-label="New user role" value={createRole} onChange={e => setCreateRole(e.target.value)} style={modalInputStyle}>
              <option value="user">User</option><option value="admin">Admin</option><option value="auditor">Auditor</option><option value="ps_admin">PS Admin</option>
            </select>
            <label htmlFor="create-sales-role" style={{ fontSize: '0.85rem', fontWeight: 600, color: 'var(--neutral-700)' }}>Sales Role</label>
            <select id="create-sales-role" aria-label="New user sales role" value={createSalesRole} onChange={e => setCreateSalesRole(e.target.value)} style={modalInputStyle}>
              <option value="">—</option><option value="rep">Rep</option><option value="inside_sales">Inside Sales</option><option value="sales_manager">Sales Manager</option><option value="sales_ops">Sales Ops</option><option value="sales_admin">Sales Admin</option><option value="auditor">Auditor</option>
            </select>
            <label style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '18px', color: 'var(--neutral-700)', fontSize: '0.85rem' }}>
              <input type="checkbox" aria-label="Create active" checked={createActive} onChange={e => setCreateActive(e.target.checked)} />
              Create active
            </label>
            <div style={{ display: 'flex', gap: '8px', justifyContent: 'flex-end' }}>
              <ActionButton variant="quiet" aria-label="Cancel adding user" disabled={actionLoading !== null} onClick={() => setAddingUser(false)}>Cancel</ActionButton>
              <ActionButton variant="primary" busy={actionLoading === 'create-user'} aria-label="Create user" onClick={saveCreate} disabled={!createUsername.trim() || createPassword.length < 12 || actionLoading === 'create-user'}>Create User</ActionButton>
            </div>
          </div>
        </div>,
        document.body,
      )}

      {/* Reset Password Modal (portaled to <body>) */}
      {resetUser && createPortal(
        <div data-ui="admin-dialog" ref={dialogRef} tabIndex={-1} style={modalOverlayStyle} role="dialog" aria-modal="true" aria-label={`Reset password for ${resetUser.username}`}>
          <div style={{ background: 'var(--neutral-0)', borderRadius: 'var(--radius)', padding: '24px', width: '420px', maxWidth: '90vw', maxHeight: 'calc(100dvh - 32px)', overflowY: 'auto', boxShadow: 'var(--shadow-raised)' }}>
            <h3 style={{ margin: '0 0 8px 0', fontSize: '1.1rem', color: 'var(--ink)' }}>Reset Password — {resetUser.username}</h3>
            <p style={{ fontSize: '0.85rem', color: 'var(--neutral-500)', margin: '0 0 16px 0' }}>
              Set a new password for this account. The password policy is enforced.
            </p>
            <label style={{ fontSize: '0.85rem', fontWeight: 600, color: 'var(--neutral-700)', display: 'block', marginBottom: '4px' }} htmlFor="new-password">New Password</label>
            <input id="new-password" type="password" aria-label="New password"
              value={newPassword}
              onChange={e => setNewPassword(e.target.value)}
              style={modalInputStyle}
            />
            <div style={{ display: 'flex', gap: '8px', justifyContent: 'flex-end' }}>
              <ActionButton variant="quiet" role="button" aria-label="Cancel password reset"
                disabled={actionLoading !== null} onClick={() => setResetUser(null)}
              >
                Cancel
              </ActionButton>
              <ActionButton variant="primary" busy={actionLoading === `reset-${resetUser.id}`} role="button" aria-label="Confirm password reset"
                onClick={saveReset}
                disabled={!newPassword || actionLoading === `reset-${resetUser.id}`}
              >
                Reset Password
              </ActionButton>
            </div>
          </div>
        </div>,
        document.body
      )}
    </div>
  );
}
export default AdminPage;
