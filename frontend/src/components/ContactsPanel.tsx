import { ActionButton } from './ActionButton';
import { SectionIcon } from './SectionIcon';
import { useAccountListState } from '../lib/useAccountListState';
/**
 * H4 — Contacts + buying coverage panel (Intelligence secondary rail).
 *
 * Contacts are customer-owned observations. Honesty rules (contract S0):
 * the coverage block renders backend strings verbatim (gaps, the
 * last-contacted basis, the delete 409 message) — the UI never restates the
 * wording or infers roles/people. Unknown fields render as absent / "—".
 */
import { useEffect, useState } from 'react';
import { api } from '../lib/api';
import { SalesPersona, VERIFICATION_STATES } from '../types/sail';
import {
  BUYING_ROLES,
  BUYING_ROLE_LABELS,
  BuyingRoleInput,
  ContactCoverage,
  CustomerContact,
} from '../types/contact';

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

function roleLabel(role: string): string {
  return (BUYING_ROLE_LABELS as Record<string, string>)[role] ?? role;
}

const emptyForm = () => ({
  display_name: '', title: '', email: '', phone: '', department: '', persona: '',
  source: '', observation_date: '', verification_state: 'verified',
  roles: [] as string[],
  role_source: '', role_observation_date: '', role_verification_state: 'verified',
});

