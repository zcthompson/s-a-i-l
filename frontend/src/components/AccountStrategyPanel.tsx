/**
 * H7 — Account Strategy panel (Sales → Account Strategy).
 *
 * Plan (five text fields, saved with expected_version), read-only Suggestions
 * computed from recorded evidence, linked next actions/contacts/notes, and
 * immutable published snapshots. Contract S0 honesty rules: the server never
 * applies suggestions; the FE prefills only EMPTY draft fields (lib/strategy.ts)
 * and marks them "suggested" until edited. Backend error strings (409/422/403)
 * render verbatim. Write affordances follow the panel `userRole` convention
 * (ContactsPanel); the backend 403 stays authoritative if it disagrees.
 */
import { useEffect, useState } from 'react';
import { api } from '../lib/api';
import { prefillStrategy } from '../lib/strategy';
import type { Task } from '../types/engagement';
import {
  STRATEGY_FIELDS,
  STRATEGY_FIELD_LABELS,
  type StrategyField,
  type StrategyFieldValues,
  type StrategyLinksUpdate,
  type StrategyPlan,
  type StrategySnapshot,
  type StrategySnapshotSummary,
  type StrategyView,
} from '../types/strategy';

interface Props {
  customerId: number;
  userRole?: string; // 'owner' | 'member' | 'auditor' | 'none'
}

type Draft = Record<StrategyField, string>;

const OPEN_TASK_STATUSES = ['open', 'in_progress'];

const sectionStyle: React.CSSProperties = {
  background: 'var(--neutral-0)', borderRadius: 'var(--radius)', boxShadow: 'var(--shadow-card)',
  padding: '14px 16px', display: 'flex', flexDirection: 'column', gap: '10px',
};
const sectionTitle: React.CSSProperties = { margin: 0, fontSize: '0.95rem', color: 'var(--neutral-700)' };
const textareaStyle: React.CSSProperties = {
  padding: '8px', border: '1px solid var(--divider)', borderRadius: 'var(--radius)', fontSize: '0.85rem',
  background: 'var(--neutral-0)', color: 'var(--ink)', minHeight: '60px', resize: 'vertical', fontFamily: 'inherit',
};
const inputStyle: React.CSSProperties = {
  padding: '6px 8px', border: '1px solid var(--divider)', borderRadius: 'var(--radius)', fontSize: '0.85rem', background: 'var(--neutral-0)', color: 'var(--ink)',
};
const btn: React.CSSProperties = {
  padding: '6px 14px', background: 'var(--neutral-0)', color: 'var(--brand-700)', border: '1px solid var(--brand-500)',
  borderRadius: 'var(--radius)', cursor: 'pointer', fontSize: '0.8rem', fontWeight: 600,
};
const chip: React.CSSProperties = {
  fontSize: '0.7rem', color: 'var(--neutral-0)', background: 'var(--brand-500)', borderRadius: '10px', padding: '2px 8px', fontWeight: 600,
};
const muted: React.CSSProperties = { fontSize: '0.8rem', color: 'var(--neutral-500)' };
const errorStyle: React.CSSProperties = { fontSize: '0.85rem', color: 'var(--danger, #b91c1c)' };

/** Field testids use kebab-case (contract C4: -field-discovery-gaps). */
const kebab = (f: string) => f.replace(/_/g, '-');

const messageOf = (e: unknown, fallback: string): string => (e as Error)?.message || fallback;

function recordedOf(plan: StrategyPlan | null): Record<StrategyField, string | null> {
  const out = {} as Record<StrategyField, string | null>;
  for (const f of STRATEGY_FIELDS) out[f] = plan?.[f] ?? null;
  return out;
}

function textOf(values: Record<StrategyField, string | null>): Draft {
  const out = {} as Draft;
  for (const f of STRATEGY_FIELDS) out[f] = values[f] ?? '';
  return out;
}

