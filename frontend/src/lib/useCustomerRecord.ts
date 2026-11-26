import { useState } from 'react';
import { useInRouterContext, useSearchParams } from 'react-router-dom';

export const RECORD_AREAS: Record<string, string> = {
  note: 'sales-notes', contact: 'contacts', activity: 'activities', task: 'tasks',
  technology: 'technology-inventory', strategy: 'account-strategy', knowledge: 'customer-knowledge',
  deal: 'sales-deals', use_case: 'use-cases',
};
// Timeline/search kinds with no single-record view open the workspace area
// that lists them (RF-07). Kinds absent from both maps have no destination.
export const KIND_AREAS: Record<string, string> = {
  pipeline_import: 'sales-pipeline', rvtools_import: 'sales-vendor-intelligence',
  strategy_snapshot: 'account-strategy', membership: 'team',
};
export function hasDestination(kind: string): boolean {
  return kind in RECORD_AREAS || kind in KIND_AREAS;
}
export interface CustomerRecord { module: string; id: number; customerId: number }
function useRoutedRecord(customerId: number | undefined, area: string) {
  const [params, setParams] = useSearchParams();
  const module = params.get('record_module') || '';
  const id = Number(params.get('record_id'));
  const record = customerId && Number(params.get('record_customer')) === customerId &&
    RECORD_AREAS[module] === area && Number.isSafeInteger(id) && id > 0
    ? { module, id, customerId } : null;
  const select = (module: string, id: number) => {
    if (!customerId || !RECORD_AREAS[module] || !Number.isSafeInteger(id) || id <= 0) return;
    setParams(previous => {
      const next = new URLSearchParams(previous);
      next.set('area', RECORD_AREAS[module]);
      next.delete('customer_uc');
      next.set('record_module', module);
      next.set('record_id', String(id));
      next.set('record_customer', String(customerId));
      return next;
    });
  };
  const clear = () => setParams(previous => {
    const next = new URLSearchParams(previous);
    ['record_module', 'record_id', 'record_customer'].forEach(key => next.delete(key));
    return next;
  });
  return { record, select, clear };
}
function useLocalRecord(customerId: number | undefined, area: string) {
  const [record, setRecord] = useState<CustomerRecord | null>(null);
  return { record: record && record.customerId === customerId && RECORD_AREAS[record.module] === area ? record : null,
    select: (module: string, id: number) => { if (customerId) setRecord({ module, id, customerId }); },
    clear: () => setRecord(null) };
}
export function useCustomerRecord(customerId: number | undefined, area: string) {
  const routed = useInRouterContext();
  // Router context is stable for a mounted component.
  // eslint-disable-next-line react-hooks/rules-of-hooks
  return routed ? useRoutedRecord(customerId, area) : useLocalRecord(customerId, area);
}