export function ContactsPanel({ customerId, userRole, createRequest = 0, allowCreate }: Props) {
  const [filters, updateFilters] = useAccountListState(customerId, 'contact', { coverage: 'all' });
  const [contacts, setContacts] = useState<CustomerContact[]>([]);
  const [coverage, setCoverage] = useState<ContactCoverage | null>(null);
  const [personas, setPersonas] = useState<SalesPersona[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [archiveHint, setArchiveHint] = useState(false);
  const [showArchived, setShowArchived] = useState(false);

  const [expandedId, setExpandedId] = useState<number | null>(null);
  const [formOpen, setFormOpen] = useState(false);
  const [editing, setEditing] = useState<CustomerContact | null>(null);
  const [form, setForm] = useState(emptyForm());
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [confirmDeleteId, setConfirmDeleteId] = useState<number | null>(null);

  const canEdit = (allowCreate ?? true) && userRole !== 'auditor' && userRole !== 'none';

  const load = async (includeArchived = showArchived) => {
    setLoading(true);
    setError(null);
    try {
      const [list, cov] = await Promise.all([
        api.listCustomerContacts(customerId, { includeArchived }),
        api.getContactCoverage(customerId),
      ]);
      setContacts(Array.isArray(list) ? list : []);
      setCoverage(cov && typeof cov === 'object' ? cov : null);
    } catch (e: any) {
      setError(e?.message || 'Failed to load contacts');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    setContacts([]);
    setCoverage(null);
    setExpandedId(null);
    setFormOpen(false);
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [customerId]);

  useEffect(() => {
    let alive = true;
    api.listSalesPersonas()
      .then((p) => { if (alive && Array.isArray(p)) setPersonas(p); })
      .catch(() => { /* persona select stays empty; persona is optional */ });
    return () => { alive = false; };
  }, []);

  const toggleArchived = (v: boolean) => {
    setShowArchived(v);
    load(v);
  };

  // Names are read from the recorded contact rows (no fabrication); only
  // non-archived contacts count toward current coverage.
  const namesWithRole = (role: string) =>
    contacts
      .filter((c) => !c.archived && c.buying_roles.some((r) => r.role === role))
      .map((c) => c.display_name);

  const gapFor = (needle: string): string | null =>
    coverage?.gaps.find((g) => g.toLowerCase().includes(needle)) ?? null;

  const roleLine = (recorded: boolean | undefined, role: string, needle: string): string => {
    if (recorded) {
      const names = namesWithRole(role);
      return names.length ? names.join(', ') : 'recorded';
    }
    return gapFor(needle) ?? '—';
  };

  const personaLabel = (id: string) => personas.find((p) => p.id === id)?.label ?? id;

  const coverageBlock = coverage;

  const startCreate = () => {
    setEditing(null);
    setForm(emptyForm());
    setSaveError(null);
    setFormOpen(true);
    setExpandedId(null);
  };
  const startEdit = (c: CustomerContact) => {
    setEditing(c);
    setForm({
      display_name: c.display_name, title: c.title || '', email: c.email || '', phone: c.phone || '',
      department: c.department || '', persona: c.persona || '', source: c.source || '',
      observation_date: c.observation_date || '', verification_state: c.verification_state,
      roles: c.buying_roles.map((r) => r.role),
      role_source: '', role_observation_date: '', role_verification_state: 'verified',
    });
    setSaveError(null);
    setFormOpen(true);
    setExpandedId(null);
  };
  const set = <K extends keyof ReturnType<typeof emptyForm>>(k: K, v: ReturnType<typeof emptyForm>[K]) =>
    setForm((f) => ({ ...f, [k]: v }));
  const toggleRole = (role: string) =>
    setForm((f) => ({ ...f, roles: f.roles.includes(role) ? f.roles.filter((r) => r !== role) : [...f.roles, role] }));

  const submit = async () => {
    if (!form.display_name.trim()) {
      setSaveError('Display name is required.');
      return;
    }
    if (form.persona && personas.length > 0 && !personas.some((p) => p.id === form.persona)) {
      setSaveError(`Unknown persona '${form.persona}'. Choose one from the list.`);
      return;
    }
    // Retained roles keep their recorded provenance; newly added roles take
    // the form-level provenance entered for this submit.
    const existing = new Map((editing?.buying_roles ?? []).map((r) => [r.role, r]));
    const buying_roles: BuyingRoleInput[] = BUYING_ROLES.filter((r) => form.roles.includes(r)).map((role) => {
      const prior = existing.get(role);
      if (prior) {
        return {
          role,
          source: prior.source,
          observation_date: prior.observation_date,
          verification_state: prior.verification_state,
        };
      }
      return {
        role,
        source: form.role_source.trim() || null,
        observation_date: form.role_observation_date || null,
        verification_state: form.role_verification_state || 'verified',
      };
    });
    const payload = {
      display_name: form.display_name.trim(),
      title: form.title.trim() || null,
      email: form.email.trim() || null,
      phone: form.phone.trim() || null,
      department: form.department.trim() || null,
      persona: form.persona || null,
      source: form.source.trim() || null,
      observation_date: form.observation_date || null,
      verification_state: form.verification_state || 'verified',
      buying_roles,
    };
    setSaving(true);
    setSaveError(null);
    try {
      if (editing) {
        await api.updateContact(editing.id, payload);
      } else {
        await api.createContact(customerId, payload);
      }
      setFormOpen(false);
      await load();
    } catch (e: any) {
      setSaveError(e?.message || 'Failed to save');
    } finally {
      setSaving(false);
    }
  };

  const setArchived = async (c: CustomerContact, archived: boolean) => {
    setError(null);
    try {
      await api.updateContact(c.id, { archived });
      await load();
    } catch (e: any) {
      setError(e?.message || 'Failed to update contact');
    }
  };

  const doDelete = async (id: number) => {
    setConfirmDeleteId(null);
    setError(null);
    setArchiveHint(false);
    try {
      await api.deleteContact(id);
      if (expandedId === id) setExpandedId(null);
      await load();
    } catch (e: any) {
      // Backend message verbatim (409 = linked notes → archive instead).
      setError(e?.message || 'Failed to delete');
      setArchiveHint(e?.status === 409);
    }
  };


  useEffect(() => {
    if (createRequest && canEdit) { setEditing(null); setForm(emptyForm()); setSaveError(null); setFormOpen(true); }
  }, [createRequest, canEdit]);

  return (
    <div data-testid="contacts-panel">
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '16px' }}>
        <div>
          <h2 style={{ margin: 0, fontSize: '1.15rem', color: 'var(--ink)' }}>
            Contacts
            <span style={{ marginLeft: '8px', fontSize: '0.75rem', color: 'var(--neutral-500)', fontWeight: 500 }} data-testid="contacts-count">
              ({contacts.length})
            </span>
          </h2>
          <div style={{ fontSize: '0.8rem', color: 'var(--neutral-500)' }}>
            People and buying roles as recorded by the team — observations, not verified org charts.
          </div>
        </div>
        {canEdit && (
          <ActionButton variant="primary" icon={<SectionIcon name="➕" size={16} />} aria-label="Add contact" onClick={startCreate}>
              Add Contact
            </ActionButton>
        )}
      </div>

      {coverageBlock && (
        <div data-testid="contact-coverage" style={{ background: 'var(--neutral-0)', borderRadius: 'var(--radius)', padding: '12px 14px', boxShadow: 'var(--shadow-card)', marginBottom: '16px', fontSize: '0.85rem', display: 'grid', gap: '4px' }}>
          <div style={{ fontWeight: 600, color: 'var(--neutral-700)' }}>Buying coverage</div>
          <div data-testid="coverage-contacts">Contacts recorded: {coverageBlock.contacts_recorded}
            {coverageBlock.archived_count > 0 && (
              <span style={{ color: 'var(--neutral-500)' }}> (archived: {coverageBlock.archived_count})</span>
            )}
          </div>
          {coverageBlock.gaps.find((g) => g.toLowerCase().includes('no contacts')) && (
            <div data-testid="coverage-contacts-gap" style={{ color: 'var(--status-warning)' }}>
              {coverageBlock.gaps.find((g) => g.toLowerCase().includes('no contacts'))}
            </div>
          )}
          <div data-testid="coverage-economic-buyer">
            Economic buyer: {roleLine(coverageBlock.economic_buyer_recorded, 'economic_buyer', 'economic buyer')}
          </div>
          <div data-testid="coverage-champion">
            Champion: {roleLine(coverageBlock.champion_recorded, 'champion', 'champion')}
          </div>
          <div data-testid="coverage-personas">
            Personas recorded: {Object.keys(coverageBlock.personas).length} of {personas.length}
            {' '}(unknown: {coverageBlock.persona_unknown})
          </div>
          <div data-testid="coverage-last-contacted">
            Last contacted: {coverageBlock.last_contacted ?? '—'}
            <div style={{ fontSize: '0.75rem', color: 'var(--neutral-500)' }} data-testid="coverage-last-contacted-basis">
              {coverageBlock.last_contacted_basis}
            </div>
          </div>
        </div>
      )}

      <div style={{ display: 'flex', gap: '10px', marginBottom: '16px', alignItems: 'center' }}>
        <label style={{ fontSize: '0.85rem', color: 'var(--neutral-600)', display: 'flex', gap: '6px', alignItems: 'center' }}>
          <input type="checkbox" aria-label="Show archived" checked={showArchived} onChange={(e) => toggleArchived(e.target.checked)} />
          Show archived
        </label>
      </div>

      {error && (
        <div role="alert" style={{ padding: '10px 14px', background: 'rgba(220,53,69,0.1)', color: 'var(--status-negative)', borderRadius: 'var(--radius)', marginBottom: '12px', fontSize: '0.85rem' }}>
          <div data-testid="contacts-error">{error}</div>
          {archiveHint && (
            <div style={{ marginTop: '4px' }}>Use Archive instead — note references are preserved.</div>
          )}
        </div>
      )}

      {formOpen && (
        <div style={{ background: 'var(--neutral-0)', borderRadius: 'var(--radius)', padding: '16px', boxShadow: 'var(--shadow-card)', marginBottom: '16px' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '12px' }}>
            <h3 style={{ margin: 0, fontSize: '1rem' }}>{editing ? 'Edit Contact' : 'Add Contact'}</h3>
            <button aria-label="Close form" onClick={() => setFormOpen(false)} style={{ background: 'none', border: 'none', cursor: 'pointer', fontSize: '1rem' }}>✕</button>
          </div>
          {saveError && (
            <div role="alert" style={{ padding: '8px 12px', background: 'rgba(220,53,69,0.1)', color: 'var(--status-negative)', borderRadius: 'var(--radius)', marginBottom: '12px', fontSize: '0.85rem' }}>{saveError}</div>
          )}
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(min(200px, 100%), 1fr))', gap: '12px' }}>
            <Field label="Display name *"><input style={inputStyle} value={form.display_name} onChange={(e) => set('display_name', e.target.value)} /></Field>
            <Field label="Title"><input style={inputStyle} value={form.title} onChange={(e) => set('title', e.target.value)} /></Field>
            <Field label="Department"><input style={inputStyle} value={form.department} onChange={(e) => set('department', e.target.value)} /></Field>
            <Field label="Email"><input style={inputStyle} value={form.email} onChange={(e) => set('email', e.target.value)} /></Field>
            <Field label="Phone"><input style={inputStyle} value={form.phone} onChange={(e) => set('phone', e.target.value)} /></Field>
            <Field label="Persona">
              <select style={inputStyle} value={form.persona} onChange={(e) => set('persona', e.target.value)}>
                <option value="">Not recorded</option>
                {personas.map((p) => (<option key={p.id} value={p.id}>{p.label}</option>))}
                {form.persona && !personas.some((p) => p.id === form.persona) && (
                  <option value={form.persona}>{form.persona}</option>
                )}
              </select>
            </Field>
            <Field label="Source"><input style={inputStyle} placeholder="e.g. discovery call" value={form.source} onChange={(e) => set('source', e.target.value)} /></Field>
            <Field label="Observation date"><input type="date" style={inputStyle} value={form.observation_date} onChange={(e) => set('observation_date', e.target.value)} /></Field>
            <Field label="Verification state">
              <select style={inputStyle} value={form.verification_state} onChange={(e) => set('verification_state', e.target.value)}>
                {VERIFICATION_STATES.map((v) => (<option key={v} value={v}>{v}</option>))}
              </select>
            </Field>
          </div>
          <fieldset style={{ marginTop: '12px', border: '1px solid var(--divider)', borderRadius: 'var(--radius)' }}>
            <legend style={{ fontSize: '0.8rem', color: 'var(--neutral-600)' }}>Buying roles (explicit observations)</legend>
            <div style={{ display: 'flex', gap: '14px', flexWrap: 'wrap' }}>
              {BUYING_ROLES.map((r) => (
                <label key={r} style={{ fontSize: '0.85rem', display: 'flex', gap: '4px', alignItems: 'center' }}>
                  <input type="checkbox" aria-label={`Role ${BUYING_ROLE_LABELS[r]}`} checked={form.roles.includes(r)} onChange={() => toggleRole(r)} />
                  {BUYING_ROLE_LABELS[r]}
                </label>
              ))}
            </div>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: '12px', marginTop: '10px' }}>
              <Field label="Role source (applies to roles added now)"><input style={inputStyle} value={form.role_source} onChange={(e) => set('role_source', e.target.value)} /></Field>
              <Field label="Role observation date"><input type="date" style={inputStyle} value={form.role_observation_date} onChange={(e) => set('role_observation_date', e.target.value)} /></Field>
              <Field label="Role verification state">
                <select style={inputStyle} value={form.role_verification_state} onChange={(e) => set('role_verification_state', e.target.value)}>
                  {VERIFICATION_STATES.map((v) => (<option key={v} value={v}>{v}</option>))}
                </select>
              </Field>
            </div>
          </fieldset>
          <div style={{ display: 'flex', gap: '10px', marginTop: '14px' }}>
            <ActionButton variant="primary" busy={saving} aria-label="Save contact" onClick={submit}>
              {editing ? 'Save Changes' : 'Add Contact'}
            </ActionButton>
            <ActionButton variant="secondary" aria-label="Cancel" onClick={() => setFormOpen(false)}>
              Cancel
            </ActionButton>
          </div>
        </div>
      )}

      {filters.coverage === 'gaps' && <section className="crm-surface" aria-label="Buying coverage gaps">
        <h3>Missing buying roles</h3><p>{coverage ? coverage.gaps.join(' · ') || 'No buying-role gaps recorded.' : 'Buying coverage unavailable.'}</p>
        <p>Add or update a contact to record the missing buying role. Unknown roles are not inferred.</p>
        <ActionButton variant="quiet" density="compact" onClick={() => updateFilters({ coverage: 'all' })}>Show all contact context</ActionButton>
      </section>}
      {loading ? (
        <div style={{ padding: '24px', textAlign: 'center', color: 'var(--neutral-500)' }}>Loading…</div>
      ) : contacts.length === 0 ? (
        <div style={{ padding: '24px', textAlign: 'center', color: 'var(--neutral-500)', background: 'var(--neutral-0)', borderRadius: 'var(--radius)' }}>
          No contacts recorded yet.
        </div>
      ) : (
        contacts.map((c) => {
          const expanded = expandedId === c.id;
          return (
            <div key={c.id} data-testid={`contact-row-${c.id}`} style={{ background: 'var(--neutral-0)', borderRadius: 'var(--radius)', boxShadow: 'var(--shadow-card)', marginBottom: '8px', overflow: 'hidden', opacity: c.archived ? 0.75 : 1 }}>
              <div tabIndex={0} aria-label={`Toggle contact ${c.display_name}`} onClick={() => setExpandedId(expanded ? null : c.id)}
                onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') setExpandedId(expanded ? null : c.id); }}
                style={{ display: 'flex', alignItems: 'center', gap: '10px', padding: '12px 14px', cursor: 'pointer', flexWrap: 'wrap' }}>
                <span style={{ fontWeight: 700, color: 'var(--ink)', fontSize: '0.92rem' }}>{c.display_name}</span>
                {c.title && <span style={{ fontSize: '0.8rem', color: 'var(--neutral-600)' }}>{c.title}</span>}
                {c.department && <span style={{ fontSize: '0.78rem', color: 'var(--neutral-500)' }}>{c.department}</span>}
                {c.persona && (
                  <span style={{ fontSize: '0.72rem', color: 'var(--brand-700)', background: 'var(--brand-50)', borderRadius: '10px', padding: '2px 8px', fontWeight: 600 }}>
                    {c.persona_label ?? personaLabel(c.persona)}
                  </span>
                )}
                {c.buying_roles.map((r) => (
                  <span key={r.role} data-testid={`role-chip-${r.role}`} style={{ fontSize: '0.7rem', color: 'var(--neutral-0)', background: 'var(--brand-500)', borderRadius: '10px', padding: '2px 8px', fontWeight: 600 }}>
                    {r.role_label || roleLabel(r.role)}
                  </span>
                ))}
                {c.archived && (
                  <span style={{ fontSize: '0.7rem', color: 'var(--neutral-600)', background: 'var(--neutral-200)', borderRadius: '10px', padding: '2px 8px', fontWeight: 600 }}>Archived</span>
                )}
                <span style={{ fontSize: '0.7rem', color: 'var(--neutral-600)', background: 'var(--neutral-100)', borderRadius: '10px', padding: '2px 8px' }}>{c.verification_state}</span>
              </div>
              {expanded && (
                <div style={{ padding: '12px 14px', borderTop: '1px solid var(--divider)', fontSize: '0.85rem' }}>
                  <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(160px, 1fr))', gap: '10px', fontSize: '0.8rem' }}>
                    {([
                      ['Email', c.email],
                      ['Phone', c.phone],
                      ['Linked notes', String(c.note_count)],
                    ] as Array<[string, string | null]>).map(([k, val]) => (
                      <div key={k}>
                        <div style={{ color: 'var(--neutral-500)', fontSize: '0.7rem', textTransform: 'uppercase', letterSpacing: '0.3px' }}>{k}</div>
                        <div style={{ color: 'var(--ink)' }}>{val || '—'}</div>
                      </div>
                    ))}
                  </div>
                  <div data-testid={`contact-provenance-${c.id}`} style={{ marginTop: '10px', fontSize: '0.78rem', color: 'var(--neutral-500)' }}>
                    Source: {c.source || '—'} · Observed: {c.observation_date || '—'}
                  </div>
                  {canEdit && (
                    <div style={{ display: 'flex', gap: '10px', marginTop: '12px' }}>
                      <ActionButton variant="secondary" density="compact" aria-label="Edit contact" onClick={() => startEdit(c)}>Edit</ActionButton>
                      {c.archived ? (
                        <ActionButton variant="secondary" density="compact" aria-label="Restore contact" onClick={() => setArchived(c, false)}>Restore</ActionButton>
                      ) : (
                        <ActionButton variant="quiet" density="compact" aria-label="Archive contact" onClick={() => setArchived(c, true)}>Archive</ActionButton>
                      )}
                      {confirmDeleteId === c.id ? (
                        <ActionButton variant="danger" density="compact" aria-label="Confirm delete" onClick={() => doDelete(c.id)}>Confirm delete?</ActionButton>
                      ) : (
                        <ActionButton variant="secondary" data-tone="danger" density="compact" aria-label="Delete contact" onClick={() => setConfirmDeleteId(c.id)}>Delete</ActionButton>
                      )}
                    </div>
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
