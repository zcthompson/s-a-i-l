/**
 * PortfolioFilterBar — shared search / filter / sort / count / reset controls
 * for the portfolio surfaces (H2). Presentational over portfolioNav state: the
 * parent owns the state (URL-synced) and the filtered list.
 */
import { useEffect, useState } from 'react';
import type { CSSProperties } from 'react';
import { api } from '../lib/api';
import { UNASSIGNED, countLabel, distinctValues, isFiltered, navStateToSearchParams, parseNavState } from '../lib/portfolioNav';
import type { NavDefaults, PortfolioNavRow, PortfolioNavState, SortKey } from '../lib/portfolioNav';
import { PORTFOLIO_FILTER_PARAMS } from '../lib/useDashboardScope';
import { SavedViewsMenu } from './SavedViewsMenu';
import type { SavedViewParams } from './SavedViewsMenu';

export const SORT_LABELS: Record<SortKey, string> = {
  newest: 'Newest (default)',
  name: 'Name',
  vertical: 'Vertical',
  branch: 'Branch',
  owner: 'Owner',
  impact: 'Account Impact',
  pipeline: 'Pipeline',
  granted: 'Added',
};

export interface PortfolioFilterBarProps {
  /** The COMPLETE authorized rows (option lists derive from these). */
  rows: readonly PortfolioNavRow[];
  state: PortfolioNavState;
  onChange: (patch: Partial<PortfolioNavState>) => void;
  onReset: () => void;
  filteredCount: number;
  /** Sort options offered (HomeDashboard omits 'granted'). */
  sortKeys: readonly SortKey[];
  disabled?: boolean;
  /** Surface defaults (e.g. an A–Z default sort) — the surface-default state
   *  counts as unfiltered (no Reset). Omitted = the H2 defaults. */
  defaults?: NavDefaults;
  /** Show the count line even when unfiltered (it replaces a "N total" line). */
  alwaysShowCount?: boolean;
}

const controlStyle: CSSProperties = {
  padding: '6px 10px', fontSize: '0.85rem', color: 'var(--neutral-700)',
  background: 'var(--neutral-0)', border: '1px solid var(--divider)',
  borderRadius: 'var(--radius-sm)', minWidth: 0, maxWidth: '100%', boxSizing: 'border-box',
};
const labelStyle: CSSProperties = {
  display: 'flex', flexDirection: 'column', gap: '2px', fontSize: '0.7rem',
  color: 'var(--neutral-500)', flex: '1 1 150px', minWidth: 'min(130px, 100%)', maxWidth: '100%', boxSizing: 'border-box',
};

/** Keep the current value selectable even if it is not in the payload options. */
const withCurrent = (options: string[], current: string) =>
  current !== '' && !options.includes(current) ? [...options, current] : options;

/** The bar state as the H2 URL params (null = the surface default / absent),
 *  exactly what the URL carries; no other keys. */
export function navStateToViewParams(state: PortfolioNavState, defaults?: NavDefaults): SavedViewParams {
  const sp = navStateToSearchParams(state, undefined, defaults);
  return Object.fromEntries(PORTFOLIO_FILTER_PARAMS.map(k => [k, sp.get(k)]));
}

/** A stored view's params as a COMPLETE nav patch (absent/invalid values fall
 *  back to the surface defaults via the H2 URL codec); `view` is never touched. */
export function viewParamsToNavPatch(params: SavedViewParams, defaults?: NavDefaults): Partial<PortfolioNavState> {
  const sp = new URLSearchParams();
  PORTFOLIO_FILTER_PARAMS.forEach(k => {
    const v = params[k];
    if (typeof v === 'string') sp.set(k, v);
  });
  const { q, vertical, branch, owner, sort, dir, page, pageSize } = parseNavState(sp, defaults);
  return { q, vertical, branch, owner, sort, dir, page, pageSize };
}

