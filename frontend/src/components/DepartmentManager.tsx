import { useState, useEffect } from 'react';
import { api } from '../lib/api';
import { RowActions } from './workspacePrimitives';

interface DepartmentManagerProps {
  customerName: string;
  userRole: string;
  departments: Array<{ id: number; name: string; use_case_count: number }>;
  onDepartmentChange: () => void;
}

export function DepartmentManager({
  customerName,
  userRole,
  departments,
  onDepartmentChange,
}: DepartmentManagerProps) {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const [newDeptName, setNewDeptName] = useState('');
  const [renamingDept, setRenamingDept] = useState<{ id: number; name: string } | null>(null);
  const [newDeptNameValue, setNewDeptNameValue] = useState('');
  const [deletingDept, setDeletingDept] = useState<{ id: number; name: string } | null>(null);

  const canManage = userRole !== 'auditor' && userRole !== 'none';

  useEffect(() => {
    // Reset success/error on department changes
    setSuccess(null);
    setError(null);
  }, [departments]);

  const handleCreate = async () => {
    if (!newDeptName.trim()) return;
    try {
      setLoading(true);
      await api.createDepartment({ name: newDeptName.trim(), customer_name: customerName });
      setNewDeptName('');
      setSuccess(`Department "${newDeptName.trim()}" created`);
      onDepartmentChange();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to create department');
    } finally {
      setLoading(false);
    }
  };

  const handleRename = async (dept: { id: number; name: string }) => {
    if (!newDeptNameValue.trim()) return;
    try {
      setLoading(true);
      await api.updateDepartment(dept.id, { name: newDeptNameValue.trim() });
      setSuccess(`Department "${dept.name}" renamed to "${newDeptNameValue.trim()}"`);
      setRenamingDept(null);
      setNewDeptNameValue('');
      onDepartmentChange();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to rename department');
    } finally {
      setLoading(false);
    }
  };

  const handleDelete = async (dept: { id: number; name: string }) => {
    if (!confirm(`Delete department "${dept.name}"? Use cases in this department will be unlinked.`)) return;
    try {
      setLoading(true);
      await api.deleteDepartment(dept.id);
      setSuccess(`Department "${dept.name}" deleted`);
      setDeletingDept(null);
      onDepartmentChange();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to delete department');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div>
      <h2 style={{ margin: '0 0 16px 0', fontSize: '1.3rem', color: 'var(--ink)' }}>
        Departments for {customerName}
      </h2>

      {/* Error/Success */}
      {error && (
        <div style={{ padding: '12px', background: 'var(--status-negative-soft)', borderLeft: '4px solid var(--status-negative)', borderRadius: 'var(--radius-sm)', color: 'var(--status-negative)', marginBottom: '16px' }}>
          ⚠️ {error}
        </div>
      )}
      {success && (
        <div style={{ padding: '12px', background: 'var(--status-positive-soft)', borderLeft: '4px solid var(--status-positive)', borderRadius: 'var(--radius-sm)', color: 'var(--status-positive)', marginBottom: '16px' }}>
          ✅ {success}
          <button onClick={() => setSuccess(null)} style={{ marginLeft: '12px', background: 'none', border: 'none', color: 'var(--status-positive)', cursor: 'pointer', fontWeight: 600 }}>✕</button>
        </div>
      )}

      {/* Create Department */}
      <div style={{ background: 'var(--neutral-0)', borderRadius: 'var(--radius)', padding: '20px', boxShadow: 'var(--shadow-card)', marginBottom: '24px' }}>
        <h3 style={{ margin: '0 0 12px 0', fontSize: '1rem', color: 'var(--neutral-700)' }}>Add New Department</h3>
        <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap' }}>
          <input
            placeholder="Department name"
            value={newDeptName}
            onChange={e => setNewDeptName(e.target.value)}
            style={{ flex: 1, minWidth: '200px', padding: '8px 10px', border: '1px solid var(--divider)', borderRadius: 'var(--radius)', fontSize: '0.9rem' }}
            disabled={!canManage || loading}
          />
          <button
            onClick={handleCreate}
            disabled={!newDeptName.trim() || !canManage || loading}
            style={{
              padding: '8px 16px',
              background: newDeptName.trim() && canManage && !loading ? 'var(--brand-500)' : 'var(--neutral-400)',
              color: 'var(--neutral-0)',
              border: 'none',
              borderRadius: 'var(--radius)',
              cursor: newDeptName.trim() && canManage && !loading ? 'pointer' : 'not-allowed',
              fontSize: '0.85rem',
              fontWeight: 600,
            }}
          >
            {loading ? 'Creating...' : 'Add Department'}
          </button>
        </div>
      </div>

      {/* Department List */}
      <div style={{ display: 'grid', gap: '16px' }}>
        {departments.length === 0 ? (
          <div style={{ background: 'var(--neutral-0)', borderRadius: 'var(--radius)', padding: '40px', textAlign: 'center', boxShadow: 'var(--shadow-card)' }}>
            <p style={{ color: 'var(--neutral-500)', margin: 0 }}>No departments yet. Add one above to get started.</p>
          </div>
        ) : (
          departments.map((dept: { id: number; name: string; use_case_count: number }) => (
            <div key={dept.id} style={{ background: 'var(--neutral-0)', borderRadius: 'var(--radius)', padding: '16px 20px', boxShadow: 'var(--shadow-card)' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '12px' }}>
                <div>
                  {renamingDept?.id === dept.id ? (
                    <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
                      <input
                        value={newDeptNameValue}
                        onChange={e => setNewDeptNameValue(e.target.value)}
                        style={{ padding: '4px 8px', border: '1px solid var(--divider)', borderRadius: 'var(--radius-sm)', fontSize: '0.9rem', minWidth: '150px' }}
                        autoFocus
                        onKeyDown={e => { if (e.key === 'Enter') handleRename({ id: dept.id, name: dept.name }); if (e.key === 'Escape') setRenamingDept(null); }}
                      />
                      <button onClick={() => handleRename({ id: dept.id, name: dept.name })} style={{ padding: '4px 8px', background: 'var(--status-positive)', color: 'var(--neutral-0)', border: 'none', borderRadius: 'var(--radius-sm)', cursor: 'pointer', fontSize: '0.8rem' }}>Save</button>
                      <button onClick={() => { setRenamingDept(null); setNewDeptNameValue(''); }} style={{ padding: '4px 8px', background: 'var(--neutral-400)', color: 'var(--neutral-0)', border: 'none', borderRadius: 'var(--radius-sm)', cursor: 'pointer', fontSize: '0.8rem' }}>Cancel</button>
                    </div>
                  ) : (
                    <span style={{ fontWeight: 600, fontSize: '1rem', color: 'var(--ink)' }}>{dept.name}</span>
                  )}
                  <div style={{ fontSize: '0.8rem', color: 'var(--neutral-500)', marginTop: '2px' }}>{dept.use_case_count} use case{dept.use_case_count !== 1 ? 's' : ''}</div>
                </div>
                <div style={{ display: 'flex', gap: '6px' }}>
                  {canManage && renamingDept?.id !== dept.id && (
                    // CHANGELOG 0.1.0 U7 (directive 42): per-row Rename/Delete move
                    // into a compact overflow menu — the destructive delete
                    // keeps its inline confirmation panel below.
                    <RowActions
                      ariaLabel={`Actions for department ${dept.name}`}
                      items={[
                        {
                          label: 'Rename department',
                          onClick: () => { setRenamingDept({ id: dept.id, name: dept.name }); setNewDeptNameValue(dept.name); },
                          divider: true,
                        },
                        {
                          label: 'Delete department',
                          onClick: () => setDeletingDept({ id: dept.id, name: dept.name }),
                          destructive: true,
                        },
                      ]}
                    />
                  )}
                </div>
              </div>

              {/* Delete confirmation */}
              {deletingDept?.id === dept.id && (
                <div style={{ padding: '12px', background: 'var(--status-negative-soft)', borderRadius: 'var(--radius)', marginBottom: '12px' }}>
                  <p style={{ margin: '0 0 8px', color: 'var(--status-negative)', fontSize: '0.9rem' }}>
                    Are you sure you want to delete "{dept.name}"?
                  </p>
                  <div style={{ display: 'flex', gap: '8px' }}>
                    <button
                      onClick={() => handleDelete({ id: dept.id, name: dept.name })}
                      style={{ padding: '6px 12px', background: 'var(--status-negative)', color: 'var(--neutral-0)', border: 'none', borderRadius: 'var(--radius-sm)', cursor: 'pointer', fontSize: '0.85rem', fontWeight: 600 }}
                    >
                      Confirm Delete
                    </button>
                    <button
                      onClick={() => setDeletingDept(null)}
                      style={{ padding: '6px 12px', background: 'var(--neutral-100)', color: 'var(--neutral-500)', border: '1px solid var(--divider)', borderRadius: 'var(--radius-sm)', cursor: 'pointer', fontSize: '0.85rem' }}
                    >
                      Cancel
                    </button>
                  </div>
                </div>
              )}
            </div>
          ))
        )}
      </div>
    </div>
  );
}

export default DepartmentManager;
