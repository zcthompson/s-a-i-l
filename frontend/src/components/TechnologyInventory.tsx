import { useEffect, useMemo, useState } from 'react';
import { api } from '../lib/api';
import { formatDate } from '../lib/pipelineFormat';
import {
  CustomerTechnology,
  CustomerTechnologyCreate,
  TECH_CATEGORIES,
  DEPLOYMENT_MODELS,
  LIFECYCLE_STATES,
  SUPPORT_STATES,
  BUSINESS_CRITICALITIES,
  VERIFICATION_STATES,
} from '../types/sail';

interface Props {
  customerId: number;
  allowWrite?: boolean;
  userRole?: string; // 'owner' | 'member' | 'auditor' | 'none'
}

type SortKey = 'name' | 'category' | 'business_criticality' | 'lifecycle_state';

const CRIT_ORDER: Record<string, number> = { critical: 0, high: 1, medium: 2, low: 3, '': 4 };
const LIFECYCLE_ORDER: Record<string, number> = { eol: 0, eol_announced: 1, previous_generation: 2, current: 3, unknown: 4, '': 5 };

function verificationColor(state: string): { bg: string; fg: string; label: string } {
  switch (state) {
    case 'verified': return { bg: 'var(--status-positive)', fg: 'white', label: 'Verified' };
    case 'inferred': return { bg: 'var(--status-warning)', fg: '#1f2937', label: 'Inferred' };
    default: return { bg: 'var(--neutral-200)', fg: 'var(--neutral-600)', label: 'Unverified' };
  }
}
function critColor(c: string | null): string {
  switch (c) {
    case 'critical': return 'var(--status-negative)';
    case 'high': return 'var(--status-warning)';
    case 'medium': return 'var(--brand-500)';
    default: return 'var(--neutral-400)';
  }
}

// E5 — optional dated end-of-support evidence. Sent additively through the
// existing create/update payloads (the backend accepts both fields).

const emptyForm = (): CustomerTechnologyCreate & { id?: number } => ({
  name: '',
  category: '',
  vendor: null,
  version_edition: null,
  deployment_model: null,
  quantity: null,
  footprint: null,
  purpose: null,
  lifecycle_state: null,
  support_state: null,
  business_criticality: null,
  source: null,
  date_observed: null,
  verification_state: 'unverified',
  confidence: null,
  notes: null,
  end_of_support_date: null,
  eol_source: null,
});

// A single labeled form field (text/number/date/select/textarea).
function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label style={{ display: 'flex', flexDirection: 'column', gap: '4px', fontSize: '0.8rem', color: 'var(--neutral-600)' }}>
      {label}
      {children}
    </label>
  );
}
const inputStyle: React.CSSProperties = {
  padding: '8px', border: '1px solid var(--divider)', borderRadius: 'var(--radius)', fontSize: '0.85rem', background: 'var(--neutral-0)', color: 'var(--ink)',
};

