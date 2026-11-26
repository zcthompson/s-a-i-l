import { DealDetail } from './DealDetail';
import { useEffect, useRef, useState } from 'react';
import { api } from '../lib/api';
import type { CustomerRecord } from '../lib/useCustomerRecord';

// Fetch through authorized record APIs; never display a record from another account.
export async function loadCustomerRecord({ module, id, customerId }: CustomerRecord): Promise<Record<string, any>> {
  let record;
  switch (module) {
    case 'note': record = await api.getSalesNote(id); break;
    case 'contact': record = await api.getContact(id); break;
    case 'activity': record = await api.getActivity(id); break;
    case 'technology': record = await api.getTechnology(id); break;
    case 'knowledge': record = await api.getCustomerKnowledge(id); break;
    case 'task': record = (await api.listTasks(customerId)).find(row => row.id === id); break;
    case 'deal': record = (await api.listDeals(customerId)).find(row => row.id === id); break;
    case 'use_case': record = await api.get(id); break;
    case 'strategy': record = (await api.getAccountStrategy(customerId)).plan; break;
  }
  if (!record || record.id !== id || (module !== 'strategy' && record.customer_id !== customerId)) throw new Error('Record unavailable');
  return record;
}
const FIELDS: Record<string, string> = {
  content: 'Note', description: 'Description', detail: 'Details', outcome: 'Outcome',
  email: 'Email', phone: 'Phone', department: 'Department', vendor: 'Vendor',
  version_edition: 'Version', status: 'Status', assignee: 'Assignee', due_date: 'Due date',
  due_at: 'Due time', close_date: 'Close date', next_step: 'Next step',
  objectives: 'Objectives', desired_outcomes: 'Desired outcomes', risks: 'Risks',
  plays: 'Plays', discovery_gaps: 'Discovery gaps', extracted_text: 'Document text',
};
function DefaultSelectedCustomerRecord({ selection, onClose }: { selection: CustomerRecord; onClose: () => void }) {
  const [data, setData] = useState<Record<string, any> | null>(null);
  const [failed, setFailed] = useState(false);
  const [retry, setRetry] = useState(0);
  const heading = useRef<HTMLHeadingElement>(null);
  const { customerId, module, id } = selection;
  useEffect(() => {
    let current = true;
    setData(null); setFailed(false);
    loadCustomerRecord({ customerId, module, id }).then(record => {
      if (current) setData(record);
    }).catch(() => { if (current) setFailed(true); });
    return () => { current = false; };
  }, [customerId, module, id, retry]);
  useEffect(() => { if (data || failed) heading.current?.focus(); }, [data, failed]);
  return <section aria-label="Selected account record" style={{ border: '2px solid var(--brand-500)', borderRadius: 'var(--radius)', padding: 16, marginBottom: 16 }}>
    <h2 ref={heading} tabIndex={-1} style={{ marginTop: 0 }}>{data?.display_name || data?.title || data?.name || data?.file_name || (module === 'strategy' ? 'Account strategy' : 'Selected record')}</h2>
    {failed ? <div role="alert">This record is unavailable or you no longer have access. <button onClick={() => setRetry(value => value + 1)}>Retry record</button></div>
      : !data ? <p role="status">Loading selected record…</p>
      : <dl>{Object.entries(FIELDS).filter(([key]) => typeof data[key] === 'string' && data[key]).map(([key, label]) => <div key={key}>
        <dt style={{ fontWeight: 600 }}>{label}</dt><dd style={{ margin: '4px 0 12px', whiteSpace: 'pre-wrap', overflowWrap: 'anywhere' }}>{data[key]}</dd>
      </div>)}</dl>}
    <button type="button" onClick={onClose}>Return to section</button>
  </section>;
}

export function SelectedCustomerRecord({ selection, onClose, onEditDeal, customerName, onOpenRecord, onChanged }: { selection: CustomerRecord; onClose: () => void; onEditDeal?: (id: number) => void; customerName?: string; onChanged?: () => void; onOpenRecord?: (module: string, id: number) => void }) {
  return selection.module === 'deal' ? <DealDetail onChanged={onChanged} customerName={customerName} onOpenRecord={onOpenRecord} customerId={selection.customerId} id={selection.id} onClose={onClose} onEdit={onEditDeal} /> : <DefaultSelectedCustomerRecord selection={selection} onClose={onClose} />;
}
