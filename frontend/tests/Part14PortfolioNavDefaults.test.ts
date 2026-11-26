/** portfolioNav alias search + the additive per-surface defaults
 *  argument. Synthetic names only. Omitted defaults = the H2 behavior. */
import { describe, it, expect } from 'vitest';
import {
  defaultNavState, filterRows, isFiltered, navStateToSearchParams, parseNavState, resetNavState, searchText,
} from '../src/lib/portfolioNav';
import type { NavDefaults, PortfolioNavRow, PortfolioNavState } from '../src/lib/portfolioNav';

const params = (s: string) => new URLSearchParams(s);
const AZ: NavDefaults = { defaultSort: { sort: 'name', dir: 'asc' } };
const PS10: NavDefaults = { defaultPageSize: 10 };

const rows: PortfolioNavRow[] = [
  { id: 1, name: 'Quillon Partners', aliases: ['QP Group', 'Quill Holdings'], knownMetadata: true },
  { id: 2, name: 'Borealis', knownMetadata: true },
  { id: 3, name: 'Cobalt', aliases: [], knownMetadata: true },
];

describe('A7 alias search', () => {
  it('a query matching an alias finds the row (case-insensitive substring)', () => {
    const st = { ...defaultNavState(), q: 'qp grou' };
    expect(filterRows(rows, st).map(r => r.id)).toEqual([1]);
    expect(filterRows(rows, { ...st, q: 'HOLDINGS' }).map(r => r.id)).toEqual([1]);
  });

  it('a query matching the name still works', () => {
    expect(filterRows(rows, { ...defaultNavState(), q: 'borea' }).map(r => r.id)).toEqual([2]);
  });

  it('rows without aliases (missing or empty) are unchanged', () => {
    expect(searchText(rows[1])).toBe('borealis');
    expect(searchText(rows[2])).toBe('cobalt');
    expect(searchText({ id: 9, name: 'X', aliases: null })).toBe('x');
  });
});

describe('B1 defaultSort name/asc', () => {
  it('an unfiltered URL parses to name/asc', () => {
    const s = parseNavState(params('view=customers'), AZ);
    expect(s.sort).toBe('name');
    expect(s.dir).toBe('asc');
  });

  it('the surface default serializes to no nav params (unrelated params survive)', () => {
    const out = navStateToSearchParams(defaultNavState(null, AZ), params('view=customers&customer=X'), AZ);
    expect(out.toString()).toBe('view=customers&customer=X');
  });

  it('a non-default sort serializes and round-trips', () => {
    for (const patch of [{ sort: 'newest' as const }, { sort: 'name' as const, dir: 'desc' as const }, { sort: 'vertical' as const, dir: 'asc' as const }, { sort: 'branch' as const, dir: 'desc' as const }]) {
      const st: PortfolioNavState = { ...defaultNavState(null, AZ), ...patch };
      const sp = navStateToSearchParams(st, undefined, AZ);
      expect(sp.toString()).not.toBe('');
      expect(parseNavState(params(sp.toString()), AZ)).toEqual(st);
    }
    expect(navStateToSearchParams({ ...defaultNavState(null, AZ), sort: 'newest' }, undefined, AZ).toString()).toBe('sort=newest');
  });

  it('resetNavState returns to name/asc (pageSize preserved)', () => {
    const s = resetNavState({ ...defaultNavState(null, AZ), q: 'x', sort: 'branch', dir: 'desc', page: 4, pageSize: 40 }, AZ);
    expect(s).toEqual({ ...defaultNavState(null, AZ), pageSize: 40 });
  });

  it('isFiltered treats the surface default as unfiltered', () => {
    expect(isFiltered(defaultNavState(null, AZ), AZ)).toBe(false);
    expect(isFiltered({ ...defaultNavState(null, AZ), dir: 'desc' }, AZ)).toBe(true);
    expect(isFiltered({ ...defaultNavState(null, AZ), sort: 'newest' }, AZ)).toBe(true);
  });
});

describe('defaultPageSize 10', () => {
  it('parses to 10 when ps is absent; ps still overrides (clamped to PAGE_SIZES)', () => {
    expect(parseNavState(params(''), PS10).pageSize).toBe(10);
    expect(parseNavState(params('ps=40'), PS10).pageSize).toBe(40);
    expect(parseNavState(params('ps=7'), PS10).pageSize).toBe(10);
  });

  it('serializes 10 to no ps and 20 to ps=20; reset preserves the size', () => {
    expect(navStateToSearchParams(defaultNavState(null, PS10), undefined, PS10).toString()).toBe('');
    expect(navStateToSearchParams({ ...defaultNavState(null, PS10), pageSize: 20 }, undefined, PS10).toString()).toBe('ps=20');
    expect(resetNavState({ ...defaultNavState(null, PS10), q: 'x' }, PS10).pageSize).toBe(10);
  });
});

describe('omitted defaults = H2 behavior', () => {
  it('parse/serialize/reset/isFiltered are unchanged', () => {
    const s = parseNavState(params(''));
    expect(s).toEqual(defaultNavState());
    expect(s.sort).toBe('newest');
    expect(s.pageSize).toBe(20);
    expect(parseNavState(params(''), {})).toEqual(s);
    expect(navStateToSearchParams({ ...s, sort: 'name' }).toString()).toBe('sort=name');
    expect(navStateToSearchParams({ ...s, sort: 'name', dir: 'desc' }).toString()).toBe('sort=name&dir=desc');
    expect(navStateToSearchParams({ ...s, pageSize: 10 }).toString()).toBe('ps=10');
    expect(resetNavState({ ...s, sort: 'name', q: 'x' })).toEqual(defaultNavState());
    expect(isFiltered({ ...s, sort: 'name' })).toBe(true);
    expect(isFiltered(s)).toBe(false);
  });
});
