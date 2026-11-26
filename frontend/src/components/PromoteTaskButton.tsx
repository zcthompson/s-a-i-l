/**
 * H5 — idempotent "Create follow-up task" action. The backend dedups on
 * (customer, source_key): created=false means the task already exists, which
 * is a neutral outcome (inline role="status", no error styling). The in-flight
 * guard prevents a double-click or rerender from firing a second call.
 */
import { useRef, useState } from 'react';
import { api } from '../lib/api';
import type { TaskSourceType } from '../types/engagement';

interface Props {
  customerId: number;
  sourceType: TaskSourceType;
  sourceId: number;
  /** Accessible context, e.g. the card or note title. */
  label?: string;
}

export function PromoteTaskButton({ customerId, sourceType, sourceId, label }: Props) {
  const inFlight = useRef(false);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const click = async () => {
    if (inFlight.current) return;
    inFlight.current = true;
    setBusy(true);
    setError(null);
    setMessage(null);
    try {
      const res = await api.promoteTask(customerId, { source_type: sourceType, source_id: sourceId });
      setMessage(res.created ? 'Follow-up task created' : 'Task already exists for this source');
    } catch (e: any) {
      setError(e?.message || 'Failed to create task');
    } finally {
      inFlight.current = false;
      setBusy(false);
    }
  };

  return (
    <span style={{ display: 'inline-flex', alignItems: 'center', gap: '8px', flexWrap: 'wrap' }}>
      <button
        role="button"
        aria-label={label ? `Create follow-up task from ${label}` : 'Create follow-up task'}
        disabled={busy}
        onClick={click}
        style={{ padding: '4px 12px', margin: 0, background: 'var(--neutral-0)', color: 'var(--brand-700)', border: '1px solid var(--brand-500)', borderRadius: 'var(--radius)', cursor: busy ? 'not-allowed' : 'pointer', fontSize: '0.78rem', fontWeight: 600 }}
      >
        Create follow-up task
      </button>
      {message && (
        <span role="status" data-testid="promote-status" style={{ fontSize: '0.78rem', color: 'var(--neutral-600)' }}>{message}</span>
      )}
      {error && (
        <span role="alert" data-testid="promote-error" style={{ fontSize: '0.78rem', color: 'var(--status-negative)' }}>{error}</span>
      )}
    </span>
  );
}
