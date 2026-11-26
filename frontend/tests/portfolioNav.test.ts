/** H2 — pure portfolioNav unit tests (codec, filter, sort, count). Synthetic names only. */
import { describe, it, expect } from 'vitest';
import {
  applyNavPatch, countLabel, defaultNavState, filterRows, isFiltered, matchesText, navStateToSearchParams,
  parseNavState, resetNavState, sortRows,
} from '../src/lib/portfolioNav';
import type { PortfolioNavRow, PortfolioNavState } from '../src/lib/portfolioNav';

const st = (over: Partial<PortfolioNavState> = {}): PortfolioNavState => ({ ...defaultNavState(), ...over });
const params = (s: string) => new URLSearchParams(s);
const ids = (rows: PortfolioNavRow[]) => rows.map(r => r.id);

const rows: PortfolioNavRow[] = [
  { id: 5, name: 'Zephyr Holdings', vertical: 'Energy', branch: 'North', primaryRep: 'Rep Bravo', salesArea: 'Area 9', primarySubsidiary: 'Zephyr Labs', managerName: 'Mgr Quill', knownMetadata: true, totalImpact: 500, pipelineAcv: null, grantedAt: '2026-03-01T00:00:00Z' },
  { id: 4, name: 'acme test', description: 'Widget maker', vertical: 'Healthcare', branch: 'South', primaryRep: 'Rep Alpha', knownMetadata: true, totalImpact: null, pipelineAcv: 900, grantedAt: '2026-01-01T00:00:00Z' },
  { id: 3, name: 'Borealis', vertical: 'Energy', branch: 'South', primaryRep: null, knownMetadata: true, totalImpact: 500, pipelineAcv: 10, grantedAt: null },
  { id: 2, name: 'Cobalt', knownMetadata: false, totalImpact: 100, pipelineAcv: 10, grantedAt: '2026-02-01T00:00:00Z' },
  { id: 1, name: 'Delta Works', vertical: 'Energy', branch: null, primaryRep: 'Rep Alpha', knownMetadata: true, totalImpact: 0, pipelineAcv: 0, grantedAt: '2026-02-01T00:00:00Z' },
];

describe('URL codec', () => {
  it('default state serializes to no params', () => {
    expect(navStateToSearchParams(defaultNavState()).toString()).toBe('');
  });

  it('round-trips a non-default state', () => {
    const state = st({ q: 'zeph yr', vertical: 'Energy', branch: 'North', owner: 'Rep Bravo', sort: 'impact', dir: 'desc', page: 3, pageSize: 40 });
    const sp = navStateToSearchParams(state);
    expect(parseNavState(new URLSearchParams(sp.toString()))).toEqual(state);
  });

  it('writes only non-default values and deletes defaults from base, preserving unrelated params', () => {
    const base = params('view=dashboard&q=old&page=4&other=keep');
    const out = navStateToSearchParams(st({ sort: 'name' }), base);
    expect(out.get('view')).toBe('dashboard'); // null state.view leaves the app's ?view= alone
    expect(out.get('other')).toBe('keep');
    expect(out.has('q')).toBe(false);
    expect(out.has('page')).toBe(false);
    expect(out.get('sort')).toBe('name');
    expect(out.has('dir')).toBe(false); // asc is the default
    expect(navStateToSearchParams(st({ sort: 'name', dir: 'desc' })).get('dir')).toBe('desc');
  });

  it('dir is never written for the newest sort', () => {
    expect(navStateToSearchParams(st({ sort: 'newest', dir: 'desc' })).has('dir')).toBe(false);
  });

  it('invalid values fall back to defaults without throwing', () => {
    const s = parseNavState(params('sort=bogus&dir=sideways&page=-3&ps=7&view=weird'));
    expect(s).toEqual(defaultNavState());
    expect(parseNavState(params('page=0')).page).toBe(1);
    expect(parseNavState(params('page=abc')).page).toBe(1);
    expect(parseNavState(params('page=2.5')).page).toBe(1);
    expect(parseNavState(params('ps=10')).pageSize).toBe(10);
    expect(parseNavState(params('ps=15')).pageSize).toBe(20);
  });

  it('view: my/all parsed, else the opts default; explicit view round-trips and default is deleted', () => {
    expect(parseNavState(params('view=all'), { defaultView: 'my' }).view).toBe('all');
    expect(parseNavState(params('view=dashboard'), { defaultView: 'my' }).view).toBe('my');
    expect(parseNavState(params('')).view).toBeNull();
    expect(navStateToSearchParams(st({ view: 'all' })).get('view')).toBe('all');
    expect(navStateToSearchParams(st({ view: 'my' }), undefined, { defaultView: 'my' }).has('view')).toBe(false);
  });
});

