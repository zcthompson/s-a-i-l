/**
 * CustomerTeam.tsx - User management and sharing for a customer
 * 
 * Shows:
 * - Current users with access (with role badges)
 * - "Add User" modal
 * - "Remove User" / "Change Role" buttons
 * - Access check for current view
 */

import React, { useState, useEffect } from 'react';
import { createPortal } from 'react-dom';
import { api } from '../lib/api';
import type { CustomerUser } from '../types/use_case';

interface CustomerTeamProps {
  customerName: string;
  customerId: number;
  userRole: string; // 'owner' | 'member' | 'auditor'
}

const styles: Record<string, React.CSSProperties> = {
  card: {
    background: 'var(--neutral-0)',
    borderRadius: 'var(--radius)',
    boxShadow: 'var(--shadow-sm)',
  },
  header: {
    padding: '1rem',
    borderBottom: '1px solid var(--divider)',
    display: 'flex',
    justifyContent: 'space-between',
    alignItems: 'center',
  },
  error: {
    padding: '1rem',
    background: 'var(--status-negative-soft)',
    borderBottom: '1px solid var(--status-negative-soft)',
    color: 'var(--status-negative)',
  },
  retryButton: {
    color: 'var(--status-negative)',
    textDecoration: 'underline',
    background: 'none',
    border: 'none',
    cursor: 'pointer',
    marginTop: '8px',
    fontSize: '0.875rem',
  },
  table: {
    overflowX: 'auto' as const,
  },
  tableBase: {
    width: '100%',
    borderCollapse: 'collapse' as const,
  },
  tableHead: {
    background: 'var(--neutral-50)',
  },
  th: {
    padding: '12px 16px',
    textAlign: 'left' as const,
    fontSize: '0.75rem',
    fontWeight: 500,
    color: 'var(--neutral-500)',
    textTransform: 'uppercase' as const,
    letterSpacing: '0.05em',
  },
  tbody: {
    background: 'var(--neutral-0)',
    borderTop: '1px solid var(--divider)',
  },
  td: {
    padding: '12px 16px',
    fontSize: '0.875rem',
    borderTop: '1px solid var(--divider)',
  },
  modal: {
    position: 'fixed' as const,
    inset: 0,
    background: 'rgba(0,0,0,0.5)',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    zIndex: 50,
  },
  modalContent: {
    background: 'var(--neutral-0)',
    borderRadius: 'var(--radius)',
    padding: '24px',
    width: '100%',
    maxWidth: '28rem',
  },
  input: {
    width: '100%',
    padding: '0.75rem',
    border: '1px solid var(--neutral-300)',
    borderRadius: 'var(--radius-sm)',
  },
  select: {
    width: '100%',
    padding: '0.75rem',
    border: '1px solid var(--neutral-300)',
    borderRadius: 'var(--radius-sm)',
  },
  addButton: {
    padding: '0.5rem 1rem',
    background: 'var(--brand-500)',
    color: 'var(--neutral-0)',
    borderRadius: 'var(--radius-sm)',
    border: 'none',
    cursor: 'pointer',
    fontSize: '0.875rem',
  },
};

