/**
 * H5 — Activities panel (Intelligence secondary rail).
 *
 * Structured interactions (call / meeting / email / demo / QBR) are distinct
 * from narrative sales notes. An activity needs exactly one occurred date
 * (a time OR a date) — the form enforces that client-side, the backend 422
 * is authoritative and rendered verbatim. The actor is always the current
 * user (you record your own interactions). Write gate mirrors ContactsPanel:
 * hidden for auditor/none; the backend 403 is authoritative.
 */
import { useEffect, useState } from 'react';
import { api } from '../lib/api';
import { getAuthUsername } from '../lib/auth';
import { localInputToUtcIso, renderOccurred } from '../lib/engagement';
import { ACTIVITY_TYPES, ACTIVITY_TYPE_LABELS, Activity } from '../types/engagement';
import type { CustomerContact } from '../types/contact';

interface Props {
  customerId: number;
  createRequest?: number;
  allowCreate?: boolean;
  userRole?: string; // 'owner' | 'member' | 'auditor' | 'none'
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

const emptyForm = () => ({
  type: 'call', occurred_at: '', occurred_date: '', source: '', outcome: '', contact_ids: [] as number[],
});

export function ActivitiesPanel({ customerId, userRole, createRequest = 0, allowCreate }: Props) {
  const [activities, setActivities] = useState<Activity[]>([]);
  const [contacts, setContacts] = useState<CustomerContact[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [formOpen, setFormOpen] = useState(false);
  const [form, setForm] = useState(emptyForm());
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [confirmDeleteId, setConfirmDeleteId] = useState<number | null>(null);

  const canEdit = (allowCreate ?? true) && userRole !== 'auditor' && userRole !== 'none';
  const actor = getAuthUsername();

  const load = async () => {
    setLoading(true);
    setError(null);
    try {
      const list = await api.listActivities(customerId);
      setActivities(Array.isArray(list) ? list : []);
    } catch (e: any) {
      setError(e?.message || 'Failed to load activities');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    setActivities([]);
    setFormOpen(false);
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [customerId]);

  useEffect(() => {
    let alive = true;
    setContacts([]);
    api.listCustomerContacts(customerId)
      .then((c) => { if (alive && Array.isArray(c)) setContacts(c); })
      .catch(() => { /* attendees are optional; the multi-select stays empty */ });
    return () => { alive = false; };
  }, [customerId]);

  const set = <K extends keyof ReturnType<typeof emptyForm>>(k: K, v: ReturnType<typeof emptyForm>[K]) =>
    setForm((f) => ({ ...f, [k]: v }));
  const toggleContact = (id: number) =>
    setForm((f) => ({ ...f, contact_ids: f.contact_ids.includes(id) ? f.contact_ids.filter((c) => c !== id) : [...f.contact_ids, id] }));

  const submit = async () => {
    // Exactly-one rule (mirrors the backend): a time OR a date, never both/neither.
    if (form.occurred_at && form.occurred_date) {
      setSaveError('Provide either a time or a date, not both.');
      return;
    }
    if (!form.occurred_at && !form.occurred_date) {
      setSaveError('An activity needs an occurred time or date.');
      return;
    }
    setSaving(true);
    setSaveError(null);
    try {
      await api.createActivity(customerId, {
        type: form.type,
        occurred_at: form.occurred_at ? localInputToUtcIso(form.occurred_at) : null,
        occurred_date: form.occurred_date || null,
        actor,
        source: form.source.trim() || null,
        outcome: form.outcome.trim() || null,
        contact_ids: form.contact_ids,
      });
      setFormOpen(false);
      setForm(emptyForm());
      await load();
    } catch (e: any) {
      setSaveError(e?.message || 'Failed to save');
    } finally {
      setSaving(false);
    }
  };

  const doDelete = async (id: number) => {
    setConfirmDeleteId(null);
    setError(null);
    try {
      await api.deleteActivity(id);
      await load();
    } catch (e: any) {
      setError(e?.message || 'Failed to delete');
    }
  };

  useEffect(() => {
    if (createRequest && canEdit) { setForm(emptyForm()); setSaveError(null); setFormOpen(true); }
  }, [createRequest, canEdit]);

  return (
    <div data-testid="activities-panel">
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '16px' }}>
        <div>
          <h2 style={{ margin: 0, fontSize: '1.15rem', color: 'var(--ink)' }}>
            Activities
            <span style={{ marginLeft: '8px', fontSize: '0.75rem', color: 'var(--neutral-500)', fontWeight: 500 }} data-testid="activities-count">
              ({activities.length})
            </span>
          </h2>
          <div style={{ fontSize: '0.8rem', color: 'var(--neutral-500)' }}>
            Recorded interactions with this account. Only dated activities count as engagement.
          </div>
        </div>
        {canEdit && (
          <button role="button" aria-label="Add activity" onClick={() => { setForm(emptyForm()); setSaveError(null); setFormOpen(true); }}
            style={{ padding: '10px 18px', background: 'var(--brand-500)', color: 'var(--neutral-0)', border: 'none', borderRadius: 'var(--radius)', cursor: 'pointer', fontSize: '0.9rem', fontWeight: 600 }}>
            ➕ Add Activity
          </button>
        )}
      </div>

      {error && (
        <div role="alert" data-testid="activities-error" style={{ padding: '10px 14px', background: 'rgba(220,53,69,0.1)', color: 'var(--status-negative)', borderRadius: 'var(--radius)', marginBottom: '12px', fontSize: '0.85rem' }}>
          {error}
        </div>
      )}

      {formOpen && (
        <div style={{ background: 'var(--neutral-0)', borderRadius: 'var(--radius)', padding: '16px', boxShadow: 'var(--shadow-card)', marginBottom: '16px' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '12px' }}>
            <h3 style={{ margin: 0, fontSize: '1rem' }}>Add Activity</h3>
            <button role="button" aria-label="Close form" onClick={() => setFormOpen(false)} style={{ background: 'none', border: 'none', cursor: 'pointer', fontSize: '1rem' }}>✕</button>
          </div>
          {saveError && (
            <div role="alert" data-testid="activity-save-error" style={{ padding: '8px 12px', background: 'rgba(220,53,69,0.1)', color: 'var(--status-negative)', borderRadius: 'var(--radius)', marginBottom: '12px', fontSize: '0.85rem' }}>{saveError}</div>
          )}
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(min(200px, 100%), 1fr))', gap: '12px' }}>
            <Field label="Type *">
              <select aria-label="Activity type" style={inputStyle} value={form.type} onChange={(e) => set('type', e.target.value)}>
                {ACTIVITY_TYPES.map((t) => (<option key={t} value={t}>{ACTIVITY_TYPE_LABELS[t]}</option>))}
              </select>
            </Field>
            <Field label="Time (UTC) — or a date">
              <input type="datetime-local" aria-label="Occurred time" style={inputStyle} value={form.occurred_at} onChange={(e) => set('occurred_at', e.target.value)} />
            </Field>
            <Field label="Date — or a time">
              <input type="date" aria-label="Occurred date" style={inputStyle} value={form.occurred_date} onChange={(e) => set('occurred_date', e.target.value)} />
            </Field>
            <Field label="Actor">
              <input aria-label="Actor" style={{ ...inputStyle, background: 'var(--neutral-100)' }} value={actor} readOnly />
            </Field>
            <Field label="Source"><input aria-label="Activity source" style={inputStyle} value={form.source} onChange={(e) => set('source', e.target.value)} /></Field>
          </div>
          <div style={{ marginTop: '12px' }}>
            <Field label="Outcome">
              <textarea aria-label="Activity outcome" rows={3} style={inputStyle} value={form.outcome} onChange={(e) => set('outcome', e.target.value)} />
            </Field>
          </div>
          <fieldset style={{ marginTop: '12px', border: '1px solid var(--divider)', borderRadius: 'var(--radius)' }}>
            <legend style={{ fontSize: '0.8rem', color: 'var(--neutral-600)' }}>Attendees (account contacts)</legend>
            {contacts.length === 0 ? (
              <div style={{ fontSize: '0.8rem', color: 'var(--neutral-500)' }}>No contacts recorded.</div>
            ) : (
              <div style={{ display: 'flex', gap: '14px', flexWrap: 'wrap' }}>
                {contacts.map((c) => (
                  <label key={c.id} style={{ fontSize: '0.85rem', display: 'flex', gap: '4px', alignItems: 'center' }}>
                    <input type="checkbox" aria-label={`Attendee ${c.display_name}`} checked={form.contact_ids.includes(c.id)} onChange={() => toggleContact(c.id)} />
                    {c.display_name}
                  </label>
                ))}
              </div>
            )}
          </fieldset>
          <div style={{ display: 'flex', gap: '10px', marginTop: '14px' }}>
            <button role="button" aria-label="Save activity" disabled={saving} onClick={submit}
              style={{ padding: '10px 18px', background: saving ? 'var(--neutral-300)' : 'var(--brand-500)', color: saving ? 'var(--neutral-700)' : 'var(--neutral-0)', border: 'none', borderRadius: 'var(--radius)', cursor: saving ? 'not-allowed' : 'pointer', fontSize: '0.9rem', fontWeight: 600 }}>
              {saving ? 'Saving…' : 'Add Activity'}
            </button>
            <button role="button" aria-label="Cancel" onClick={() => setFormOpen(false)}
              style={{ padding: '10px 18px', background: 'var(--neutral-0)', color: 'var(--neutral-600)', border: '1px solid var(--divider)', borderRadius: 'var(--radius)', cursor: 'pointer', fontSize: '0.9rem' }}>
              Cancel
            </button>
          </div>
        </div>
      )}

      {loading ? (
        <div style={{ padding: '24px', textAlign: 'center', color: 'var(--neutral-500)' }}>Loading…</div>
      ) : activities.length === 0 ? (
        <div style={{ padding: '24px', textAlign: 'center', color: 'var(--neutral-500)', background: 'var(--neutral-0)', borderRadius: 'var(--radius)' }}>
          No activities recorded yet.
        </div>
      ) : (
        activities.map((a) => (
          <div key={a.id} data-testid={`activity-row-${a.id}`} style={{ background: 'var(--neutral-0)', borderRadius: 'var(--radius)', boxShadow: 'var(--shadow-card)', marginBottom: '8px', padding: '12px 14px' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '10px', flexWrap: 'wrap' }}>
              <span data-testid={`activity-type-${a.id}`} style={{ fontSize: '0.72rem', color: 'var(--neutral-0)', background: 'var(--brand-500)', borderRadius: '10px', padding: '2px 8px', fontWeight: 600 }}>
                {(ACTIVITY_TYPE_LABELS as Record<string, string>)[a.type] ?? a.type}
              </span>
              <span data-testid={`activity-occurred-${a.id}`} style={{ fontWeight: 700, color: 'var(--ink)', fontSize: '0.9rem' }}>{renderOccurred(a)}</span>
              <span style={{ fontSize: '0.8rem', color: 'var(--neutral-600)' }}>by {a.actor}</span>
              {a.attendees.length > 0 && (
                <span data-testid={`activity-attendees-${a.id}`} style={{ fontSize: '0.8rem', color: 'var(--neutral-600)' }}>
                  with {a.attendees.map((x) => x.display_name).join(', ')}
                </span>
              )}
              {a.source && <span style={{ fontSize: '0.78rem', color: 'var(--neutral-500)' }}>Source: {a.source}</span>}
            </div>
            {a.outcome && <div style={{ marginTop: '6px', fontSize: '0.85rem', color: 'var(--ink)', whiteSpace: 'pre-wrap' }}>{a.outcome}</div>}
            {canEdit && (
              <div style={{ marginTop: '8px' }}>
                {confirmDeleteId === a.id ? (
                  <button role="button" aria-label="Confirm delete" onClick={() => doDelete(a.id)}
                    style={{ padding: '6px 14px', background: 'var(--status-negative)', color: 'var(--neutral-0)', border: 'none', borderRadius: 'var(--radius)', cursor: 'pointer', fontSize: '0.8rem', fontWeight: 600 }}>
                    Confirm delete?
                  </button>
                ) : (
                  <button role="button" aria-label="Delete activity" onClick={() => setConfirmDeleteId(a.id)}
                    style={{ padding: '6px 14px', background: 'var(--neutral-0)', color: 'var(--status-negative)', border: '1px solid var(--status-negative)', borderRadius: 'var(--radius)', cursor: 'pointer', fontSize: '0.8rem' }}>
                    🗑️ Delete
                  </button>
                )}
              </div>
            )}
          </div>
        ))
      )}
    </div>
  );
}
