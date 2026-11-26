import { useState } from 'react';
import { useInRouterContext, useSearchParams } from 'react-router-dom';

/** Parameters owned by portfolio lists; never transfer these to a different scope. */
export const PORTFOLIO_FILTER_PARAMS = ['q', 'vertical', 'branch', 'owner', 'sort', 'dir', 'page', 'ps'] as const;

function useRoutedScope(isAdmin: boolean) {
  const [params, setParams] = useSearchParams();
  const raw = params.get('portfolio_scope');
  const invalid = raw !== null && (raw !== 'my' && raw !== 'all' || !isAdmin);
  // An invalid admin link falls back to the narrower authorized scope.
  const myView = isAdmin && (raw === 'my' || invalid);
  const toggle = () => setParams(previous => {
    const next = new URLSearchParams(previous);
    next.set('portfolio_scope', myView ? 'all' : 'my');
    PORTFOLIO_FILTER_PARAMS.forEach(key => next.delete(key));
    return next;
  });
  return { myView, toggle, invalid };
}

function useLocalScope(isAdmin: boolean) {
  const [my, setMy] = useState(false);
  return { myView: isAdmin && my, toggle: () => setMy(value => !value), invalid: false };
}

/** The hook mode is stable for a component's lifetime. */
export function useDashboardScope(isAdmin: boolean) {
  const routed = useInRouterContext();
  // eslint-disable-next-line react-hooks/rules-of-hooks
  return routed ? useRoutedScope(isAdmin) : useLocalScope(isAdmin);
}
