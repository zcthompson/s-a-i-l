import { useCallback, useEffect, useRef, useState } from 'react';
import { api } from './api';
import type { CustomerAssessment } from '../types/use_case';

export function useAssessmentRounds(customerName?: string) {
  const sequence = useRef(0);
  const [state, setState] = useState<{ customer?: string; rows: CustomerAssessment[]; loading: boolean; error: boolean }>({ rows: [], loading: true, error: false });
  const load = useCallback(async () => {
    const request = ++sequence.current;
    setState(previous => ({ customer: customerName, rows: previous.customer === customerName ? previous.rows : [], loading: !!customerName, error: false }));
    if (!customerName) return;
    try {
      const rows = await api.listAssessments(customerName);
      if (sequence.current === request) setState({ customer: customerName, rows: Array.isArray(rows) ? rows : [], loading: false, error: false });
    } catch {
      if (sequence.current === request) setState({ customer: customerName, rows: [], loading: false, error: true });
    }
  }, [customerName]);
  useEffect(() => {
    const tracker = sequence;
    void load();
    return () => { ++tracker.current; };
  }, [load]);
  const current = state.customer === customerName;
  return { assessments: current ? state.rows : [], roundsLoading: !!customerName && (!current || state.loading),
    roundsLoadError: current && state.error, loadAssessments: load };
}