export function PortfolioFilterBar({ rows, state, onChange, onReset, filteredCount, sortKeys, disabled, defaults, alwaysShowCount }: PortfolioFilterBarProps) {
  const [canonicalVerticals, setCanonicalVerticals] = useState<string[]>([]);
  useEffect(() => {
    let live = true;
    Promise.resolve(api.listVerticals())
      .then(r => { if (live && r && Array.isArray((r as { verticals?: unknown }).verticals)) setCanonicalVerticals((r as { verticals: string[] }).verticals); })
      .catch(() => undefined);
    return () => { live = false; };
  }, []);

  const verticals = withCurrent(
    canonicalVerticals.length > 0 ? canonicalVerticals : distinctValues(rows.map(r => r.vertical)),
    state.vertical,
  );
  const branches = withCurrent(distinctValues(rows.map(r => r.branch)), state.branch);
  const owners = withCurrent(distinctValues(rows.map(r => r.primaryRep)), state.owner === UNASSIGNED ? '' : state.owner);
  const offerUnassigned = state.owner === UNASSIGNED || rows.some(r => r.knownMetadata === true && (r.primaryRep ?? null) === null);
  const filtered = isFiltered(state, defaults);
  // A surface with a non-newest default sort marks THAT option as the default.
  const defaultSortKey = defaults?.defaultSort?.sort ?? 'newest';
  const sortLabel = (k: SortKey) =>
    defaultSortKey === 'newest' ? SORT_LABELS[k] : k === 'newest' ? 'Newest' : k === defaultSortKey ? `${SORT_LABELS[k]} (default)` : SORT_LABELS[k];

  return (
    <div role="search" aria-label="Filter portfolio" style={{ display: 'flex', flexDirection: 'column', gap: '8px', padding: '8px 0' }}>
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: '8px', alignItems: 'flex-end' }}>
        <label style={{ ...labelStyle, flex: '2 1 220px' }}>
          Search
          <input
            type="search"
            aria-label="Search customers"
            placeholder="Name, vertical, branch, owner…"
            value={state.q}
            disabled={disabled}
            onChange={e => onChange({ q: e.target.value })}
            style={controlStyle}
          />
        </label>
        <label style={labelStyle}>
          Vertical
          <select aria-label="Filter by vertical" value={state.vertical} disabled={disabled} onChange={e => onChange({ vertical: e.target.value })} style={controlStyle}>
            <option value="">All verticals</option>
            {verticals.map(v => <option key={v} value={v}>{v}</option>)}
          </select>
        </label>
        <label style={labelStyle}>
          Branch
          <select aria-label="Filter by branch" value={state.branch} disabled={disabled} onChange={e => onChange({ branch: e.target.value })} style={controlStyle}>
            <option value="">All branches</option>
            {branches.map(v => <option key={v} value={v}>{v}</option>)}
          </select>
        </label>
        <label style={labelStyle}>
          Owner
          <select aria-label="Filter by owner" value={state.owner} disabled={disabled} onChange={e => onChange({ owner: e.target.value })} style={controlStyle}>
            <option value="">All owners</option>
            {owners.map(v => <option key={v} value={v}>{v}</option>)}
            {offerUnassigned && <option value={UNASSIGNED}>Unassigned</option>}
          </select>
        </label>
        <label style={labelStyle}>
          Sort
          <span style={{ display: 'flex', gap: '4px', minWidth: 0, flexWrap: 'wrap' }}>
            <select aria-label="Sort by" value={state.sort} disabled={disabled} onChange={e => onChange({ sort: e.target.value as SortKey })} style={{ ...controlStyle, flex: 1 }}>
              {sortKeys.map(k => <option key={k} value={k}>{sortLabel(k)}</option>)}
            </select>
            {state.sort !== 'newest' && (
              <button
                type="button"
                aria-label={state.dir === 'asc' ? 'Sort direction: ascending' : 'Sort direction: descending'}
                title="Toggle sort direction"
                disabled={disabled}
                onClick={() => onChange({ dir: state.dir === 'asc' ? 'desc' : 'asc' })}
                style={{ ...controlStyle, cursor: 'pointer' }}
              >
                {state.dir === 'asc' ? '↑ Asc' : '↓ Desc'}
              </button>
            )}
          </span>
        </label>
      </div>
      <div style={{ display: 'flex', alignItems: 'center', gap: '12px', minHeight: '1.5rem', flexWrap: 'wrap', fontSize: '0.8rem', color: 'var(--neutral-500)' }}>
        <span role="status" aria-live="polite" data-testid="portfolio-match-count">
          {filtered || alwaysShowCount ? countLabel(filteredCount, rows.length) : ''}
        </span>
        {filtered && (
          <button
            type="button"
            aria-label="Reset filters"
            onClick={onReset}
            style={{ ...controlStyle, cursor: 'pointer', padding: '3px 10px', color: 'var(--brand-700)', border: '1px solid var(--brand-500)' }}
          >
            Reset
          </button>
        )}
        <span style={{ marginLeft: 'auto' }}>
          <SavedViewsMenu
            surface="portfolio"
            currentParams={navStateToViewParams(state, defaults)}
            onApply={params => onChange(viewParamsToNavPatch(params, defaults))}
            disabled={disabled}
          />
        </span>
      </div>
    </div>
  );
}

export default PortfolioFilterBar;