describe('filterRows', () => {
  it('q: case-insensitive, trimmed, multi-field substring', () => {
    expect(ids(filterRows(rows, st({ q: '  ZEPHYR ' })))).toEqual([5]);
    expect(ids(filterRows(rows, st({ q: 'widget' })))).toEqual([4]); // description
    expect(ids(filterRows(rows, st({ q: 'area 9' })))).toEqual([5]); // salesArea
    expect(ids(filterRows(rows, st({ q: 'zephyr labs' })))).toEqual([5]); // subsidiary
    expect(ids(filterRows(rows, st({ q: 'quill' })))).toEqual([5]); // manager
    expect(ids(filterRows(rows, st({ q: 'rep alpha' })))).toEqual([4, 1]); // owner
    expect(ids(filterRows(rows, st({ q: 'healthcare' })))).toEqual([4]); // vertical
    expect(ids(filterRows(rows, st({ q: 'north' })))).toEqual([5]); // branch
    expect(matchesText(rows[0], '   ')).toBe(true);
  });

  it('vertical / branch / owner are exact matches', () => {
    expect(ids(filterRows(rows, st({ vertical: 'Energy' })))).toEqual([5, 3, 1]);
    expect(ids(filterRows(rows, st({ vertical: 'Ener' })))).toEqual([]);
    expect(ids(filterRows(rows, st({ branch: 'South' })))).toEqual([4, 3]);
    expect(ids(filterRows(rows, st({ owner: 'Rep Alpha' })))).toEqual([4, 1]);
  });

  it("owner 'unassigned' matches only known-metadata rows with no rep", () => {
    expect(ids(filterRows(rows, st({ owner: 'unassigned' })))).toEqual([3]);
  });

  it('knownMetadata=false rows match no metadata filter but still match text on name', () => {
    expect(ids(filterRows(rows, st({ vertical: 'Energy' })))).not.toContain(2);
    expect(ids(filterRows(rows, st({ owner: 'unassigned' })))).not.toContain(2);
    expect(ids(filterRows(rows, st({ q: 'cobalt' })))).toEqual([2]);
  });

  it('filters AND-compose', () => {
    expect(ids(filterRows(rows, st({ vertical: 'Energy', branch: 'South' })))).toEqual([3]);
    expect(ids(filterRows(rows, st({ vertical: 'Energy', q: 'delta', owner: 'Rep Alpha' })))).toEqual([1]);
    expect(ids(filterRows(rows, st({ vertical: 'Healthcare', branch: 'North' })))).toEqual([]);
  });

  it('does not mutate the input', () => {
    const copy = ids(rows);
    filterRows(rows, st({ q: 'a' }));
    sortRows(rows, st({ sort: 'name' }));
    expect(ids(rows)).toEqual(copy);
  });
});

