import { ActionButton } from './ActionButton';
import { SectionIcon } from './SectionIcon';
import { useAccountListState } from '../lib/useAccountListState';
import { SavedViewsMenu } from './SavedViewsMenu';
/**
 * H5 — Tasks panel (Intelligence secondary rail).
 *
 * Honesty rules (contract S0): an undated task has no due (never overdue);
 * overdue / due_soon / needs_reassignment are server-computed flags rendered
 * as given; backend 409 (concurrent edit) and 422 messages render VERBATIM.
 * Assignee choices pair display names with server-authorized usernames.
 * The dashboard supplies section write permissions; backend policy remains
 * authoritative for all mutations and version conflicts.
 */
import { useEffect, useState } from 'react';
import { api, getAuthUsername } from '../lib/api';
import { localInputToUtcIso, renderDue } from '../lib/engagement';
import type { Task } from '../types/engagement';

interface Props {
  customerId: number;
  createRequest?: number;
  allowCreate?: boolean;
  userRole?: string; // 'owner' | 'member' | 'auditor' | 'none'
  /** Deprecated caller compatibility; display-name hints are not assignment identities. */
  assigneeHints?: string[];
  assignees?: { username: string; display_name: string }[];
}

const inputStyle: React.CSSProperties = {
  padding: '8px', border: '1px solid var(--divider)', borderRadius: 'var(--radius)', fontSize: '0.85rem', background: 'var(--neutral-0)',
};

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label style={{ display: 'flex', flexDirection: 'column', gap: '4px', fontSize: '0.8rem', color: 'var(--neutral-600)' }}>
      {label}
      {children}
    </label>
  );
}


const emptyForm = () => ({ title: '', detail: '', assignee: '', due_at: '', due_date: '' });

