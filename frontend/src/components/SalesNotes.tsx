import { PromoteTaskButton } from './PromoteTaskButton';
import { useEffect, useMemo, useRef, useState } from 'react';
import { api } from '../lib/api';
import { scopedId, useScopedView } from '../lib/useScopedView';
import {
  SalesNote,
  SALES_NOTE_CATEGORIES,
  VERIFICATION_STATES,
  VerificationState,
} from '../types/sail';

interface Props {
  customerId: number;
  allowWrite?: boolean;
  userRole?: string; // 'owner' | 'member' | 'auditor' | 'none'
}

function verificationColor(state: string): { bg: string; fg: string; label: string } {
  switch (state) {
    case 'verified': return { bg: 'var(--status-positive)', fg: 'white', label: 'Verified' };
    case 'inferred': return { bg: 'var(--status-warning)', fg: '#1f2937', label: 'Inferred' };
    default: return { bg: 'var(--neutral-200)', fg: 'var(--neutral-600)', label: 'Unverified' };
  }
}

// Parse a comma-separated numeric string ("1,2,3") into number[], or null.
function parseIds(s: string | null | undefined): number[] | null {
  if (!s || !s.trim()) return null;
  const out = s.split(',').map((x) => Number(x.trim())).filter((n) => Number.isFinite(n) && n > 0);
  return out.length ? out : null;
}

const emptyForm = (): {
  category: string; title: string; content: string;
  author: string; source: string; note_date: string;
  verification_state: string; related_technology_ids: string; related_use_case_ids: string;
} => ({
  category: '', title: '', content: '', author: '', source: '', note_date: '',
  verification_state: 'verified', related_technology_ids: '', related_use_case_ids: '',
});

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

const NOTE_VIEW_KEYS = ['category', 'id'] as const;

