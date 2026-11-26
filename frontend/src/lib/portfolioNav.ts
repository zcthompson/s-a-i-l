/**
 * portfolioNav — pure search / filter / sort / count / URL-state logic for the
 * portfolio surfaces (HomeDashboard table, MyDashboard list). H2.
 *
 * Single source of truth: no React state, no api access. Everything runs over
 * the COMPLETE already-authorized list that the backend returned; local
 * pagination slices the result afterwards. Frontend filtering is a navigation
 * aid, never an authorization boundary.
 */
import { DEFAULT_PAGE_SIZE, PAGE_SIZES } from '../components/CustomerListPager';

export interface PortfolioNavRow {
  id: number;
  name: string;
  description?: string | null;
  vertical?: string | null;
  branch?: string | null;
  salesArea?: string | null;
  primarySubsidiary?: string | null;
  primaryRep?: string | null;
  managerName?: string | null;
  /** Customer alias tags (raw strings); searched like the other text fields. */
  aliases?: string[] | null;
  /** True when the row's metadata came from the customer-list payload; false =
   *  metadata unavailable (unknown is NOT "unassigned" and matches no filter). */
  knownMetadata?: boolean;
  totalImpact?: number | null;
  pipelineAcv?: number | null;
  grantedAt?: string | null;
}

export const SORT_KEYS = ['newest', 'name', 'vertical', 'branch', 'owner', 'impact', 'pipeline', 'granted'] as const;
export type SortKey = (typeof SORT_KEYS)[number];
export type SortDir = 'asc' | 'desc';
export type NavView = 'my' | 'all';

export interface PortfolioNavState {
  q: string;
  vertical: string;
  branch: string;
  /** '' (all) | 'unassigned' | exact display name */
  owner: string;
  sort: SortKey;
  dir: SortDir;
  page: number;
  pageSize: number;
  view: NavView | null;
}

export const UNASSIGNED = 'unassigned';

/** Per-surface defaults (all optional; omitted = the H2 defaults: newest/asc,
 *  DEFAULT_PAGE_SIZE, no view). A state equal to the surface defaults
 *  serializes to no nav params. */
export interface NavDefaults {
  defaultView?: NavView;
  defaultSort?: { sort: SortKey; dir: SortDir };
  defaultPageSize?: number;
}

const surfaceSort = (opts: NavDefaults) => opts.defaultSort ?? { sort: 'newest' as SortKey, dir: 'asc' as SortDir };
const surfacePageSize = (opts: NavDefaults) =>
  opts.defaultPageSize !== undefined && (PAGE_SIZES as readonly number[]).includes(opts.defaultPageSize) ? opts.defaultPageSize : DEFAULT_PAGE_SIZE;

export function defaultNavState(defaultView: NavView | null = null, opts: NavDefaults = {}): PortfolioNavState {
  const { sort, dir } = surfaceSort(opts);
  return { q: '', vertical: '', branch: '', owner: '', sort, dir, page: 1, pageSize: surfacePageSize(opts), view: defaultView };
}

// ── URL codec ───────────────────────────────────────────────────────────────

export function parseNavState(
  searchParams: URLSearchParams,
  opts: NavDefaults = {},
): PortfolioNavState {
  const defSort = surfaceSort(opts);
  const defPageSize = surfacePageSize(opts);
  const sortRaw = searchParams.get('sort');
  const sort = (SORT_KEYS as readonly string[]).includes(sortRaw ?? '') ? (sortRaw as SortKey) : defSort.sort;
  const dirRaw = searchParams.get('dir');
  // An absent dir means the surface default dir for the default sort, else asc.
  const dir: SortDir = dirRaw === 'desc' ? 'desc' : dirRaw === null && sort === defSort.sort ? defSort.dir : 'asc';
  const pageRaw = searchParams.get('page');
  const pageNum = pageRaw !== null && /^\d+$/.test(pageRaw) ? parseInt(pageRaw, 10) : 1;
  const psRaw = searchParams.get('ps');
  const psNum = psRaw !== null && /^\d+$/.test(psRaw) ? parseInt(psRaw, 10) : defPageSize;
  const viewRaw = searchParams.get('view');
  return {
    q: searchParams.get('q') ?? '',
    vertical: searchParams.get('vertical') ?? '',
    branch: searchParams.get('branch') ?? '',
    owner: searchParams.get('owner') ?? '',
    sort,
    dir,
    page: pageNum >= 1 ? pageNum : 1,
    pageSize: (PAGE_SIZES as readonly number[]).includes(psNum) ? psNum : defPageSize,
    view: viewRaw === 'my' || viewRaw === 'all' ? viewRaw : (opts.defaultView ?? null),
  };
}

