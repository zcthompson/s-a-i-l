import { useState } from 'react';
import { api } from '../lib/api';
export function DealPromotion({ customerId, attentionId, vendor, allowed, onOpen, linkedDealId }: {
  customerId: number; attentionId?: string; vendor?: { import_id: number; opportunity_number: string };
  linkedDealId?: number | null;
  allowed: boolean; onOpen?: (id: number) => void;
}) {
  const [dealId, setDealId] = useState<number | null>(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const promote = async () => {
    setBusy(true); setError('');
    try { const result = await api.promoteDeal(customerId, vendor ? { vendor } : { attention_id: attentionId }); setDealId(result.deal.id); onOpen?.(result.deal.id); }
    catch (error) { setError(error instanceof Error ? error.message : 'Deal creation unavailable'); }
    finally { setBusy(false); }
  };
  const selectedId = dealId ?? linkedDealId;
  if (!allowed && !selectedId) return null;
  return <div style={{ marginTop: 8 }}>
    {selectedId ? <button type="button" onClick={() => onOpen?.(selectedId!)}>Open linked deal #{selectedId}</button>
      : <button type="button" disabled={busy} onClick={() => { if (window.confirm('Create a rep-maintained deal linked to this evidence? Vendor amounts will remain separate.')) void promote(); }}>{busy ? 'Creating…' : 'Create a deal?'}</button>}
    {error && <p role="alert">{error}</p>}
  </div>;
}
