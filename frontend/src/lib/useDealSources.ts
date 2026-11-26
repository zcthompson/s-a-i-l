import { useEffect, useState } from 'react';
import { api } from './api';
export function useDealSources(customerId: number) {
  const [sources, setSources] = useState<Record<string, number>>({});
  useEffect(() => {
    let alive = true;
    setSources({});
    if (customerId) Promise.resolve().then(() => api.listDeals(customerId)).then(rows => {
      if (alive) setSources(Object.fromEntries(rows.flatMap(row => [...(row.source_key ? [[row.source_key, row.id]] : []), ...(row.vendor_evidence ?? []).map(evidence => [`vendor:${evidence.opportunity_number.trim()}`, row.id])])));
    }).catch(() => {});
    return () => { alive = false; };
  }, [customerId]);
  return sources;
}