describe('sortRows', () => {
  it('newest keeps input order and ignores dir', () => {
    expect(ids(sortRows(rows, st({ sort: 'newest', dir: 'desc' })))).toEqual([5, 4, 3, 2, 1]);
  });

  it('name: case-insensitive, both directions', () => {
    expect(ids(sortRows(rows, st({ sort: 'name' })))).toEqual([4, 3, 2, 1, 5]);
    expect(ids(sortRows(rows, st({ sort: 'name', dir: 'desc' })))).toEqual([5, 1, 2, 3, 4]);
  });

  it('vertical/branch/owner: nulls last in BOTH directions, id-asc tie-break', () => {
    // vertical: Energy(5,3,1) Healthcare(4) missing(2)
    expect(ids(sortRows(rows, st({ sort: 'vertical' })))).toEqual([1, 3, 5, 4, 2]);
    expect(ids(sortRows(rows, st({ sort: 'vertical', dir: 'desc' })))).toEqual([4, 1, 3, 5, 2]);
    // branch: North(5) South(4,3) missing(1,2)
    expect(ids(sortRows(rows, st({ sort: 'branch' })))).toEqual([5, 3, 4, 1, 2]);
    expect(ids(sortRows(rows, st({ sort: 'branch', dir: 'desc' })))).toEqual([3, 4, 5, 1, 2]);
    // owner: Alpha(4,1) Bravo(5) missing(2,3)
    expect(ids(sortRows(rows, st({ sort: 'owner' })))).toEqual([1, 4, 5, 2, 3]);
    expect(ids(sortRows(rows, st({ sort: 'owner', dir: 'desc' })))).toEqual([5, 1, 4, 2, 3]);
  });

  it('impact: numeric, null last (0 is a real value, never coerced), id tie-break', () => {
    expect(ids(sortRows(rows, st({ sort: 'impact' })))).toEqual([1, 2, 3, 5, 4]);
    expect(ids(sortRows(rows, st({ sort: 'impact', dir: 'desc' })))).toEqual([3, 5, 2, 1, 4]);
  });

  it('pipeline: numeric, null last', () => {
    expect(ids(sortRows(rows, st({ sort: 'pipeline' })))).toEqual([1, 2, 3, 4, 5]);
    expect(ids(sortRows(rows, st({ sort: 'pipeline', dir: 'desc' })))).toEqual([4, 2, 3, 1, 5]);
  });

  it('granted: date asc/desc, null last', () => {
    expect(ids(sortRows(rows, st({ sort: 'granted' })))).toEqual([4, 1, 2, 5, 3]);
    expect(ids(sortRows(rows, st({ sort: 'granted', dir: 'desc' })))).toEqual([5, 1, 2, 4, 3]);
  });
});

describe('state helpers', () => {
  it('isFiltered', () => {
    expect(isFiltered(defaultNavState())).toBe(false);
    expect(isFiltered(st({ q: '   ' }))).toBe(false);
    expect(isFiltered(st({ q: 'a' }))).toBe(true);
    expect(isFiltered(st({ vertical: 'Energy' }))).toBe(true);
    expect(isFiltered(st({ branch: 'South' }))).toBe(true);
    expect(isFiltered(st({ owner: 'unassigned' }))).toBe(true);
    expect(isFiltered(st({ sort: 'name' }))).toBe(true);
    expect(isFiltered(st({ page: 3, pageSize: 40 }))).toBe(false);
  });

  it('countLabel carries filtered and authorized-total numbers', () => {
    expect(countLabel(12, 920)).toBe('12 of 920 accounts match');
  });

  it('reset preserves pageSize and view', () => {
    const r = resetNavState(st({ q: 'x', sort: 'name', dir: 'desc', page: 4, pageSize: 10, view: 'all' }));
    expect(r).toEqual({ ...defaultNavState('all'), pageSize: 10 });
  });

  it('filter/sort/pageSize patches reset page to 1; an explicit page patch does not', () => {
    const base = st({ page: 3 });
    expect(applyNavPatch(base, { q: 'a' }).page).toBe(1);
    expect(applyNavPatch(base, { sort: 'name' }).page).toBe(1);
    expect(applyNavPatch(base, { pageSize: 10 }).page).toBe(1);
    expect(applyNavPatch(base, { page: 2 }).page).toBe(2);
    expect(applyNavPatch(base, { q: '' }).page).toBe(3); // unchanged value
  });
});
