/**
 * CustomerAliasesField — the "Aliases" section of the Edit customer dialog
 * (aliases are edited under Edit Customer,
 * below Description and Vertical — not a card on the Overview).
 *
 * Alias chips (raw alias; created_by/created_at as the chip title + a small
 * secondary line) and — only when `canManage` — an add input + per-chip
 * remove, so several aliases can be attached in one sitting. Each add/remove
 * saves immediately through the alias API (the server's 422/409 messages
 * render verbatim inline, per alias) and re-fetches the list; the dialog's
 * Save button covers only description/vertical. Fetches its own list per
 * customer (the customer payload's raw-string list carries no id/created_by/
 * created_at). The backend is the authorization boundary; `canManage`
 * defaults to false (fail-closed: read-only chips). Writers per the backend
 * gate: owner, sales admin, or admin.
 */
import { useCallback, useEffect, useState } from 'react';
import type { CSSProperties } from 'react';
import { api } from '../lib/api';
import type { CustomerAlias } from '../types/use_case';

interface CustomerAliasesFieldProps {
  customerName: string;
  canManage?: boolean;
  /** Called with the raw alias strings (sorted) after each add/remove. */
  onChange?: (aliases: string[]) => void;
}

const chipStyle: CSSProperties = {
  display: 'inline-flex', alignItems: 'center', gap: '6px', padding: '4px 10px',
  background: 'var(--neutral-50)', border: '1px solid var(--divider)', borderRadius: '999px',
  fontSize: '0.82rem', color: 'var(--ink)',
};

const provenance = (a: CustomerAlias) => {
  const by = a.created_by ? `Added by ${a.created_by}` : 'Added';
  const at = a.created_at && !Number.isNaN(Date.parse(a.created_at)) ? ` on ${new Date(a.created_at).toLocaleDateString()}` : '';
  return `${by}${at}`;
};

export function CustomerAliasesField({ customerName, canManage = false, onChange }: CustomerAliasesFieldProps) {
  const [aliases, setAliases] = useState<CustomerAlias[] | null>(null);
  const [draft, setDraft] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    const rows = await api.listAliases(customerName);
    const list = Array.isArray(rows) ? rows : [];
    setAliases(list);
    onChange?.(list.map((a) => a.alias));
  }, [customerName, onChange]);

  useEffect(() => {
    let alive = true;
    setAliases(null);
    setError(null);
    setDraft('');
    // Deferred call: a synchronous throw lands in .catch, never the render.
    Promise.resolve()
      .then(() => api.listAliases(customerName))
      .then((rows) => { if (alive) setAliases(Array.isArray(rows) ? rows : []); })
      .catch((e: any) => { if (alive) { setAliases([]); setError(e?.message || 'Failed to load aliases'); } });
    return () => { alive = false; };
  }, [customerName]);

  const handleAdd = async () => {
    if (busy) return;
    setBusy(true);
    setError(null);
    try {
      await api.addAlias(customerName, draft);
      setDraft('');
      await load();
    } catch (e: any) {
      setError(e?.message || 'Failed to add alias');
    } finally {
      setBusy(false);
    }
  };

  const handleRemove = async (a: CustomerAlias) => {
    if (busy) return;
    setBusy(true);
    setError(null);
    try {
      await api.removeAlias(customerName, a.id);
      await load();
    } catch (e: any) {
      setError(e?.message || 'Failed to remove alias');
    } finally {
      setBusy(false);
    }
  };

  return (
    <div data-testid="customer-aliases-field" style={{ margin: '18px 0 0' }}>
      <div id="customer-aliases-label" style={{ fontWeight: 600, color: 'var(--neutral-700)', marginBottom: '4px' }}>Aliases</div>
      <div style={{ fontSize: '0.82rem', color: 'var(--neutral-500)', marginBottom: '10px' }}>
        Other names this account goes by in imports (pipeline reports, RVTools, rep files). Matching ignores case and extra spaces.
        {canManage && ' Each alias is saved as soon as you add or remove it.'}
      </div>
      {aliases === null ? (
        <p role="status" style={{ margin: 0, fontSize: '0.85rem', color: 'var(--neutral-500)' }}>Loading aliases…</p>
      ) : aliases.length === 0 ? (
        <p style={{ margin: 0, fontSize: '0.85rem', color: 'var(--neutral-500)' }}>No aliases recorded.</p>
      ) : (
        <ul aria-labelledby="customer-aliases-label" style={{ listStyle: 'none', margin: 0, padding: 0, display: 'flex', flexWrap: 'wrap', gap: '8px' }}>
          {aliases.map((a) => (
            <li key={a.id} style={chipStyle} title={provenance(a)} data-testid="customer-alias-chip">
              <span style={{ display: 'flex', flexDirection: 'column', lineHeight: 1.2 }}>
                <span>{a.alias}</span>
                <span style={{ fontSize: '0.68rem', color: 'var(--neutral-500)' }}>{provenance(a)}</span>
              </span>
              {canManage && (
                <button
                  type="button"
                  aria-label={`Remove alias ${a.alias}`}
                  disabled={busy}
                  onClick={() => handleRemove(a)}
                  style={{ background: 'none', border: 'none', color: 'var(--neutral-500)', cursor: busy ? 'not-allowed' : 'pointer', fontSize: '0.9rem', padding: 0, lineHeight: 1 }}
                >
                  ×
                </button>
              )}
            </li>
          ))}
        </ul>
      )}
      {canManage && (
        <form
          onSubmit={(e) => { e.preventDefault(); void handleAdd(); }}
          style={{ display: 'flex', gap: '8px', marginTop: '12px', flexWrap: 'wrap' }}
        >
          <input
            type="text"
            aria-label="New alias"
            placeholder="Add an alias"
            value={draft}
            disabled={busy}
            onChange={(e) => setDraft(e.target.value)}
            style={{ flex: '1 1 200px', padding: '10px 12px', border: '1px solid var(--neutral-400)', borderRadius: 'var(--radius)', font: 'inherit' }}
          />
          <button
            type="submit"
            aria-label="Add alias"
            disabled={busy}
            style={{ padding: '10px 18px', background: 'var(--neutral-0)', color: 'var(--brand-700)', border: '1px solid var(--brand-500)', borderRadius: 'var(--radius)', cursor: busy ? 'not-allowed' : 'pointer', fontWeight: 600 }}
          >
            Add
          </button>
        </form>
      )}
      {error && (
        <div role="alert" data-testid="customer-aliases-error" style={{ marginTop: '10px', padding: '8px 12px', background: 'var(--status-negative-soft)', color: 'var(--status-negative)', borderRadius: 'var(--radius-sm)', fontSize: '0.82rem' }}>
          {error}
        </div>
      )}
    </div>
  );
}

export default CustomerAliasesField;