/**
 * Serialize onto `base` (unrelated params survive). Defaults are DELETED so the
 * default state yields no nav params at all.
 *
 * `view` caveat: the route's `?view=` param is ALSO the app's active-view key
 * (`?view=dashboard`). A null `state.view` therefore leaves `view` untouched in
 * `base`; only a non-null 'my'|'all' is written (and deleted when it equals
 * `opts.defaultView`).
 */
export function navStateToSearchParams(
  state: PortfolioNavState,
  base?: URLSearchParams,
  opts: NavDefaults = {},
): URLSearchParams {
  const defSort = surfaceSort(opts);
  const out = new URLSearchParams(base ? base.toString() : undefined);
  const put = (key: string, value: string, isDefault: boolean) => {
    if (isDefault) out.delete(key);
    else out.set(key, value);
  };
  put('q', state.q, state.q.trim() === '');
  put('vertical', state.vertical, state.vertical === '');
  put('branch', state.branch, state.branch === '');
  put('owner', state.owner, state.owner === '');
  put('sort', state.sort, state.sort === defSort.sort);
  put('dir', state.dir, state.sort === 'newest' || state.dir === (state.sort === defSort.sort ? defSort.dir : 'asc'));
  put('page', String(state.page), state.page <= 1);
  put('ps', String(state.pageSize), state.pageSize === surfacePageSize(opts));
  if (state.view !== null) put('view', state.view, state.view === opts.defaultView);
  return out;
}

// ── Filtering ───────────────────────────────────────────────────────────────

export function searchText(row: PortfolioNavRow): string {
  return [row.name, row.description, row.vertical, row.branch, row.salesArea, row.primarySubsidiary, row.primaryRep, row.managerName, ...(row.aliases ?? [])]
    .filter((v): v is string => typeof v === 'string' && v !== '')
    .join('\n')
    .toLowerCase();
}

export function matchesText(row: PortfolioNavRow, q: string): boolean {
  const needle = q.trim().toLowerCase();
  return needle === '' || searchText(row).includes(needle);
}

export function matchesMetadata(row: PortfolioNavRow, state: Pick<PortfolioNavState, 'vertical' | 'branch' | 'owner'>): boolean {
  const anyMeta = state.vertical !== '' || state.branch !== '' || state.owner !== '';
  if (!anyMeta) return true;
  if (row.knownMetadata === false) return false;
  if (state.vertical !== '' && row.vertical !== state.vertical) return false;
  if (state.branch !== '' && row.branch !== state.branch) return false;
  if (state.owner === UNASSIGNED) return row.knownMetadata === true && (row.primaryRep ?? null) === null;
  if (state.owner !== '' && row.primaryRep !== state.owner) return false;
  return true;
}

export function filterRows<T extends PortfolioNavRow>(rows: readonly T[], state: PortfolioNavState): T[] {
  return rows.filter(r => matchesText(r, state.q) && matchesMetadata(r, state));
}

// ── Sorting ─────────────────────────────────────────────────────────────────

type Missing = null | undefined;
const isMissing = (v: unknown): v is Missing => v === null || v === undefined || v === '' || (typeof v === 'number' && Number.isNaN(v));

/** Compare with nulls LAST regardless of direction, then id ascending. */
function compareBy<T extends PortfolioNavRow, V>(
  get: (r: T) => V | Missing,
  cmp: (a: V, b: V) => number,
  dir: SortDir,
): (a: T, b: T) => number {
  const sign = dir === 'desc' ? -1 : 1;
  return (a, b) => {
    const va = get(a);
    const vb = get(b);
    const ma = isMissing(va);
    const mb = isMissing(vb);
    if (ma && mb) return a.id - b.id;
    if (ma) return 1;
    if (mb) return -1;
    const c = cmp(va as V, vb as V) * sign;
    return c !== 0 ? c : a.id - b.id;
  };
}