export function SalesNotes({ customerId, allowWrite = false }: Props) {
  const [notes, setNotes] = useState<SalesNote[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [noteView, updateNoteView] = useScopedView(customerId, 'notes', NOTE_VIEW_KEYS);
  const categoryFilter = SALES_NOTE_CATEGORIES.includes(noteView.category as typeof SALES_NOTE_CATEGORIES[number]) ? noteView.category : '';
  const expandedId = scopedId(noteView.id);
  const setExpandedId = (id: number | null) => updateNoteView({ id: id === null ? null : String(id) });
  const [search, setSearch] = useState('');

  const [formOpen, setFormOpen] = useState(false);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [form, setForm] = useState(emptyForm());
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [confirmDeleteId, setConfirmDeleteId] = useState<number | null>(null);

  const customerRef = useRef(customerId);
  customerRef.current = customerId;
  const loadSeq = useRef(0);

  const canEdit = allowWrite;

  const load = async () => {
    if (customerRef.current !== customerId) return;
    const requestedCustomer = customerId;
    const seq = ++loadSeq.current;
    setLoading(true);
    setError(null);
    try {
      const data = await api.listCustomerSalesNotes(customerId);
      if (customerRef.current === requestedCustomer && loadSeq.current === seq) setNotes(data.filter((note) => note.customer_id === requestedCustomer));
    } catch (e: any) {
      if (customerRef.current === requestedCustomer && loadSeq.current === seq) setError(e?.message || 'Failed to load sales notes');
    } finally {
      if (customerRef.current === requestedCustomer && loadSeq.current === seq) setLoading(false);
    }
  };

  useEffect(() => {
    setNotes([]);
    setFormOpen(false);
    load();
    return () => { loadSeq.current += 1; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [customerId]);

  const categoriesInUse = useMemo(
    () => Array.from(new Set(notes.map((n) => n.category))).sort(),
    [notes],
  );

  const filtered = useMemo(() => {
    let out = notes;
    if (categoryFilter) out = out.filter((n) => n.category === categoryFilter);
    if (search.trim()) {
      const q = search.trim().toLowerCase();
      out = out.filter(
        (n) =>
          n.title.toLowerCase().includes(q) ||
          n.content.toLowerCase().includes(q) ||
          (n.author || '').toLowerCase().includes(q),
      );
    }
    // Default sort: note_date desc (newest first); fall back to id desc.
    return [...out].sort((a, b) => {
      const da = a.note_date || '';
      const db = b.note_date || '';
      if (da !== db) return da < db ? 1 : -1;
      return b.id - a.id;
    });
  }, [notes, categoryFilter, search]);

  const summary = useMemo(() => {
    const total = notes.length;
    const latest = notes.reduce<string | null>((acc, n) => (n.note_date && (!acc || n.note_date > acc) ? n.note_date : acc), null);
    const verified = notes.filter((n) => n.verification_state === 'verified').length;
    return { total, latest, verified };
  }, [notes]);

  const startCreate = () => {
    if (!canEdit) return;
    setEditingId(null);
    setForm(emptyForm());
    setSaveError(null);
    setFormOpen(true);
    setExpandedId(null);
  };
  const startEdit = (n: SalesNote) => {
    if (!canEdit) return;
    setEditingId(n.id);
    setForm({
      category: n.category, title: n.title, content: n.content,
      author: n.author || '', source: n.source || '', note_date: n.note_date || '',
      verification_state: n.verification_state,
      related_technology_ids: (n.related_technology_ids || []).join(', '),
      related_use_case_ids: (n.related_use_case_ids || []).join(', '),
    });
    setSaveError(null);
    setFormOpen(true);
    setExpandedId(null);
  };
  const set = <K extends keyof ReturnType<typeof emptyForm>>(k: K, v: ReturnType<typeof emptyForm>[K]) =>
    setForm((f) => ({ ...f, [k]: v }));

  const submit = async () => {
    if (!canEdit) return;
    if (!form.category || !form.title.trim() || !form.content.trim()) {
      setSaveError('Category, title, and content are required.');
      return;
    }
    setSaving(true);
    setSaveError(null);
    const payload = {
      category: form.category,
      title: form.title.trim(),
      content: form.content,
      author: form.author || null,
      source: form.source || null,
      note_date: form.note_date || null,
      verification_state: (form.verification_state || 'verified') as VerificationState,
      related_technology_ids: parseIds(form.related_technology_ids) ?? [],
      related_use_case_ids: parseIds(form.related_use_case_ids) ?? [],
    };
    try {
      if (editingId) {
        await api.updateSalesNote(editingId, payload);
      } else {
        await api.createSalesNote(customerId, payload);
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
      await api.deleteSalesNote(id);
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
          <h2 style={{ margin: 0, fontSize: '1.15rem', color: 'var(--ink)' }}>Sales Notes</h2>
          <div style={{ fontSize: '0.8rem', color: 'var(--neutral-500)' }}>
            Structured discovery, meetings, technical discussions, risks, and competitive intel — preserved verbatim.
          </div>
        </div>
        {canEdit && (
          <button role="button" aria-label="Add sales note" onClick={startCreate}
            style={{ padding: '10px 18px', background: 'var(--brand-500)', color: 'var(--neutral-0)', border: 'none', borderRadius: 'var(--radius)', cursor: 'pointer', fontSize: '0.9rem', fontWeight: 600 }}>
            ➕ Add Note
          </button>
        )}
      </div>

      {/* Summary */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(160px, 1fr))', gap: '12px', marginBottom: '16px' }}>
        {[
          { label: 'Total Notes', value: summary.total, color: 'var(--ink)' },
          { label: 'Verified', value: summary.verified, color: 'var(--status-positive)' },
          { label: 'Latest Note', value: summary.latest || '—', color: 'var(--brand-700)', small: true },
        ].map((c) => (
          <div key={c.label} style={{ background: 'var(--neutral-0)', borderRadius: 'var(--radius)', padding: '12px 14px', boxShadow: 'var(--shadow-card)' }}>
            <div style={{ fontSize: '0.72rem', color: 'var(--neutral-500)' }}>{c.label}</div>
            <div style={{ fontSize: c.small ? '1.05rem' : '1.6rem', fontWeight: 'bold', color: c.color }}>{c.value}</div>
          </div>
        ))}
      </div>

      {/* Filters */}
      <div style={{ display: 'flex', gap: '10px', flexWrap: 'wrap', marginBottom: '16px', alignItems: 'center' }}>
        <select aria-label="Filter by note category" value={categoryFilter} onChange={(e) => updateNoteView({ category: e.target.value || null, id: null })} style={{ ...inputStyle, minWidth: '180px' }}>
          <option value="">All categories</option>
          {categoryFilter && !categoriesInUse.includes(categoryFilter) && <option value={categoryFilter}>{categoryFilter} (no notes)</option>}
          {categoriesInUse.map((c) => (<option key={c} value={c}>{c}</option>))}
        </select>
        <input aria-label="Search notes" placeholder="Search title / content / author…" value={search} onChange={(e) => setSearch(e.target.value)} style={{ ...inputStyle, minWidth: '240px', flex: '1 1 240px' }} />
      </div>

      <p style={{ fontSize: '0.75rem', color: 'var(--neutral-500)' }}>Search text is cleared on refresh.</p>
      {!loading && !error && expandedId !== null && !notes.some((note) => note.id === expandedId) && <p role="alert">Note not found or unavailable.</p>}

      {error && (
        <div style={{ padding: '10px 14px', background: 'rgba(220,53,69,0.1)', color: 'var(--status-negative)', borderRadius: 'var(--radius)', marginBottom: '12px', fontSize: '0.85rem' }}>
          {error}
        </div>
      )}

      {/* Create / Edit form */}
      {formOpen && canEdit && (
        <div style={{ background: 'var(--neutral-0)', borderRadius: 'var(--radius)', padding: '16px', boxShadow: 'var(--shadow-card)', marginBottom: '16px' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '12px' }}>
            <h3 style={{ margin: 0, fontSize: '1rem' }}>{editingId ? 'Edit Note' : 'Add Note'}</h3>
            <button role="button" aria-label="Close form" onClick={() => setFormOpen(false)} style={{ background: 'none', border: 'none', cursor: 'pointer', fontSize: '1rem' }}>✕</button>
          </div>
          {saveError && (
            <div style={{ padding: '8px 12px', background: 'rgba(220,53,69,0.1)', color: 'var(--status-negative)', borderRadius: 'var(--radius)', marginBottom: '12px', fontSize: '0.85rem' }}>{saveError}</div>
          )}
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: '12px' }}>
            <Field label="Category *">
              <select style={inputStyle} value={form.category} onChange={(e) => set('category', e.target.value)}>
                <option value="">Select…</option>
                {SALES_NOTE_CATEGORIES.map((c) => (<option key={c} value={c}>{c}</option>))}
              </select>
            </Field>
            <Field label="Title *"><input style={inputStyle} value={form.title} onChange={(e) => set('title', e.target.value)} /></Field>
            <Field label="Author"><input style={inputStyle} value={form.author} onChange={(e) => set('author', e.target.value)} /></Field>
            <Field label="Source"><input style={inputStyle} placeholder="e.g. discovery call, meeting" value={form.source} onChange={(e) => set('source', e.target.value)} /></Field>
            <Field label="Note date"><input type="date" style={inputStyle} value={form.note_date} onChange={(e) => set('note_date', e.target.value)} /></Field>
            <Field label="Verification State">
              <select style={inputStyle} value={form.verification_state} onChange={(e) => set('verification_state', e.target.value)}>
                {VERIFICATION_STATES.map((v) => (<option key={v} value={v}>{v}</option>))}
              </select>
            </Field>
            <Field label="Related technology ids (comma-sep.)"><input style={inputStyle} placeholder="e.g. 1, 2" value={form.related_technology_ids} onChange={(e) => set('related_technology_ids', e.target.value)} /></Field>
            <Field label="Related use case ids (comma-sep.)"><input style={inputStyle} placeholder="e.g. 3, 4" value={form.related_use_case_ids} onChange={(e) => set('related_use_case_ids', e.target.value)} /></Field>
          </div>
          <div style={{ marginTop: '12px' }}>
            <Field label="Content *"><textarea rows={3} style={inputStyle} value={form.content} onChange={(e) => set('content', e.target.value)} /></Field>
          </div>
          <div style={{ display: 'flex', gap: '10px', marginTop: '14px' }}>
            <button role="button" aria-label="Save note" disabled={saving} onClick={submit}
              style={{ padding: '10px 18px', background: saving ? 'var(--neutral-300)' : 'var(--brand-500)', color: saving ? 'var(--neutral-700)' : 'var(--neutral-0)', border: 'none', borderRadius: 'var(--radius)', cursor: saving ? 'not-allowed' : 'pointer', fontSize: '0.9rem', fontWeight: 600 }}>
              {saving ? 'Saving…' : editingId ? 'Save Changes' : 'Add Note'}
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
      ) : filtered.length === 0 ? (
        <div style={{ padding: '24px', textAlign: 'center', color: 'var(--neutral-500)', background: 'var(--neutral-0)', borderRadius: 'var(--radius)' }}>
          {notes.length === 0 ? 'No sales notes recorded yet.' : 'No notes match the current filters.'}
        </div>
      ) : (
        filtered.map((n) => {
          const v = verificationColor(n.verification_state);
          const expanded = expandedId === n.id;
          return (
            <div key={n.id} style={{ background: 'var(--neutral-0)', borderRadius: 'var(--radius)', boxShadow: 'var(--shadow-card)', marginBottom: '8px', overflow: 'hidden' }}>
              <div role="button" aria-expanded={expanded} tabIndex={0} onClick={() => setExpandedId(expanded ? null : n.id)}
                onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') setExpandedId(expanded ? null : n.id); }}
                style={{ display: 'flex', alignItems: 'center', gap: '10px', padding: '12px 14px', cursor: 'pointer', flexWrap: 'wrap' }}>
                <span style={{ fontSize: '0.7rem', color: 'var(--neutral-0)', background: 'var(--brand-500)', borderRadius: '10px', padding: '2px 8px', fontWeight: 600, textTransform: 'capitalize' }}>{n.category}</span>
                <span style={{ fontWeight: 600, color: 'var(--ink)', fontSize: '0.92rem', flex: '1 1 200px' }}>{n.title}</span>
                {n.author && <span style={{ fontSize: '0.78rem', color: 'var(--neutral-500)' }}>{n.author}</span>}
                {n.note_date && <span style={{ fontSize: '0.78rem', color: 'var(--neutral-500)' }}>{n.note_date}</span>}
                <span style={{ fontSize: '0.7rem', color: v.fg, background: v.bg, borderRadius: '10px', padding: '2px 8px', fontWeight: 600 }}>{v.label}</span>
              </div>
              {expanded && (
                <div style={{ padding: '12px 14px', borderTop: '1px solid var(--divider)', fontSize: '0.85rem' }}>
                  <div style={{ color: 'var(--ink)', whiteSpace: 'pre-wrap', marginBottom: '10px' }}>{n.content}</div>
                  <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(160px, 1fr))', gap: '10px', fontSize: '0.8rem' }}>
                    {([
                      ['Source', n.source],
                      ['Related technologies', (n.related_technology_ids || []).join(', ') || '—'],
                      ['Related use cases', (n.related_use_case_ids || []).join(', ') || '—'],
                    ] as Array<[string, string | null]>).map(([k, val]) => (
                      <div key={k}>
                        <div style={{ color: 'var(--neutral-500)', fontSize: '0.7rem', textTransform: 'uppercase', letterSpacing: '0.3px' }}>{k}</div>
                        <div style={{ color: 'var(--ink)' }}>{val || '—'}</div>
                      </div>
                    ))}
                  </div>
                  {canEdit && (
                    <div style={{ display: 'flex', gap: '10px', marginTop: '12px' }}>
                      <button role="button" aria-label="Edit note" onClick={() => startEdit(n)}
                        style={{ padding: '6px 14px', background: 'var(--neutral-0)', color: 'var(--brand-700)', border: '1px solid var(--brand-500)', borderRadius: 'var(--radius)', cursor: 'pointer', fontSize: '0.8rem', fontWeight: 600 }}>
                        ✏️ Edit
                      </button>
                      <PromoteTaskButton customerId={customerId} sourceType="note" sourceId={n.id} label="note" />
                      {confirmDeleteId === n.id ? (
                        <button role="button" aria-label="Confirm delete" onClick={() => doDelete(n.id)}
                          style={{ padding: '6px 14px', background: 'var(--status-negative)', color: 'var(--neutral-0)', border: 'none', borderRadius: 'var(--radius)', cursor: 'pointer', fontSize: '0.8rem', fontWeight: 600 }}>
                          Confirm delete?
                        </button>
                      ) : (
                        <button role="button" aria-label="Delete note" onClick={() => setConfirmDeleteId(n.id)}
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
        })
      )}
    </div>
  );
}
