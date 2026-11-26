import { useState } from 'react';
import { useInRouterContext, useSearchParams } from 'react-router-dom';
export type ListParams = Record<string, string>;
function useRouted(customerId: number, prefix: string, defaults: ListParams) {
  const [params, setParams] = useSearchParams();
  const scoped = params.get(`${prefix}_customer`) === String(customerId);
  const state = Object.fromEntries(Object.entries(defaults).map(([key, value]) => [key, scoped ? params.get(`${prefix}_${key}`) ?? value : value]));
  const update = (patch: ListParams) => setParams(previous => {
    const next = new URLSearchParams(previous);
    next.set(`${prefix}_customer`, String(customerId));
    Object.entries({ ...state, ...patch }).forEach(([key, value]) => next.set(`${prefix}_${key}`, value));
    return next;
  });
  return [state, update] as const;
}
function useLocal(_customerId: number, _prefix: string, defaults: ListParams) {
  const [state, setState] = useState(defaults);
  return [state, (patch: ListParams) => setState(previous => ({ ...previous, ...patch }))] as const;
}
export function useAccountListState(customerId: number, prefix: string, defaults: ListParams) {
  const routed = useInRouterContext();
  // Router context is stable throughout a mounted component.
  // eslint-disable-next-line react-hooks/rules-of-hooks
  return routed ? useRouted(customerId, prefix, defaults) : useLocal(customerId, prefix, defaults);
}