export const CustomerTeam: React.FC<CustomerTeamProps> = ({ customerName, customerId: _customerId, userRole }) => {
  const [users, setUsers] = useState<CustomerUser[]>([]);
  const [loading, setLoading] = useState(true);
  const [showAddModal, setShowAddModal] = useState(false);
  const [newUserId, setNewUserId] = useState('');
  const [newRole, setNewRole] = useState('member');
  const [error, setError] = useState<string | null>(null);

  const isAdmin = userRole === 'owner';

  useEffect(() => {
    loadUsers();
  // eslint-disable-next-line react-hooks/exhaustive-deps -- pre-existing dependency list; change only with UI verification
  }, [customerName]);

  const loadUsers = async () => {
    try {
      setLoading(true);
      setError(null);
      const data = await api.listCustomerUsers(customerName);
      setUsers(data);
    } catch (err: any) {
      setError(err.message || 'Failed to load users');
    } finally {
      setLoading(false);
    }
  };

  const handleAddUser = async () => {
    try {
      setError(null);
      const userId = parseInt(newUserId, 10);
      if (isNaN(userId) || userId <= 0) {
        setError('Invalid user ID');
        return;
      }
      await api.addUserToCustomer(customerName, userId, newRole);
      setShowAddModal(false);
      setNewUserId('');
      setNewRole('member');
      await loadUsers();
    } catch (err: any) {
      setError(err.message || 'Failed to add user');
    }
  };

  const handleRemoveUser = async (user: CustomerUser) => {
    if (!isAdmin) return;
    if (!confirm(`Remove "${user.username}" from "${customerName}"?`)) return;

    try {
      setError(null);
      await api.removeUserFromCustomer(customerName, user.user_id);
      await loadUsers();
    } catch (err: any) {
      setError(err.message || 'Failed to remove user');
    }
  };

  const handleUpdateRole = async (user: CustomerUser, newRole: string) => {
    if (!isAdmin) return;
    try {
      setError(null);
      await api.updateUserRole(customerName, user.user_id, newRole);
      await loadUsers();
    } catch (err: any) {
      setError(err.message || 'Failed to update role');
    }
  };

  if (loading) return (
    <div style={{ textAlign: 'center', padding: '16px', color: 'var(--neutral-500)' }}>Loading team...</div>
  );

  return (
    <div style={styles.card}>
      {/* Header */}
      <div style={styles.header}>
        <div>
          <h3 style={{ fontSize: '1.125rem', fontWeight: 600, color: 'var(--neutral-900)' }}>Team: {customerName}</h3>
          <p style={{ fontSize: '0.875rem', color: 'var(--neutral-500)', marginTop: '4px' }}>
            {users.length} user{users.length !== 1 ? 's' : ''} have access
          </p>
        </div>
        {isAdmin && (
          <button
            role="button"
            aria-label="Add a user to the customer team"
            onClick={() => setShowAddModal(true)}
            style={styles.addButton}
          >
            + Add User
          </button>
        )}
      </div>

      {/* Error */}
      {error && (
        <div style={styles.error}>
          <p style={{ fontSize: '0.875rem' }}>{error}</p>
          <button
            role="button"
            aria-label="Retry loading users"
            onClick={() => loadUsers()}
            style={styles.retryButton}
          >
            Retry
          </button>
        </div>
      )}

      {/* Users Table */}
      <div style={styles.table}>
        <table style={styles.tableBase}>
          <thead style={styles.tableHead}>
            <tr>
              <th style={styles.th}>User</th>
              <th style={styles.th}>Role</th>
              <th style={styles.th}>Granted By</th>
              <th style={styles.th}>Actions</th>
            </tr>
          </thead>
          <tbody style={styles.tbody}>
            {users.map((user) => (
              <tr key={user.id}>
                <td style={styles.td}>
                  <span style={{ fontWeight: 500, color: 'var(--neutral-900)' }}>
                    {user.username || 'Unknown'}
                  </span>
                  <span style={{ display: 'block', fontSize: '0.75rem', color: 'var(--neutral-500)' }}>ID: {user.user_id}</span>
                </td>
                <td style={styles.td}>
                  <RoleBadge role={user.role} />
                </td>
                <td style={{ ...styles.td, color: 'var(--neutral-500)' }}>
                  {user.granted_by ? `User ${user.granted_by}` : '-'}
                </td>
                <td style={styles.td}>
                  {isAdmin ? (
                    <div style={{ display: 'flex', gap: '8px' }}>
                      <RoleSelect
                        value={user.role}
                        onChange={(newRole) => handleUpdateRole(user, newRole)}
                        disabled={user.role === 'owner'}
                      />
                      {user.role !== 'owner' && (
                        <button
                          role="button"
                          aria-label={`Remove ${user.username}`}
                          onClick={() => handleRemoveUser(user)}
                          style={{ color: 'var(--status-negative)', background: 'none', border: 'none', cursor: 'pointer', fontSize: '0.875rem' }}
                        >
                          Remove
                        </button>
                      )}
                    </div>
                  ) : (
                    <span style={{ fontSize: '0.75rem', color: 'var(--neutral-500)' }}>Owner only</span>
                  )}
                </td>
              </tr>
            ))}
            {users.length === 0 && (
              <tr>
                <td colSpan={4} style={{ ...styles.td, textAlign: 'center', color: 'var(--neutral-500)', padding: '24px' }}>
                  No users have access to this customer yet.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      {/* Add User Modal (portaled to <body> so it stays viewport-anchored
          under the dark-theme filter, which makes #root a containing block) */}
      {showAddModal && createPortal(
        <div style={styles.modal}>
          <div style={styles.modalContent}>
            <h3 style={{ fontSize: '1.125rem', fontWeight: 600, color: 'var(--neutral-900)', marginBottom: '16px' }}>Add User to {customerName}</h3>

            <div style={{ marginBottom: '16px' }}>
              <label style={{ display: 'block', fontSize: '0.875rem', fontWeight: 500, color: 'var(--neutral-700)', marginBottom: '4px' }}>
                User ID
              </label>
              <input
                aria-label="Customer Team field"
                type="number"
                value={newUserId}
                onChange={(e) => setNewUserId(e.target.value)}
                style={styles.input}
                placeholder="Enter user ID"
              />
            </div>

            <div style={{ marginBottom: '16px' }}>
              <label style={{ display: 'block', fontSize: '0.875rem', fontWeight: 500, color: 'var(--neutral-700)', marginBottom: '4px' }}>
                Role
              </label>
              <select
                aria-label="Customer Team selection"
                value={newRole}
                onChange={(e) => setNewRole(e.target.value)}
                style={styles.select}
              >
                <option value="owner">Owner</option>
                <option value="member">Member</option>
                <option value="auditor">Auditor (read-only)</option>
              </select>
              <p style={{ fontSize: '0.75rem', color: 'var(--neutral-500)', marginTop: '4px' }}>
                {newRole === 'owner' && 'Full control: add/remove users, manage all use cases'}
                {newRole === 'member' && 'Can view and edit use cases'}
                {newRole === 'auditor' && 'Read-only access to view use cases'}
              </p>
            </div>

            {error && <p style={{ color: 'var(--status-negative)', fontSize: '0.875rem', marginBottom: '12px' }}>{error}</p>}

            <div style={{ display: 'flex', gap: '8px', justifyContent: 'flex-end' }}>
              <button
                role="button"
                aria-label="Cancel adding user"
                onClick={() => setShowAddModal(false)}
                style={{ padding: '0.5rem 1rem', color: 'var(--neutral-700)', border: 'none', background: 'none', cursor: 'pointer' }}
              >
                Cancel
              </button>
              <button
                role="button"
                aria-label="Add user to the team"
                onClick={handleAddUser}
                style={{ ...styles.addButton, borderRadius: 'var(--radius-sm)' }}
              >
                Add User
              </button>
            </div>
          </div>
        </div>,
        document.body
      )}
    </div>
  );
  };

// ── Sub-components ─────────────────────────────────────────────────────

function RoleBadge({ role }: { role: string }) {
  const colorMap: Record<string, React.CSSProperties> = {
    owner: { background: 'var(--brand-50)', color: 'var(--brand-700)', border: '1px solid var(--brand-100)' },
    member: { background: "var(--brand-50)", color: "var(--brand-700)", border: "1px solid var(--brand-100)" },
    auditor: { background: "var(--neutral-100)", color: "var(--neutral-700)", border: "1px solid var(--neutral-300)" },
  };

  return (
    <span style={{
      display: 'inline-flex',
      alignItems: 'center',
      padding: '4px 10px',
      borderRadius: 'var(--radius-pill)',
      fontSize: '0.75rem',
      fontWeight: 500,
      ...colorMap[role] || colorMap.member,
    }}>
      {role.charAt(0).toUpperCase() + role.slice(1)}
    </span>
  );
}

function RoleSelect({ value, onChange, disabled }: {
  value: string;
  onChange: (role: string) => void;
  disabled: boolean;
}) {
  return (
    <select
      aria-label="Customer Team selection"
      value={value}
      onChange={(e) => onChange(e.target.value)}
      disabled={disabled}
      style={{
        fontSize: '0.75rem',
        padding: '4px 8px',
        border: '1px solid var(--neutral-300)',
        borderRadius: 'var(--radius-sm)',
        ...(disabled ? { background: 'var(--neutral-50)', color: 'var(--neutral-500)' } : { background: 'var(--neutral-0)' }),
      }}
    >
      <option value="owner">Owner</option>
      <option value="member">Member</option>
      <option value="auditor">Auditor</option>
    </select>
  );
}