export function TasksPanel({ customerId, userRole, assigneeHints, assignees = [], createRequest = 0, allowCreate }: Props) {
  const [tasks, setTasks] = useState<Task[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [formOpen, setFormOpen] = useState(false);
  const [form, setForm] = useState(emptyForm());
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [reassignId, setReassignId] = useState<number | null>(null);
  const [reassignTo, setReassignTo] = useState('');
  const [confirmDeleteId, setConfirmDeleteId] = useState<number | null>(null);

  const canEdit = (allowCreate ?? true) && userRole !== 'auditor' && userRole !== 'none';
  void assigneeHints; // Legacy callers may supply hints; never treat a display name as a username.
  const [filters, updateFilters] = useAccountListState(customerId, 'task', { view: 'all' });
  const view = filters.view;
  const setView = (view: string) => updateFilters({ view });
  const [editConflict, setEditConflict] = useState(false);
  const [editingTask, setEditingTask] = useState<Task | null>(null);
  const visibleTasks = tasks.filter(task => view === 'all' || (view === 'open' && ['open', 'in_progress'].includes(task.status)) || (view === 'overdue' && task.overdue) || (view === 'mine' && task.assignee === getAuthUsername()));
  const assigneeOptions = <><option value="">Unassigned</option>{assignees.map(user => <option key={user.username} value={user.username}>{user.display_name} ({user.username})</option>)}</>;

  const load = async (preserveError = false) => {
    setLoading(true);
    if (!preserveError) setError(null);
    try {
      const list = await api.listTasks(customerId);
      setTasks(Array.isArray(list) ? list : []);
    } catch (e: any) {
      setError(e?.message || 'Failed to load tasks');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    setTasks([]);
    setFormOpen(false);
    setReassignId(null);
    setError(null);
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [customerId]);

  const set = <K extends keyof ReturnType<typeof emptyForm>>(k: K, v: string) => setForm((f) => ({ ...f, [k]: v }));

  const submit = async () => {
    if (!form.title.trim()) {
      setSaveError('Title is required.');
      return;
    }
    if (form.due_at && form.due_date) {
      setSaveError('Provide either a due time or a due date, not both.');
      return;
    }
    if (editConflict) return;
    setSaving(true);
    setSaveError(null);
    try {
      const payload = {
        title: form.title.trim(),
        detail: form.detail.trim() || null,
        assignee: form.assignee.trim() || null,
        due_at: form.due_at ? localInputToUtcIso(form.due_at) : null,
        due_date: form.due_date || null,
      };
      if (editingTask) await api.updateTask(editingTask.id, { ...payload, expected_version: editingTask.version });
      else await api.createTask(customerId, payload);
      setEditingTask(null);
      setFormOpen(false);
      setForm(emptyForm());
      await load();
    } catch (e: any) {
      setSaveError(e?.message || 'Failed to save');
      if (e?.status === 409) { setEditConflict(true); await load(true); }
    } finally {
      setSaving(false);
    }
  };

  // Every state change sends the task's loaded version; a 409 message is shown
  // verbatim and the list reloads so the user sees current state.
  const change = async (t: Task, patch: { status?: string; assignee?: string }) => {
    setError(null);
    try {
      await api.updateTask(t.id, { expected_version: t.version, ...patch });
      setReassignId(null);
      setReassignTo('');
      await load();
    } catch (e: any) {
      setError(e?.message || 'Failed to update task');
      if (e?.status === 409) await load(true);
    }
  };

  const doDelete = async (t: Task) => {
    setConfirmDeleteId(null);
    setError(null);
    try {
      await api.deleteTask(t.id, t.version);
      await load();
    } catch (e: any) {
      setError(e?.message || 'Failed to delete task');
      if (e?.status === 409) await load(true);
    }
  };

  useEffect(() => {
    if (createRequest && canEdit) { setEditConflict(false); setEditingTask(null); setForm(emptyForm()); setSaveError(null); setFormOpen(true); }
  }, [createRequest, canEdit]);

  return (
    <div data-testid="tasks-panel">
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '16px' }}>
        <div>
          <h2 style={{ margin: 0, fontSize: '1.15rem', color: 'var(--ink)' }}>
            Tasks
            <span style={{ marginLeft: '8px', fontSize: '0.75rem', color: 'var(--neutral-500)', fontWeight: 500 }} data-testid="tasks-count">
              ({tasks.length})
            </span>
          </h2>
          <div style={{ fontSize: '0.8rem', color: 'var(--neutral-500)' }}>
            Follow-ups for this account. Scheduling a task is not engagement.
          </div>
        </div>
        {canEdit && (
          <ActionButton variant="primary" icon={<SectionIcon name="➕" size={16} />} aria-label="Add task" onClick={() => { setEditConflict(false); setEditingTask(null); setForm(emptyForm()); setSaveError(null); setFormOpen(true); }}>
              Add Task
            </ActionButton>
        )}
      </div>

      {error && (
        <div role="alert" style={{ padding: '10px 14px', background: 'rgba(220,53,69,0.1)', color: 'var(--status-negative)', borderRadius: 'var(--radius)', marginBottom: '12px', fontSize: '0.85rem' }}>
          <div data-testid="tasks-error">{error}</div><ActionButton variant="quiet" density="compact" onClick={() => void load()}>Retry tasks</ActionButton>
        </div>
      )}

      {formOpen && (
        <div style={{ background: 'var(--neutral-0)', borderRadius: 'var(--radius)', padding: '16px', boxShadow: 'var(--shadow-card)', marginBottom: '16px' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '12px' }}>
            <h3 style={{ margin: 0, fontSize: '1rem' }}>{editingTask ? 'Edit Task' : 'Add Task'}</h3>
            <button aria-label="Close form" onClick={() => setFormOpen(false)} style={{ background: 'none', border: 'none', cursor: 'pointer', fontSize: '1rem' }}>✕</button>
          </div>
          {editConflict && <ActionButton variant="secondary" density="compact" onClick={async () => {
            if (!editingTask || !window.confirm('Reload this task and discard your unsaved changes?')) return;
            try { const row = await api.getTask(editingTask.id); setEditingTask(row); setForm({ title: row.title, detail: row.detail ?? '', assignee: row.assignee ?? '', due_at: row.due_at?.slice(0, 16) ?? '', due_date: row.due_date ?? '' }); setEditConflict(false); setSaveError(null); }
            catch { setSaveError('Task could not be reloaded. Retry or cancel editing.'); }
          }}>Reload task</ActionButton>}
          {saveError && (
            <div role="alert" data-testid="task-save-error" style={{ padding: '8px 12px', background: 'rgba(220,53,69,0.1)', color: 'var(--status-negative)', borderRadius: 'var(--radius)', marginBottom: '12px', fontSize: '0.85rem' }}>{saveError}</div>
          )}
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(min(200px, 100%), 1fr))', gap: '12px' }}>
            <Field label="Title *"><input autoFocus aria-label="Task title" style={inputStyle} value={form.title} onChange={(e) => set('title', e.target.value)} /></Field>
            <Field label="Assignee">
              <select aria-label="Task assignee" style={inputStyle} value={form.assignee} onChange={(e) => set('assignee', e.target.value)}>{form.assignee && !assignees.some(user => user.username === form.assignee) && <option value={form.assignee}>{form.assignee} (current assignment)</option>}{assigneeOptions}</select>
            </Field>
            <Field label="Due time (UTC) — or a date"><input type="datetime-local" aria-label="Due time" style={inputStyle} value={form.due_at} onChange={(e) => set('due_at', e.target.value)} /></Field>
            <Field label="Due date — or a time"><input type="date" aria-label="Due date" style={inputStyle} value={form.due_date} onChange={(e) => set('due_date', e.target.value)} /></Field>
          </div>
          <div style={{ marginTop: '12px' }}>
            <Field label="Detail"><textarea aria-label="Task detail" rows={3} style={inputStyle} value={form.detail} onChange={(e) => set('detail', e.target.value)} /></Field>
          </div>
          <div style={{ display: 'flex', gap: '10px', marginTop: '14px' }}>
            <ActionButton variant="primary" busy={saving} aria-label="Save task" disabled={saving || editConflict} onClick={submit}>
              {editingTask ? 'Save Task' : 'Add Task'}
            </ActionButton>
            <ActionButton variant="secondary" aria-label="Cancel" onClick={() => setFormOpen(false)}>
              Cancel
            </ActionButton>
          </div>
        </div>
      )}

      <SavedViewsMenu surface="account_tasks" customerId={customerId} currentParams={{ customer_id: String(customerId), view }} onApply={params => { if (params.customer_id === String(customerId)) setView(params.view ?? 'all'); }} />
      <label>Show tasks <select aria-label="Task view" value={view} onChange={event => setView(event.target.value)}>
        <option value="all">All tasks</option><option value="open">Open tasks</option><option value="overdue">Overdue tasks</option><option value="mine">Assigned to me</option>
      </select></label>
      {!loading && tasks.length > 0 && visibleTasks.length === 0 && <p>No tasks match this view. <ActionButton variant="quiet" density="compact" onClick={() => setView('all')}>Show all tasks</ActionButton></p>}
      {loading ? (
        <div style={{ padding: '24px', textAlign: 'center', color: 'var(--neutral-500)' }}>Loading…</div>
      ) : error && tasks.length === 0 ? <p>Task records unavailable.</p> : tasks.length === 0 ? (
        <div style={{ padding: '24px', textAlign: 'center', color: 'var(--neutral-500)', background: 'var(--neutral-0)', borderRadius: 'var(--radius)' }}>
          No tasks yet.
        </div>
      ) : (
        visibleTasks.map((t) => {
          const active = t.status === 'open' || t.status === 'in_progress';
          return (
            <div key={t.id} data-testid={`task-row-${t.id}`} style={{ background: 'var(--neutral-0)', borderRadius: 'var(--radius)', boxShadow: 'var(--shadow-card)', marginBottom: '8px', padding: '12px 14px', opacity: t.status === 'cancelled' ? 0.7 : 1 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '10px', flexWrap: 'wrap' }}>
                <span style={{ fontWeight: 700, color: 'var(--ink)', fontSize: '0.92rem' }}>{t.title}</span>
                <span data-testid={`task-status-${t.id}`} style={{ fontSize: '0.72rem', color: 'var(--neutral-0)', background: t.status === 'completed' ? 'var(--status-positive, #2e7d32)' : 'var(--brand-500)', borderRadius: '10px', padding: '2px 8px', fontWeight: 600 }}>
                  {t.status}
                </span>
                <span data-testid={`task-assignee-${t.id}`} style={{ fontSize: '0.8rem', color: 'var(--neutral-600)' }}>
                  {t.assignee ? `Assignee: ${t.assignee}` : 'Unassigned'}
                </span>
                <span data-testid={`task-due-${t.id}`} style={{ fontSize: '0.8rem', color: t.overdue ? 'var(--status-negative)' : 'var(--neutral-600)', fontWeight: t.overdue ? 700 : 400 }}>
                  Due: {renderDue(t)}{t.overdue ? ' (overdue)' : t.due_soon ? ' (due soon)' : ''}
                </span>
                {t.needs_reassignment && (
                  <span data-testid={`task-needs-reassignment-${t.id}`} style={{ fontSize: '0.72rem', color: 'var(--status-warning)', border: '1px solid var(--status-warning)', borderRadius: '10px', padding: '2px 8px', fontWeight: 600 }}>
                    Needs reassignment
                  </span>
                )}
              </div>
              {t.detail && <div style={{ marginTop: '6px', fontSize: '0.85rem', color: 'var(--ink)', whiteSpace: 'pre-wrap' }}>{t.detail}</div>}
              <div style={{ marginTop: '6px', fontSize: '0.78rem', color: 'var(--neutral-500)' }} data-testid={`task-meta-${t.id}`}>
                Created by {t.created_by} · Evidence: {t.evidence_note_count} note(s), {t.evidence_activity_count} activit{t.evidence_activity_count === 1 ? 'y' : 'ies'}
              </div>
              {canEdit && (
                <div style={{ display: 'flex', gap: '10px', marginTop: '10px', flexWrap: 'wrap', alignItems: 'center' }}>
                  <ActionButton variant="secondary" density="compact" aria-label={`Edit task ${t.title}`} onClick={() => {
                    setEditConflict(false); setEditingTask(t); setSaveError(null); setForm({ title: t.title, detail: t.detail ?? '', assignee: t.assignee ?? '', due_at: t.due_at?.slice(0, 16) ?? '', due_date: t.due_date ?? '' }); setFormOpen(true);
                  }}>Edit</ActionButton>
                  {t.status === 'open'  && <ActionButton variant="quiet" density="compact" aria-label={`Start task ${t.title}`} onClick={() => change(t, { status: 'in_progress' })}>Start</ActionButton>}
                  {active && <ActionButton variant="secondary" density="compact" aria-label={`Complete task ${t.title}`} onClick={() => change(t, { status: 'completed' })}>Complete</ActionButton>}
                  {t.status === 'completed' && <ActionButton variant="secondary" density="compact" aria-label={`Reopen task ${t.title}`} onClick={() => change(t, { status: 'open' })}>Reopen</ActionButton>}
                  {active && <ActionButton variant="quiet" density="compact" aria-label={`Cancel task ${t.title}`} onClick={() => change(t, { status: 'cancelled' })}>Cancel</ActionButton>}
                  {active && reassignId !== t.id && (
                    <ActionButton variant="secondary" density="compact" aria-label={`Reassign task ${t.title}`} onClick={() => { setReassignId(t.id); setReassignTo(''); }}>Reassign</ActionButton>
                  )}
                  {reassignId === t.id && (
                    <>
                      <select aria-label="Reassign to username" style={inputStyle} value={reassignTo} onChange={(e) => setReassignTo(e.target.value)}>{assigneeOptions}</select>
                      <ActionButton variant="secondary" density="compact" aria-label="Confirm reassign" disabled={!reassignTo.trim()} onClick={() => change(t, { assignee: reassignTo.trim() })}>Assign</ActionButton>
                      <ActionButton variant="quiet" density="compact" aria-label="Cancel reassign" onClick={() => setReassignId(null)}>Back</ActionButton>
                    </>
                  )}
                  {confirmDeleteId === t.id ? (
                    <ActionButton variant="danger" density="compact" aria-label="Confirm delete" onClick={() => doDelete(t)}>Confirm delete?</ActionButton>
                  ) : (
                    <ActionButton variant="secondary" data-tone="danger" density="compact" aria-label={`Delete task ${t.title}`} onClick={() => setConfirmDeleteId(t.id)}>Delete</ActionButton>
                  )}
                </div>
              )}
            </div>
          );
        })
      )}
    </div>
  );
}