/** Blank text is sent as null (= not recorded / cleared), never as "". */
const toRecorded = (text: string): string | null => (text.trim() === '' ? null : text);

function payloadOf(draft: Draft): StrategyFieldValues {
  const out = {} as StrategyFieldValues;
  for (const f of STRATEGY_FIELDS) out[f] = toRecorded(draft[f]);
  return out;
}

/** Initial draft: read-only viewers see only the recorded text (no prefill). */
function initialDraft(view: StrategyView, canEdit: boolean): { draft: Draft; suggested: StrategyField[] } {
  const recorded = recordedOf(view.plan);
  if (!canEdit) return { draft: textOf(recorded), suggested: [] };
  const { fields, prefilled } = prefillStrategy(recorded, view.suggestions);
  return { draft: fields, suggested: prefilled };
}

export function AccountStrategyPanel({ customerId, userRole }: Props) {
  const canEdit = userRole !== 'auditor' && userRole !== 'none';

  const [view, setView] = useState<StrategyView | null>(null);
  const [snapshots, setSnapshots] = useState<StrategySnapshotSummary[]>([]);
  const [tasks, setTasks] = useState<Task[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [draft, setDraft] = useState<Draft>({ objectives: '', desired_outcomes: '', risks: '', plays: '', discovery_gaps: '' });
  const [suggested, setSuggested] = useState<StrategyField[]>([]);
  const [saving, setSaving] = useState(false);

  const [linking, setLinking] = useState(false);

  const [snapshotNote, setSnapshotNote] = useState('');
  const [publishing, setPublishing] = useState(false);
  const [openSnapshot, setOpenSnapshot] = useState<StrategySnapshot | null>(null);

  // Re-read the GET + snapshot list after a write. Never touches the draft, so
  // unsaved edits survive a link/publish round-trip.
  const refresh = async () => {
    const [v, list] = await Promise.all([
      api.getAccountStrategy(customerId),
      api.listStrategySnapshots(customerId),
    ]);
    setView(v);
    setSnapshots(Array.isArray(list?.snapshots) ? list.snapshots : []);
  };

  useEffect(() => {
    let alive = true;
    setView(null);
    setSnapshots([]);
    setTasks([]);
    setError(null);
    setOpenSnapshot(null);
    setSnapshotNote('');
    setLoading(true);
    Promise.all([
      api.getAccountStrategy(customerId),
      api.listStrategySnapshots(customerId),
      canEdit ? api.listTasks(customerId) : Promise.resolve([] as Task[]),
    ])
      .then(([v, list, taskList]) => {
        if (!alive) return;
        setView(v);
        setSnapshots(Array.isArray(list?.snapshots) ? list.snapshots : []);
        setTasks(Array.isArray(taskList) ? taskList : []);
        const next = initialDraft(v, canEdit);
        setDraft(next.draft);
        setSuggested(next.suggested);
      })
      .catch((e) => { if (alive) setError(messageOf(e, 'Failed to load account strategy')); })
      .finally(() => { if (alive) setLoading(false); });
    return () => { alive = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [customerId]);

  const setField = (f: StrategyField, text: string) => {
    setDraft((d) => ({ ...d, [f]: text }));
    setSuggested((s) => s.filter((x) => x !== f));
  };

  const save = async () => {
    if (!view) return;
    setSaving(true);
    setError(null);
    try {
      await api.updateAccountStrategy(customerId, { ...payloadOf(draft), expected_version: view.plan?.version ?? 0 });
      setSuggested([]);
      await refresh();
    } catch (e) {
      setError(messageOf(e, 'Save failed'));
    } finally {
      setSaving(false);
    }
  };

  const links = view?.plan?.links;
  const linkedTasks = links?.tasks ?? [];
  const linkedContacts = links?.contacts ?? [];
  const linkedNotes = links?.notes ?? [];
  const linkedTaskIds = linkedTasks.map((t) => t.task_id);

  const writeLinks = async (next: StrategyLinksUpdate) => {
    setLinking(true);
    setError(null);
    try {
      await api.updateStrategyLinks(customerId, next);
      await refresh();
    } catch (e) {
      setError(messageOf(e, 'Link update failed'));
    } finally {
      setLinking(false);
    }
  };

  const currentLinks = (): StrategyLinksUpdate => ({
    task_ids: linkedTasks.map((t) => t.task_id),
    contact_ids: linkedContacts.map((c) => c.contact_id),
    note_ids: linkedNotes.map((n) => n.note_id),
  });

  const toggleTask = (taskId: number, on: boolean) => {
    const cur = currentLinks();
    writeLinks({
      ...cur,
      task_ids: on ? [...cur.task_ids, taskId] : cur.task_ids.filter((id) => id !== taskId),
    });
  };

  const unlinkContact = (contactId: number) => {
    const cur = currentLinks();
    writeLinks({ ...cur, contact_ids: cur.contact_ids.filter((id) => id !== contactId) });
  };

  const unlinkNote = (noteId: number) => {
    const cur = currentLinks();
    writeLinks({ ...cur, note_ids: cur.note_ids.filter((id) => id !== noteId) });
  };

  // Checkbox candidates: open/in_progress tasks, plus linked tasks that have
  // since closed (so they can still be unlinked).
  const openTaskRows = tasks
    .filter((t) => OPEN_TASK_STATUSES.includes(t.status))
    .map((t) => ({ id: t.id, title: t.title, status: t.status, due: t.due_date ?? t.due_at ?? null }));
  const taskRows = [
    ...openTaskRows,
    ...linkedTasks
      .filter((t) => !openTaskRows.some((r) => r.id === t.task_id))
      .map((t) => ({ id: t.task_id, title: t.title, status: t.status, due: null as string | null })),
  ];

  const publish = async () => {
    setPublishing(true);
    setError(null);
    try {
      const note = snapshotNote.trim();
      await api.publishStrategySnapshot(customerId, note ? { note } : {});
      setSnapshotNote('');
      await refresh();
    } catch (e) {
      setError(messageOf(e, 'Publish failed'));
    } finally {
      setPublishing(false);
    }
  };

  const toggleView = async (s: StrategySnapshotSummary) => {
    if (openSnapshot?.plan_number === s.plan_number) {
      setOpenSnapshot(null);
      return;
    }
    setError(null);
    try {
      setOpenSnapshot(await api.getStrategySnapshot(s.id));
    } catch (e) {
      setError(messageOf(e, 'Failed to load snapshot'));
    }
  };

  const restore = async (s: StrategySnapshotSummary) => {
    if (!window.confirm(`Restore strategy #${s.plan_number} into the draft? Fields not recorded in that snapshot will be cleared.`)) return;
    setError(null);
    try {
      const plan = await api.restoreStrategySnapshot(s.id, view?.plan?.version ?? 0);
      setDraft(textOf(recordedOf(plan)));
      setSuggested([]);
      await refresh();
    } catch (e) {
      setError(messageOf(e, 'Restore failed'));
    }
  };

  return (
    <div data-testid="account-strategy-panel" style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
      <h3 style={{ margin: 0 }}>Account Strategy</h3>

      {error && (
        <div role="status" data-testid="account-strategy-error" style={errorStyle}>{error}</div>
      )}

      {loading && <div style={muted}>Loading account strategy…</div>}

      {view && (
        <>
          <section data-testid="account-strategy-plan" style={sectionStyle}>
            <h4 style={sectionTitle}>Plan</h4>
            {view.plan ? (
              <div style={muted}>
                Version {view.plan.version} · updated {view.plan.updated_at ?? '—'} by {view.plan.updated_by ?? '—'}
              </div>
            ) : (
              <div data-testid="account-strategy-empty" style={muted}>
                No strategy recorded yet.{canEdit ? ' Fields start empty; suggestions below may prefill them for review.' : ''}
              </div>
            )}

            {STRATEGY_FIELDS.map((f) => (
              <div key={f} style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                  <label htmlFor={`account-strategy-input-${kebab(f)}`} style={{ fontSize: '0.8rem', color: 'var(--neutral-600)' }}>
                    {STRATEGY_FIELD_LABELS[f]}
                  </label>
                  {suggested.includes(f) && (
                    <span data-testid={`account-strategy-suggested-${kebab(f)}`} style={chip}>suggested</span>
                  )}
                </div>
                <textarea
                  id={`account-strategy-input-${kebab(f)}`}
                  data-testid={`account-strategy-field-${kebab(f)}`}
                  value={draft[f]}
                  readOnly={!canEdit}
                  onChange={(e) => setField(f, e.target.value)}
                  style={textareaStyle}
                />
              </div>
            ))}

            {canEdit && (
              <div>
                <button type="button" data-testid="account-strategy-save" style={btn} disabled={saving} onClick={save}>
                  {saving ? 'Saving…' : 'Save plan'}
                </button>
              </div>
            )}
          </section>

          <section data-testid="account-strategy-suggestions" style={sectionStyle}>
            <h4 style={sectionTitle}>Suggestions</h4>
            <div style={muted}>Derived from recorded evidence — for review. Nothing is applied automatically.</div>
            {STRATEGY_FIELDS.map((f) => {
              const items = view.suggestions[f] ?? [];
              return (
                <div key={f} data-testid={`account-strategy-suggestion-${kebab(f)}`} style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
                  <div style={{ fontSize: '0.8rem', fontWeight: 600, color: 'var(--neutral-700)' }}>{STRATEGY_FIELD_LABELS[f]}</div>
                  {items.length === 0 ? (
                    <div style={muted}>No suggestion from recorded evidence.</div>
                  ) : (
                    <ul style={{ margin: 0, paddingLeft: '18px', fontSize: '0.85rem', display: 'flex', flexDirection: 'column', gap: '4px' }}>
                      {items.map((s, i) => (
                        <li key={i}>
                          {s.text} <span style={muted}>— source: {s.source}</span>
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
              );
            })}
          </section>

          <section data-testid="account-strategy-links" style={sectionStyle}>
            <h4 style={sectionTitle}>Linked next actions</h4>
            {!view.plan && <div style={muted}>Save a plan to link next actions, contacts, or notes.</div>}

            {view.plan && canEdit && (
              taskRows.length === 0 ? (
                <div style={muted}>No open tasks recorded for this account.</div>
              ) : (
                taskRows.map((row) => (
                  <label key={row.id} style={{ display: 'flex', alignItems: 'center', gap: '8px', fontSize: '0.85rem' }}>
                    <input
                      type="checkbox"
                      data-testid={`account-strategy-link-task-${row.id}`}
                      checked={linkedTaskIds.includes(row.id)}
                      disabled={linking}
                      onChange={(e) => toggleTask(row.id, e.target.checked)}
                    />
                    <span>{row.title}</span>
                    <span style={muted}>{row.status}{row.due ? ` · due ${row.due}` : ''}</span>
                  </label>
                ))
              )
            )}
            {view.plan && !canEdit && (
              linkedTasks.length === 0 ? (
                <div style={muted}>No next actions linked.</div>
              ) : (
                linkedTasks.map((t) => (
                  <div key={t.task_id} style={{ fontSize: '0.85rem' }}>
                    {t.title} <span style={muted}>{t.status}</span>
                  </div>
                ))
              )
            )}

            <div style={{ fontSize: '0.8rem', fontWeight: 600, color: 'var(--neutral-700)' }}>Linked contacts</div>
            {linkedContacts.length === 0 ? (
              <div style={muted}>No contacts linked.</div>
            ) : (
              linkedContacts.map((c) => (
                <div key={c.contact_id} style={{ display: 'flex', alignItems: 'center', gap: '8px', fontSize: '0.85rem' }}>
                  <span>{c.display_name}</span>
                  {canEdit && (
                    <button
                      type="button"
                      data-testid={`account-strategy-unlink-contact-${c.contact_id}`}
                      style={btn}
                      disabled={linking}
                      onClick={() => unlinkContact(c.contact_id)}
                    >
                      Unlink
                    </button>
                  )}
                </div>
              ))
            )}

            <div style={{ fontSize: '0.8rem', fontWeight: 600, color: 'var(--neutral-700)' }}>Linked notes</div>
            {linkedNotes.length === 0 ? (
              <div style={muted}>No notes linked.</div>
            ) : (
              linkedNotes.map((n) => (
                <div key={n.note_id} style={{ display: 'flex', alignItems: 'center', gap: '8px', fontSize: '0.85rem' }}>
                  <span>{n.title ?? '(no title)'}</span>
                  {canEdit && (
                    <button
                      type="button"
                      data-testid={`account-strategy-unlink-note-${n.note_id}`}
                      style={btn}
                      disabled={linking}
                      onClick={() => unlinkNote(n.note_id)}
                    >
                      Unlink
                    </button>
                  )}
                </div>
              ))
            )}
          </section>

          <section data-testid="account-strategy-snapshots" style={sectionStyle}>
            <h4 style={sectionTitle}>Snapshots</h4>
            {canEdit && (
              <div style={{ display: 'flex', gap: '8px', alignItems: 'center', flexWrap: 'wrap' }}>
                <input
                  type="text"
                  data-testid="account-strategy-snapshot-note"
                  placeholder="Note (optional)"
                  value={snapshotNote}
                  onChange={(e) => setSnapshotNote(e.target.value)}
                  style={{ ...inputStyle, minWidth: '240px' }}
                />
                <button type="button" data-testid="account-strategy-snapshot-publish" style={btn} disabled={publishing} onClick={publish}>
                  {publishing ? 'Publishing…' : 'Publish snapshot'}
                </button>
              </div>
            )}

            {snapshots.length === 0 ? (
              <div style={muted}>No snapshots published yet.</div>
            ) : (
              <div data-testid="account-strategy-snapshot-list" style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                {snapshots.map((s) => (
                  <div key={s.id} data-testid={`account-strategy-snapshot-${s.plan_number}`} style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '10px', flexWrap: 'wrap', fontSize: '0.85rem' }}>
                      <strong>Plan #{s.plan_number}</strong>
                      <span>{s.note ?? '—'}</span>
                      <span style={muted}>published by {s.published_by ?? '—'} at {s.published_at ?? '—'}</span>
                      <button type="button" data-testid={`account-strategy-view-${s.plan_number}`} style={btn} onClick={() => toggleView(s)}>
                        {openSnapshot?.plan_number === s.plan_number ? 'Hide' : 'View'}
                      </button>
                      {canEdit && (
                        <button type="button" data-testid={`account-strategy-restore-${s.plan_number}`} style={btn} onClick={() => restore(s)}>
                          Restore
                        </button>
                      )}
                    </div>
                    {openSnapshot?.plan_number === s.plan_number && (
                      <div data-testid={`account-strategy-view-content-${s.plan_number}`} style={{ display: 'flex', flexDirection: 'column', gap: '6px', fontSize: '0.85rem', paddingLeft: '12px', borderLeft: '2px solid var(--divider)' }}>
                        {STRATEGY_FIELDS.map((f) => (
                          <div key={f}>
                            <div style={{ fontSize: '0.8rem', color: 'var(--neutral-600)' }}>{STRATEGY_FIELD_LABELS[f]}</div>
                            <div style={{ whiteSpace: 'pre-wrap' }}>{openSnapshot.content[f] ?? 'not recorded'}</div>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                ))}
              </div>
            )}
          </section>
        </>
      )}
    </div>
  );
}