export const compareText = (a: string, b: string): number => a.toLowerCase().localeCompare(b.toLowerCase());
export const compareNumber = (a: number, b: number): number => a - b;

const dateValue = (s?: string | null): number | null => {
  if (!s) return null;
  const t = Date.parse(s);
  return Number.isNaN(t) ? null : t;
};

export function sortRows<T extends PortfolioNavRow>(rows: readonly T[], state: Pick<PortfolioNavState, 'sort' | 'dir'>): T[] {
  const { sort, dir } = state;
  // 'newest' IS the payload order (created_at desc, id desc); dir is ignored.
  if (sort === 'newest') return rows.slice();
  let cmp: (a: T, b: T) => number;
  switch (sort) {
    case 'name': cmp = compareBy<T, string>(r => r.name, compareText, dir); break;
    case 'vertical': cmp = compareBy<T, string>(r => r.vertical, compareText, dir); break;
    case 'branch': cmp = compareBy<T, string>(r => r.branch, compareText, dir); break;
    case 'owner': cmp = compareBy<T, string>(r => r.primaryRep, compareText, dir); break;
    case 'impact': cmp = compareBy<T, number>(r => r.totalImpact, compareNumber, dir); break;
    case 'pipeline': cmp = compareBy<T, number>(r => r.pipelineAcv, compareNumber, dir); break;
    case 'granted': cmp = compareBy<T, number>(r => dateValue(r.grantedAt), compareNumber, dir); break;
    default: return rows.slice();
  }
  return rows.slice().sort(cmp);
}

// ── State helpers ───────────────────────────────────────────────────────────

export function isFiltered(state: PortfolioNavState, opts: NavDefaults = {}): boolean {
  const defSort = surfaceSort(opts);
  const sortChanged = state.sort !== defSort.sort || (defSort.sort !== 'newest' && state.dir !== defSort.dir);
  return state.q.trim() !== '' || state.vertical !== '' || state.branch !== '' || state.owner !== '' || sortChanged;
}

export function countLabel(filtered: number, total: number): string {
  return `${filtered} of ${total} accounts match`;
}

/** Reset filters/sort/page (sort to the surface default); PRESERVES pageSize and view. */
export function resetNavState(state: PortfolioNavState, opts: NavDefaults = {}): PortfolioNavState {
  return { ...defaultNavState(state.view, opts), pageSize: state.pageSize };
}

/** Apply a partial update; any filter/sort/pageSize change returns to page 1
 *  unless the patch itself sets `page`. */
export function applyNavPatch(state: PortfolioNavState, patch: Partial<PortfolioNavState>): PortfolioNavState {
  const next = { ...state, ...patch };
  if (patch.page === undefined) {
    const resets: (keyof PortfolioNavState)[] = ['q', 'vertical', 'branch', 'owner', 'sort', 'dir', 'pageSize'];
    if (resets.some(k => k in patch && patch[k] !== state[k])) next.page = 1;
  }
  return next;
}

/** Distinct, case-insensitively sorted non-empty values. */
export function distinctValues(values: readonly (string | null | undefined)[]): string[] {
  return Array.from(new Set(values.filter((v): v is string => typeof v === 'string' && v !== ''))).sort(compareText);
}

/** Clamp a requested page into [1, lastPage]. */
export function clampPage(page: number, total: number, pageSize: number): number {
  return Math.min(Math.max(1, page), Math.max(1, Math.ceil(total / pageSize)));
}

/** Human summary of the active text/metadata filters (for the no-match state). */
export function activeFilterSummary(state: Pick<PortfolioNavState, 'q' | 'vertical' | 'branch' | 'owner'>): string {
  const parts = [
    state.q.trim() && `search "${state.q.trim()}"`,
    state.vertical && `vertical ${state.vertical}`,
    state.branch && `branch ${state.branch}`,
    state.owner && `owner ${state.owner === UNASSIGNED ? 'Unassigned' : state.owner}`,
  ].filter(Boolean);
  return parts.length ? `No customers match ${parts.join(', ')}.` : 'No customers match the current view.';
}
