import { useState } from 'react';
import { useInRouterContext, useSearchParams } from 'react-router-dom';

function parseId(raw: string | null): number | null {
  if (!raw || !/^[1-9]\d*$/.test(raw)) return null;
  const id = Number(raw);
  return Number.isSafeInteger(id) ? id : null;
}

function useRoutedDetail(): [number | null, (id: number | null) => void] {
  const [params, setParams] = useSearchParams();
  const id = parseId(params.get('import'));
  return [id, (next) => setParams((previous) => {
    const updated = new URLSearchParams(previous);
    if (next === null) updated.delete('import');
    else updated.set('import', String(next));
    return updated;
  })];
}

function useLocalDetail(): [number | null, (id: number | null) => void] {
  return useState<number | null>(null);
}

export function useImportDetailLink(): [number | null, (id: number | null) => void] {
  const inRouter = useInRouterContext();
  // Router context is stable while this pane is mounted.
  // eslint-disable-next-line react-hooks/rules-of-hooks
  return inRouter ? useRoutedDetail() : useLocalDetail();
}
