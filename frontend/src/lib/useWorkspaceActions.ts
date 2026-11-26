import { useEffect, useState } from 'react';
import { api } from './api';
export function useWorkspaceActions(customerId?: number) {
  const [data, setData] = useState<Awaited<ReturnType<typeof api.getWorkspaceActions>> | null>(null);
  const [error, setError] = useState(false);
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    let alive = true;
    setData(null); setError(false);
    if (customerId) Promise.resolve().then(() => api.getWorkspaceActions(customerId))
      .then(result => { if (alive) setData(result); }).catch(() => { if (alive) setError(true); });
    return () => { alive = false; };
  }, [customerId, attempt]);
  return { data: data?.customer_id === customerId ? data : null, error, retry: () => setAttempt(value => value + 1) };
}
