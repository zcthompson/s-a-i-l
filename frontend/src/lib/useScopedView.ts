import { useState } from 'react';
import { useInRouterContext, useSearchParams } from 'react-router-dom';

type Values = Record<string, string>;
type Update = (patch: Record<string, string | null>) => void;

function useRouted(scope: number | undefined, prefix: string, keys: readonly string[]): [Values, Update] {
  const [params, setParams] = useSearchParams();
  const owner = `${prefix}_owner`;
  const matches = scope !== undefined && params.get(owner) === String(scope);
  const values: Values = {};
  keys.forEach((key) => { values[key] = matches ? params.get(`${prefix}_${key}`) ?? '' : ''; });
  const update: Update = (patch) => {
    if (scope === undefined) return;
    setParams((previous) => {
      const next = new URLSearchParams(previous);
      if (next.get(owner) !== String(scope)) keys.forEach((key) => next.delete(`${prefix}_${key}`));
      next.set(owner, String(scope));
      keys.forEach((key) => {
        if (!(key in patch)) return;
        const value = patch[key];
        if (value) next.set(`${prefix}_${key}`, value);
        else next.delete(`${prefix}_${key}`);
      });
      if (keys.every((key) => !next.has(`${prefix}_${key}`))) next.delete(owner);
      return next;
    });
  };
  return [values, update];
}
function useLocal(scope: number | undefined): [Values, Update] {
  const [state, setState] = useState<{ owner: number | undefined; values: Values }>({ owner: scope, values: {} });
  return [state.owner === scope ? state.values : {}, (patch) => setState((previous) => {
    const values = previous.owner === scope ? { ...previous.values } : {};
    Object.entries(patch).forEach(([key, value]) => { if (value) values[key] = value; else delete values[key]; });
    return { owner: scope, values };
  })];
}
/** Scope links to a customer/use case; never store text, drafts or secrets. */
export function useScopedView(scope: number | undefined, prefix: string, keys: readonly string[]): [Values, Update] {
  const inRouter = useInRouterContext();
  // Router context does not change for the lifetime of a mounted component.
  // eslint-disable-next-line react-hooks/rules-of-hooks
  return inRouter ? useRouted(scope, prefix, keys) : useLocal(scope);
}
export function scopedId(raw: string | undefined): number | null {
  if (!raw || !/^[1-9]\d*$/.test(raw)) return null;
  const id = Number(raw);
  return Number.isSafeInteger(id) ? id : null;
}
