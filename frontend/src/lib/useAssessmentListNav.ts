import { useState } from 'react';
import { useInRouterContext, useSearchParams } from 'react-router-dom';

export type AssessmentSort = 'date' | 'score' | 'title';
export interface AssessmentListNav {
  search: string;
  status: string;
  sort: AssessmentSort;
  customerId: number | null;
  page: number;
}
const defaults: AssessmentListNav = { search: '', status: '', sort: 'date', customerId: null, page: 1 };
const validStatus = new Set(['draft', 'active', 'completed', 'archived']);
function positiveId(raw: string | null): number | null {
  if (!raw || !/^[1-9]\d*$/.test(raw)) return null;
  const n = Number(raw);
  return Number.isSafeInteger(n) ? n : null;
}
function parse(params: URLSearchParams): AssessmentListNav {
  const status = params.get('as_status') ?? '';
  const sort = params.get('as_sort');
  return {
    search: (params.get('as_q') ?? '').trim(),
    status: validStatus.has(status) ? status : '',
    sort: sort === 'score' || sort === 'title' ? sort : 'date',
    customerId: positiveId(params.get('as_customer')),
    page: Math.min(positiveId(params.get('as_page')) ?? 1, 1_000_000),
  };
}
type Update = (patch: Partial<AssessmentListNav>, replace?: boolean) => void;
function useRouted(): [AssessmentListNav, Update] {
  const [params, setParams] = useSearchParams();
  return [parse(params), (patch, replace = false) => setParams((previous) => {
    const next = new URLSearchParams(previous);
    const value = { ...parse(previous), ...patch };
    const set = (key: string, v: string | null) => { if (v) next.set(key, v); else next.delete(key); };
    set('as_q', value.search || null);
    set('as_status', value.status || null);
    set('as_sort', value.sort === 'date' ? null : value.sort);
    set('as_customer', value.customerId === null ? null : String(value.customerId));
    set('as_page', value.page === 1 ? null : String(value.page));
    return next;
  }, { replace })];
}
function useLocal(): [AssessmentListNav, Update] {
  const [state, setState] = useState(defaults);
  return [state, (patch) => setState((previous) => ({ ...previous, ...patch }))];
}
export function useAssessmentListNav(): [AssessmentListNav, Update] {
  const inRouter = useInRouterContext();
  // Router context is stable throughout this component's lifetime.
  // eslint-disable-next-line react-hooks/rules-of-hooks
  return inRouter ? useRouted() : useLocal();
}
