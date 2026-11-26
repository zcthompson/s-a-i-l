/**
 * E3 — SavedViewsMenu: the caller's named portfolio filter views (self-contained).
 *
 * A view persists ONLY the H2 filter description (PORTFOLIO_FILTER_PARAMS); it
 * is re-evaluated against the caller's CURRENT scope on every load (the parent
 * applies it through its existing URL-state setter). The list is fetched lazily
 * when the menu is opened, so surfaces that never open it make no request.
 *
 * Response shapes: the backend contract is GET → {views: [...]} and
 * POST → {view, created}. The bare-array / bare-view shapes are tolerated too
 * (the client typings in lib/api.ts declare those) — see normalizeList/Saved.
 */
import { useCallback, useState } from 'react';
import type { CSSProperties } from 'react';
import { api } from '../lib/api';
import type { SavedView } from '../types/savedViews';

export type SavedViewParams = Record<string, string | null>;

export interface SavedViewsMenuProps {
  surface: string;
  customerId?: number;
  /** The CURRENT filter params, sent verbatim on save. */
  currentParams: SavedViewParams;
  /** Receives the stored params of the chosen view, verbatim. */
  onApply: (params: SavedViewParams) => void;
  disabled?: boolean;
}

export const NAME_MAX = 100;

export function normalizeViewList(raw: unknown): SavedView[] {
  if (Array.isArray(raw)) return raw as SavedView[];
  const views = (raw as { views?: unknown } | null)?.views;
  if (Array.isArray(views)) return views as SavedView[];
  throw new Error('Unexpected saved views response');
}

/** `created` from the {view, created} envelope; null when the response does not say. */
export function savedCreatedFlag(raw: unknown): boolean | null {
  const created = (raw as { created?: unknown } | null)?.created;
  return typeof created === 'boolean' ? created : null;
}

const btn: CSSProperties = {
  padding: '3px 10px', fontSize: '0.8rem', color: 'var(--neutral-700)', background: 'var(--neutral-0)',
  border: '1px solid var(--divider)', borderRadius: 'var(--radius-sm)', cursor: 'pointer',
};
const muted: CSSProperties = { fontSize: '0.8rem', color: 'var(--neutral-500)' };

