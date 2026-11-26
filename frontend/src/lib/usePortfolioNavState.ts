/**
 * usePortfolioNavState — binds portfolioNav state to the current route's query
 * string (H2). Filter/sort/page changes REPLACE the URL (no history spam);
 * unrelated params (notably the app's `?view=`) are preserved.
 *
 * Outside a Router (isolated component tests) it degrades to local state with
 * the same API. `useInRouterContext()` is constant for a mounted tree, so the
 * conditional hook choice is stable.
 */
import { useCallback, useMemo, useState } from 'react';
import { useInRouterContext, useSearchParams } from 'react-router-dom';
import {
  applyNavPatch, clampPage, defaultNavState, navStateToSearchParams, parseNavState, resetNavState,
} from './portfolioNav';
import type { NavDefaults, PortfolioNavState } from './portfolioNav';

export interface PortfolioNavControls {
  state: PortfolioNavState;
  /** Partial update; filter/sort/pageSize changes reset the page to 1. */
  update: (patch: Partial<PortfolioNavState>) => void;
  reset: () => void;
}

// `opts` (surface defaults) must be stable for the mounted surface — pass a
// module-level constant.
function useRouted(opts: NavDefaults): PortfolioNavControls {
  const [searchParams, setSearchParams] = useSearchParams();
  const key = searchParams.toString();
  // eslint-disable-next-line react-hooks/exhaustive-deps
  const state = useMemo(() => parseNavState(searchParams, opts), [key]);
  const write = useCallback((fn: (s: PortfolioNavState) => PortfolioNavState) => {
    setSearchParams(prev => navStateToSearchParams(fn(parseNavState(prev, opts)), prev, opts), { replace: true });
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [setSearchParams]);
  const update = useCallback((patch: Partial<PortfolioNavState>) => write(s => applyNavPatch(s, patch)), [write]);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  const reset = useCallback(() => write(s => resetNavState(s, opts)), [write]);
  return { state, update, reset };
}

function useLocal(opts: NavDefaults): PortfolioNavControls {
  const [state, setState] = useState<PortfolioNavState>(() => defaultNavState(null, opts));
  const update = useCallback((patch: Partial<PortfolioNavState>) => setState(s => applyNavPatch(s, patch)), []);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  const reset = useCallback(() => setState(s => resetNavState(s, opts)), []);
  return { state, update, reset };
}

const NO_DEFAULTS: NavDefaults = {};

/** `opts` = optional per-surface defaults (omitted = the H2 defaults). */
export function usePortfolioNavState(opts: NavDefaults = NO_DEFAULTS): PortfolioNavControls {
  const inRouter = useInRouterContext();
  // eslint-disable-next-line react-hooks/rules-of-hooks
  return inRouter ? useRouted(opts) : useLocal(opts);
}

/** Slice the FILTERED list for the pager props (page clamps on shrink without
 *  rewriting the URL). */
export function paginateNav<T>(items: readonly T[], state: PortfolioNavState, update: PortfolioNavControls['update']) {
  const total = items.length;
  const page = clampPage(state.page, total, state.pageSize);
  const start = total === 0 ? 0 : (page - 1) * state.pageSize + 1;
  const end = Math.min(page * state.pageSize, total);
  return {
    visible: items.slice((page - 1) * state.pageSize, page * state.pageSize),
    pagerProps: {
      total, page, start, end, pageSize: state.pageSize,
      onPageChange: (p: number) => update({ page: clampPage(p, total, state.pageSize) }),
      onPageSizeChange: (size: number) => update({ pageSize: size }),
    },
  };
}