export function TechnologyInventory({ customerId, allowWrite = false }: Props) {
  const [items, setItems] = useState<CustomerTechnology[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [categoryFilter, setCategoryFilter] = useState('');
  const [verificationFilter, setVerificationFilter] = useState('');
  const [search, setSearch] = useState('');
  const [sort, setSort] = useState<SortKey>('name');

  const [expandedId, setExpandedId] = useState<number | null>(null);
  const [formOpen, setFormOpen] = useState(false);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [form, setForm] = useState(emptyForm());
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [confirmDeleteId, setConfirmDeleteId] = useState<number | null>(null);

  const canEdit = allowWrite;

  const load = async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await api.listCustomerTechnology(customerId);
      setItems(data);
    } catch (e: any) {
      setError(e?.message || 'Failed to load technology inventory');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    setItems([]);
    setExpandedId(null);
    setFormOpen(false);
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [customerId]);

  const categoriesInUse = useMemo(
    () => Array.from(new Set(items.map((i) => i.category))).sort(),
    [items],
  );

  const filtered = useMemo(() => {
    let out = items;
    if (categoryFilter) out = out.filter((i) => i.category === categoryFilter);
    if (verificationFilter) out = out.filter((i) => i.verification_state === verificationFilter);
    if (search.trim()) {
      const q = search.trim().toLowerCase();
      out = out.filter(
        (i) =>
          i.name.toLowerCase().includes(q) ||
          (i.vendor || '').toLowerCase().includes(q) ||
          (i.version_edition || '').toLowerCase().includes(q),
      );
    }
    const cmp = (a: CustomerTechnology, b: CustomerTechnology): number => {
      switch (sort) {
        case 'business_criticality': return (CRIT_ORDER[a.business_criticality || ''] - CRIT_ORDER[b.business_criticality || '']) || a.name.localeCompare(b.name);
        case 'lifecycle_state': return (LIFECYCLE_ORDER[a.lifecycle_state || ''] - LIFECYCLE_ORDER[b.lifecycle_state || '']) || a.name.localeCompare(b.name);
        case 'category': return a.category.localeCompare(b.category) || a.name.localeCompare(b.name);
        default: return a.name.localeCompare(b.name);
      }
    };
    return [...out].sort(cmp);
  }, [items, categoryFilter, verificationFilter, search, sort]);

  const groups = useMemo(() => {
    const m = new Map<string, CustomerTechnology[]>();
    for (const it of filtered) {
      const key = it.category || 'uncategorized';
      if (!m.has(key)) m.set(key, []);
      m.get(key)!.push(it);
    }
    return Array.from(m.entries()).sort(([a], [b]) => a.localeCompare(b));
  }, [filtered]);

  const summary = useMemo(() => {
    const total = items.length;
    const verified = items.filter((i) => i.verification_state === 'verified').length;
    const unverified = total - verified;
    const eol = items.filter((i) => i.lifecycle_state === 'eol' || i.lifecycle_state === 'eol_announced').length;
    return { total, verified, unverified, eol };
  }, [items]);

  const startCreate = () => {
    if (!canEdit) return;
    setEditingId(null);
    setForm(emptyForm());
    setSaveError(null);
    setFormOpen(true);
    setExpandedId(null);
  };
  const startEdit = (it: CustomerTechnology) => {
    if (!canEdit) return;
    setEditingId(it.id);
    setForm({ ...it });
    setSaveError(null);
    setFormOpen(true);
    setExpandedId(null);
  };
  const set = <K extends keyof CustomerTechnologyCreate>(k: K, v: CustomerTechnologyCreate[K]) =>
    setForm((f) => ({ ...f, [k]: v }));

  const submit = async () => {
    if (!canEdit) return;
    if (!form.name.trim() || !form.category.trim()) {
      setSaveError('Name and category are required.');
      return;
    }
    setSaving(true);
    setSaveError(null);
    try {
      const payload: CustomerTechnologyCreate = {
        name: form.name.trim(),
        category: form.category,
        vendor: form.vendor || null,
        version_edition: form.version_edition || null,
        deployment_model: form.deployment_model || null,
        quantity: form.quantity || null,
        footprint: form.footprint || null,
        purpose: form.purpose || null,
        lifecycle_state: form.lifecycle_state || null,
        support_state: form.support_state || null,
        business_criticality: form.business_criticality || null,
        source: form.source || null,
        date_observed: form.date_observed || null,
        verification_state: form.verification_state || 'unverified',
        confidence: form.confidence ?? null,
        notes: form.notes || null,
        end_of_support_date: form.end_of_support_date || null,
        eol_source: form.eol_source || null,
      };
      if (editingId) {
        await api.updateTechnology(editingId, payload);
      } else {
        await api.createTechnology(customerId, payload);
      }
      setFormOpen(false);
      await load();
    } catch (e: any) {
      setSaveError(e?.message || 'Failed to save');
    } finally {
      setSaving(false);
    }
  };

  const doDelete = async (id: number) => {
    if (!canEdit) return;
    setConfirmDeleteId(null);
    try {
      await api.deleteTechnology(id);
      if (expandedId === id) setExpandedId(null);
      await load();
    } catch (e: any) {
      setError(e?.message || 'Failed to delete');
    }
  };

  return (
    <div>
      {/* Header */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '16px' }}>
        <div>
          <h2 style={{ margin: 0, fontSize: '1.15rem', color: 'var(--ink)' }}>Technology Inventory</h2>
          <div style={{ fontSize: '0.8rem', color: 'var(--neutral-500)' }}>
            Structured, relational technology records. Verified facts vs. inferred/unverified observations are distinguished.
          </div>
        </div>
        {canEdit && (
          <button role="button" aria-label="Add technology" onClick={startCreate}
            style={{ padding: '10px 18px', background: 'var(--brand-500)', color: 'var(--neutral-0)', border: 'none', borderRadius: 'var(--radius)', cursor: 'pointer', fontSize: '0.9rem', fontWeight: 600 }}>
            ➕ Add Technology
          </button>
        )}
      </div>

      {/* Summary */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))', gap: '12px', marginBottom: '16px' }}>
        {[
          { label: 'Total Items', value: summary.total, color: 'var(--ink)' },
          { label: 'Verified', value: summary.verified, color: 'var(--status-positive)' },
          { label: 'Inferred / Unverified', value: summary.unverified, color: 'var(--status-warning)' },
          { label: 'End-of-Life', value: summary.eol, color: 'var(--status-negative)' },
        ].map((c) => (
          <div key={c.label} style={{ background: 'var(--neutral-0)', borderRadius: 'var(--radius)', padding: '12px 14px', boxShadow: 'var(--shadow-card)' }}>
            <div style={{ fontSize: '0.72rem', color: 'var(--neutral-500)' }}>{c.label}</div>
            <div style={{ fontSize: '1.6rem', fontWeight: 'bold', color: c.color }}>{c.value}</div>
          </div>
        ))}
      </div>

      {/* Filters */}
      <div style={{ display: 'flex', gap: '10px', flexWrap: 'wrap', marginBottom: '16px', alignItems: 'center' }}>
        <select aria-label="Filter by category" value={categoryFilter} onChange={(e) => setCategoryFilter(e.target.value)} style={{ ...inputStyle, minWidth: '160px' }}>
          <option value="">All categories</option>
          {categoriesInUse.map((c) => (<option key={c} value={c}>{c}</option>))}
        </select>
        <select aria-label="Filter by verification" value={verificationFilter} onChange={(e) => setVerificationFilter(e.target.value)} style={{ ...inputStyle, minWidth: '150px' }}>
          <option value="">All verification</option>
          {VERIFICATION_STATES.map((v) => (<option key={v} value={v}>{v}</option>))}
        </select>
        <input aria-label="Search technology" placeholder="Search name / vendor / version…" value={search} onChange={(e) => setSearch(e.target.value)} style={{ ...inputStyle, minWidth: '220px', flex: '1 1 220px' }} />
        <select aria-label="Sort" value={sort} onChange={(e) => setSort(e.target.value as SortKey)} style={{ ...inputStyle, minWidth: '160px' }}>
          <option value="name">Sort: Name</option>
          <option value="category">Sort: Category</option>
          <option value="business_criticality">Sort: Criticality</option>
          <option value="lifecycle_state">Sort: Lifecycle</option>
        </select>
      </div>

      {error && (
        <div style={{ padding: '10px 14px', background: 'rgba(220,53,69,0.1)', color: 'var(--status-negative)', borderRadius: 'var(--radius)', marginBottom: '12px', fontSize: '0.85rem' }}>
          {error}
        </div>
      )}

      {/* Create / Edit form */}
      {formOpen && canEdit && (
        <div style={{ background: 'var(--neutral-0)', borderRadius: 'var(--radius)', padding: '16px', boxShadow: 'var(--shadow-card)', marginBottom: '16px' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '12px' }}>
            <h3 style={{ margin: 0, fontSize: '1rem' }}>{editingId ? 'Edit Technology' : 'Add Technology'}</h3>
            <button role="button" aria-label="Close form" onClick={() => setFormOpen(false)} style={{ background: 'none', border: 'none', cursor: 'pointer', fontSize: '1rem' }}>✕</button>
          </div>
          {saveError && (
            <div style={{ padding: '8px 12px', background: 'rgba(220,53,69,0.1)', color: 'var(--status-negative)', borderRadius: 'var(--radius)', marginBottom: '12px', fontSize: '0.85rem' }}>{saveError}</div>
          )}
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: '12px' }}>
            <Field label="Name *"><input style={inputStyle} value={form.name} onChange={(e) => set('name', e.target.value)} /></Field>
            <Field label="Category *">
              <select style={inputStyle} value={form.category} onChange={(e) => set('category', e.target.value)}>
                <option value="">Select…</option>
                {TECH_CATEGORIES.map((c) => (<option key={c} value={c}>{c}</option>))}
              </select>
            </Field>
            <Field label="Vendor"><input style={inputStyle} value={form.vendor || ''} onChange={(e) => set('vendor', e.target.value || null)} /></Field>
            <Field label="Version / Edition"><input style={inputStyle} value={form.version_edition || ''} onChange={(e) => set('version_edition', e.target.value || null)} /></Field>
            <Field label="Deployment Model">
              <select style={inputStyle} value={form.deployment_model || ''} onChange={(e) => set('deployment_model', e.target.value || null)}>
                <option value="">Unknown</option>
                {DEPLOYMENT_MODELS.map((d) => (<option key={d} value={d}>{d}</option>))}
              </select>
            </Field>
            <Field label="Quantity"><input type="number" min={1} style={inputStyle} value={form.quantity ?? ''} onChange={(e) => set('quantity', e.target.value ? Number(e.target.value) : null)} /></Field>
            <Field label="Footprint"><input style={inputStyle} value={form.footprint || ''} placeholder="e.g. 12 VMs, 2 sites" onChange={(e) => set('footprint', e.target.value || null)} /></Field>
            <Field label="Purpose"><input style={inputStyle} value={form.purpose || ''} onChange={(e) => set('purpose', e.target.value || null)} /></Field>
            <Field label="Lifecycle State">
              <select style={inputStyle} value={form.lifecycle_state || ''} onChange={(e) => set('lifecycle_state', e.target.value || null)}>
                <option value="">Unknown</option>
                {LIFECYCLE_STATES.map((l) => (<option key={l} value={l}>{l}</option>))}
              </select>
            </Field>
            <Field label="Support State">
              <select style={inputStyle} value={form.support_state || ''} onChange={(e) => set('support_state', e.target.value || null)}>
                <option value="">Unknown</option>
                {SUPPORT_STATES.map((s) => (<option key={s} value={s}>{s}</option>))}
              </select>
            </Field>
            <Field label="End-of-Support Date"><input type="date" style={inputStyle} value={form.end_of_support_date || ''} onChange={(e) => setForm((f) => ({ ...f, end_of_support_date: e.target.value || null }))} /></Field>
            <Field label="EOL Source"><input style={inputStyle} maxLength={255} placeholder="e.g. vendor lifecycle page" value={form.eol_source || ''} onChange={(e) => setForm((f) => ({ ...f, eol_source: e.target.value || null }))} /></Field>
            <div style={{ gridColumn: '1 / -1', fontSize: '0.75rem', color: 'var(--neutral-500)' }}>
              Dated end-of-support evidence feeds the account health End-of-support component and EOL attention cards.
            </div>
            <Field label="Business Criticality">
              <select style={inputStyle} value={form.business_criticality || ''} onChange={(e) => set('business_criticality', e.target.value || null)}>
                <option value="">Unknown</option>
                {BUSINESS_CRITICALITIES.map((c) => (<option key={c} value={c}>{c}</option>))}
              </select>
            </Field>
            <Field label="Verification State">
              <select style={inputStyle} value={form.verification_state || ''} onChange={(e) => set('verification_state', e.target.value as any)}>
                {VERIFICATION_STATES.map((v) => (<option key={v} value={v}>{v}</option>))}
              </select>
            </Field>
            <Field label="Confidence (0–1)"><input type="number" min={0} max={1} step={0.05} style={inputStyle} value={form.confidence ?? ''} onChange={(e) => set('confidence', e.target.value ? Number(e.target.value) : null)} /></Field>
            <Field label="Date Observed"><input type="date" style={inputStyle} value={form.date_observed || ''} onChange={(e) => set('date_observed', e.target.value || null)} /></Field>
            <Field label="Source (provenance)"><input style={inputStyle} placeholder="e.g. discovery call, assessment, customer document" value={form.source || ''} onChange={(e) => set('source', e.target.value || null)} /></Field>
          </div>
          <div style={{ marginTop: '12px' }}>
            <Field label="Notes">
              <textarea rows={2} style={inputStyle} value={form.notes || ''} onChange={(e) => set('notes', e.target.value || null)} />
            </Field>
          </div>
          <div style={{ display: 'flex', gap: '10px', marginTop: '14px' }}>
            <button role="button" aria-label="Save technology" disabled={saving} onClick={submit}
              style={{ padding: '10px 18px', background: saving ? 'var(--neutral-300)' : 'var(--brand-500)', color: saving ? 'var(--neutral-700)' : 'var(--neutral-0)', border: 'none', borderRadius: 'var(--radius)', cursor: saving ? 'not-allowed' : 'pointer', fontSize: '0.9rem', fontWeight: 600 }}>
              {saving ? 'Saving…' : editingId ? 'Save Changes' : 'Add Technology'}
            </button>
            <button role="button" aria-label="Cancel" onClick={() => setFormOpen(false)}
              style={{ padding: '10px 18px', background: 'var(--neutral-0)', color: 'var(--neutral-600)', border: '1px solid var(--divider)', borderRadius: 'var(--radius)', cursor: 'pointer', fontSize: '0.9rem' }}>
              Cancel
            </button>
          </div>
        </div>
      )}

      {/* List */}
      {loading ? (
        <div style={{ padding: '24px', textAlign: 'center', color: 'var(--neutral-500)' }}>Loading…</div>
      ) : groups.length === 0 ? (
        <div style={{ padding: '24px', textAlign: 'center', color: 'var(--neutral-500)', background: 'var(--neutral-0)', borderRadius: 'var(--radius)' }}>
          {items.length === 0 ? 'No technology recorded yet.' : 'No items match the current filters.'}
        </div>
      ) : (
        groups.map(([cat, list]) => (
          <div key={cat} style={{ marginBottom: '16px' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '8px' }}>
              <h3 style={{ margin: 0, fontSize: '0.95rem', color: 'var(--neutral-700)', textTransform: 'capitalize' }}>{cat}</h3>
              <span style={{ fontSize: '0.72rem', color: 'var(--neutral-500)', background: 'var(--neutral-100)', borderRadius: '10px', padding: '1px 8px' }}>{list.length}</span>
            </div>
            {list.map((it) => {
              const eolInfo = it;
              const v = verificationColor(it.verification_state);
              const expanded = expandedId === it.id;
              return (
                <div key={it.id} style={{ background: 'var(--neutral-0)', borderRadius: 'var(--radius)', boxShadow: 'var(--shadow-card)', marginBottom: '8px', overflow: 'hidden' }}>
                  <div role="button" tabIndex={0} onClick={() => setExpandedId(expanded ? null : it.id)}
                    onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') setExpandedId(expanded ? null : it.id); }}
                    style={{ display: 'flex', alignItems: 'center', gap: '10px', padding: '12px 14px', cursor: 'pointer', flexWrap: 'wrap' }}>
                    <span style={{ fontWeight: 600, color: 'var(--ink)', fontSize: '0.92rem', flex: '1 1 220px' }}>
                      {it.name}
                      {it.vendor && <span style={{ fontWeight: 400, color: 'var(--neutral-500)', marginLeft: '6px' }}>· {it.vendor}</span>}
                      {(eolInfo.end_of_support_date || eolInfo.eol_source) && (
                        <span data-testid={`tech-eol-${it.id}`} style={{ display: 'block', fontWeight: 400, fontSize: '0.75rem', color: 'var(--neutral-500)' }}>
                          EOL {[eolInfo.end_of_support_date ? formatDate(eolInfo.end_of_support_date) : 'date not recorded', eolInfo.eol_source].filter(Boolean).join(' · ')}
                        </span>
                      )}
                    </span>
                    {it.version_edition && <span style={{ fontSize: '0.78rem', color: 'var(--neutral-500)' }}>{it.version_edition}</span>}
                    {it.business_criticality && (
                      <span style={{ fontSize: '0.7rem', color: 'white', background: critColor(it.business_criticality), borderRadius: '10px', padding: '1px 8px', fontWeight: 600, textTransform: 'capitalize' }}>{it.business_criticality}</span>
                    )}
                    {it.lifecycle_state && it.lifecycle_state !== 'unknown' && (
                      <span style={{ fontSize: '0.7rem', color: 'var(--neutral-600)', background: 'var(--neutral-100)', borderRadius: '10px', padding: '1px 8px', textTransform: 'capitalize' }}>{it.lifecycle_state}</span>
                    )}
                    <span style={{ fontSize: '0.7rem', color: v.fg, background: v.bg, borderRadius: '10px', padding: '2px 8px', fontWeight: 600 }}>{v.label}</span>
                  </div>
                  {expanded && (
                    <div style={{ padding: '12px 14px', borderTop: '1px solid var(--divider)', display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(160px, 1fr))', gap: '10px', fontSize: '0.82rem' }}>
                      {([
                        ['Deployment', it.deployment_model], ['Quantity', it.quantity != null ? String(it.quantity) : null],
                        ['Footprint', it.footprint], ['Purpose', it.purpose], ['Support', it.support_state],
                        ['Source', it.source], ['Date observed', it.date_observed], ['Confidence', it.confidence != null ? String(it.confidence) : null],
                      ] as Array<[string, string | null]>).map(([k, val], idx) => (
                        <div key={k + idx}>
                          <div style={{ color: 'var(--neutral-500)', fontSize: '0.7rem', textTransform: 'uppercase', letterSpacing: '0.3px' }}>{k}</div>
                          <div style={{ color: 'var(--ink)', textTransform: 'capitalize' }}>{val || '—'}</div>
                        </div>
                      ))}
                      {it.notes && (
                        <div style={{ gridColumn: '1 / -1' }}>
                          <div style={{ color: 'var(--neutral-500)', fontSize: '0.7rem', textTransform: 'uppercase', letterSpacing: '0.3px' }}>Notes</div>
                          <div style={{ color: 'var(--ink)' }}>{it.notes}</div>
                        </div>
                      )}
                      {canEdit && (
                        <div style={{ gridColumn: '1 / -1', display: 'flex', gap: '10px', marginTop: '4px' }}>
                          <button role="button" aria-label="Edit technology" onClick={() => startEdit(it)}
                            style={{ padding: '6px 14px', background: 'var(--neutral-0)', color: 'var(--brand-700)', border: '1px solid var(--brand-500)', borderRadius: 'var(--radius)', cursor: 'pointer', fontSize: '0.8rem', fontWeight: 600 }}>
                            ✏️ Edit
                          </button>
                          {confirmDeleteId === it.id ? (
                            <button role="button" aria-label="Confirm delete" onClick={() => doDelete(it.id)}
                              style={{ padding: '6px 14px', background: 'var(--status-negative)', color: 'var(--neutral-0)', border: 'none', borderRadius: 'var(--radius)', cursor: 'pointer', fontSize: '0.8rem', fontWeight: 600 }}>
                              Confirm delete?
                            </button>
                          ) : (
                            <button role="button" aria-label="Delete technology" onClick={() => setConfirmDeleteId(it.id)}
                              style={{ padding: '6px 14px', background: 'var(--neutral-0)', color: 'var(--status-negative)', border: '1px solid var(--status-negative)', borderRadius: 'var(--radius)', cursor: 'pointer', fontSize: '0.8rem' }}>
                              🗑️ Delete
                            </button>
                          )}
                        </div>
                      )}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        ))
      )}
    </div>
  );
}