export function SavedViewsMenu({ surface, currentParams, onApply, disabled, customerId }: SavedViewsMenuProps) {
  const [open, setOpen] = useState(false);
  const [views, setViews] = useState<SavedView[] | null>(null);
  const [loadError, setLoadError] = useState(false);
  const [saving, setSaving] = useState(false);
  const [naming, setNaming] = useState(false);
  const [name, setName] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [feedback, setFeedback] = useState<string | null>(null);

  const load = useCallback(() => {
    setLoadError(false);
    return Promise.resolve()
      .then(() => customerId ? api.listSavedViews(surface, customerId) : api.listSavedViews(surface))
      .then(raw => setViews(normalizeViewList(raw)))
      .catch(() => { setViews(null); setLoadError(true); });
  }, [surface, customerId]);

  const toggle = () => {
    const next = !open;
    setOpen(next);
    if (next) {
      setFeedback(null);
      setError(null);
      setViews(null);
      void load();
    }
  };

  const trimmed = name.trim();
  const nameValid = trimmed.length >= 1 && trimmed.length <= NAME_MAX;

  const save = () => {
    if (!nameValid || saving) return;
    setSaving(true);
    setError(null);
    setFeedback(null);
    Promise.resolve()
      .then(() => api.saveView(surface, trimmed, currentParams))
      .then(raw => {
        // Only an explicit created:false is "updated"; never claim an update we cannot see.
        setFeedback(savedCreatedFlag(raw) === false ? 'View updated.' : 'View saved.');
        setNaming(false);
        setName('');
        return load();
      })
      .catch((e: unknown) => setError(e instanceof Error && e.message ? e.message : 'Saving the view failed.'))
      .finally(() => setSaving(false));
  };

  const remove = (view: SavedView) => {
    if (!window.confirm(`Delete saved view "${view.name}"? This cannot be undone.`)) return;
    setError(null);
    setFeedback(null);
    Promise.resolve()
      .then(() => api.deleteSavedView(view.id))
      .then(() => { setFeedback('View deleted.'); return load(); })
      .catch((e: unknown) => setError(e instanceof Error && e.message ? e.message : 'Deleting the view failed.'));
  };

  const apply = (view: SavedView) => {
    onApply(view.params);
    setOpen(false);
  };

  return (
    <div data-testid="saved-views" style={{ position: 'relative', display: 'inline-block' }}>
      <button type="button" aria-expanded={open} aria-haspopup="true" aria-label="Saved views" disabled={disabled} onClick={toggle} style={btn}>
        Views {open ? '▴' : '▾'}
      </button>
      {open && (
        <div
          data-testid="saved-views-panel"
          style={{
            position: 'absolute', right: customerId ? undefined : 0, left: customerId ? 0 : undefined, top: 'calc(100% + 4px)', zIndex: 20, width: '280px', maxWidth: 'calc(100vw - 32px)',
            boxSizing: 'border-box', padding: '10px', background: 'var(--neutral-0)', border: '1px solid var(--divider)',
            borderRadius: 'var(--radius)', boxShadow: 'var(--shadow-card)', display: 'flex', flexDirection: 'column', gap: '8px',
          }}
        >
          {loadError ? (
            <div role="alert" data-testid="saved-views-error" style={{ ...muted, color: 'var(--status-negative)' }}>
              Views unavailable. Try again.{' '}
              <button type="button" onClick={() => void load()} style={btn}>Retry</button>
            </div>
          ) : views === null ? (
            <div style={muted}>Loading views…</div>
          ) : views.length === 0 ? (
            <div data-testid="saved-views-empty" style={muted}>No saved views yet.</div>
          ) : (
            <ul aria-label="Saved views list" style={{ listStyle: 'none', margin: 0, padding: 0, display: 'flex', flexDirection: 'column', gap: '4px' }}>
              {views.map(v => (
                <li key={v.id} data-testid={`saved-view-${v.id}`} style={{ display: 'flex', gap: '6px', alignItems: 'center', minWidth: 0 }}>
                  <button
                    type="button"
                    aria-label={`Apply view ${v.name}`}
                    onClick={() => apply(v)}
                    style={{ ...btn, flex: 1, minWidth: 0, textAlign: 'left', overflowWrap: 'anywhere', border: '1px solid transparent' }}
                  >
                    {v.name}
                  </button>
                  <button type="button" aria-label={`Delete view ${v.name}`} title="Delete view" onClick={() => remove(v)} style={{ ...btn, padding: '1px 7px', color: 'var(--status-negative)' }}>
                    ×
                  </button>
                </li>
              ))}
            </ul>
          )}
          {naming ? (
            <form
              onSubmit={e => { e.preventDefault(); save(); }}
              style={{ display: 'flex', gap: '6px', flexWrap: 'wrap', alignItems: 'center' }}
            >
              <input
                type="text"
                aria-label="View name"
                placeholder="View name"
                value={name}
                maxLength={NAME_MAX}
                autoFocus
                onChange={e => setName(e.target.value)}
                style={{ ...btn, cursor: 'text', flex: '1 1 140px', minWidth: 0 }}
              />
              <button type="submit" disabled={!nameValid || saving} style={btn}>{saving ? 'Saving…' : 'Save'}</button>
              <button type="button" onClick={() => { setNaming(false); setName(''); setError(null); }} style={btn}>Cancel</button>
            </form>
          ) : (
            <button type="button" onClick={() => { setNaming(true); setFeedback(null); setError(null); }} style={{ ...btn, alignSelf: 'flex-start' }}>
              Save current
            </button>
          )}
          {error && <div role="alert" data-testid="saved-views-action-error" style={{ ...muted, color: 'var(--status-negative)', overflowWrap: 'anywhere' }}>{error}</div>}
          <div role="status" aria-live="polite" data-testid="saved-views-feedback" style={muted}>{feedback ?? ''}</div>
        </div>
      )}
    </div>
  );
}

export default SavedViewsMenu;
