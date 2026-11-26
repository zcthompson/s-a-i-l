import { useState } from 'react';
import { useInRouterContext, useSearchParams } from 'react-router-dom';

// Edit/remove dialogs and form drafts remain transient.
const AREAS = new Set([
  'overview', 'intelligence-summary', 'technology-inventory', 'customer-knowledge',
  'sales-notes', 'contacts', 'activities', 'tasks', 'account-brief',
  'third-party-services', 'assessments', 'bulk-score', 'use-cases', 'analytics',
  'business-impact', 'business-impact-forecasting', 'export', 'sales-opportunities',
  'sales-evaluations', 'account-strategy', 'team', 'departments', 'detail',
  'sales-pipeline', 'sales-vendor-intelligence', 'account-timeline', 'sales-deals',
]);

type FilterTarget = { customerId: number; prefix: string; params: Record<string, string> };
type CustomerArea = [string, (area: string, filters?: FilterTarget) => void, number | null, (id: number) => void];

function parseId(raw: string | null): number | null {
  if (!raw || !/^[1-9]\d*$/.test(raw)) return null;
  const id = Number(raw);
  return Number.isSafeInteger(id) ? id : null;
}

function useRoutedCustomerArea(): CustomerArea {
  const [params, setParams] = useSearchParams();
  const raw = params.get('area');
  const area = raw && AREAS.has(raw) ? raw : 'overview';
  const detailId = area === 'detail' ? parseId(params.get('customer_uc')) : null;
  const select = (next: string, filters?: FilterTarget) => {
    if (next === 'detail') return;
    const safe = AREAS.has(next) ? next : 'overview';
    if (!filters && raw === safe && !params.has('customer_uc') && !params.has('record_id')) return;
    setParams((previous) => {
      const updated = new URLSearchParams(previous);
      updated.set('area', safe);
      if (filters) {
        updated.set(`${filters.prefix}_customer`, String(filters.customerId));
        Object.entries(filters.params).forEach(([key, value]) => updated.set(`${filters.prefix}_${key}`, value));
      }
      updated.delete('customer_uc');
      ['record_module', 'record_id', 'record_customer'].forEach(key => updated.delete(key));
      return updated;
    });
  };
  const openDetail = (id: number) => setParams((previous) => {
    const updated = new URLSearchParams(previous);
    ['record_module', 'record_id', 'record_customer'].forEach(key => updated.delete(key));
    updated.set('area', 'detail');
    updated.set('customer_uc', String(id));
    return updated;
  });
  return [area, select, detailId, openDetail];
}

function useLocalCustomerArea(): CustomerArea {
  const [area, setArea] = useState('overview');
  const [detailId, setDetailId] = useState<number | null>(null);
  return [area, (next) => { setDetailId(null); setArea(next); }, detailId,
    (id) => { setDetailId(id); setArea('detail'); }];
}

export function useCustomerArea(): CustomerArea {
  const inRouter = useInRouterContext();
  // Router context does not change for a mounted component.
  // eslint-disable-next-line react-hooks/rules-of-hooks
  return inRouter ? useRoutedCustomerArea() : useLocalCustomerArea();
}
