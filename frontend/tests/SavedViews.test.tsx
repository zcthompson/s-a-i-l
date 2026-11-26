/**
 * SavedViewsMenu + PortfolioFilterBar saved-views integration (synthetic fixtures only).
 * Partial-mocks the api module (repo pattern: vi.hoisted + vi.mock factory).
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, cleanup, waitFor, within } from '@testing-library/react';
import { useState } from 'react';
import { SavedViewsMenu, normalizeViewList, savedCreatedFlag } from '../src/components/SavedViewsMenu';
import { PortfolioFilterBar, navStateToViewParams, viewParamsToNavPatch } from '../src/components/PortfolioFilterBar';
import { applyNavPatch, defaultNavState } from '../src/lib/portfolioNav';
import type { NavDefaults, PortfolioNavRow, PortfolioNavState, SortKey } from '../src/lib/portfolioNav';
import type { SavedView } from '../src/types/savedViews';

afterEach(() => { cleanup(); vi.restoreAllMocks(); });

const { apiMock } = vi.hoisted(() => ({
  apiMock: {
    listSavedViews: vi.fn(),
    saveView: vi.fn(),
    deleteSavedView: vi.fn(),
    listVerticals: vi.fn(),
  },
}));
vi.mock('../src/lib/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../src/lib/api')>();
  return { ...actual, api: { ...actual.api, ...apiMock } };
});

const view = (over: Partial<SavedView> = {}): SavedView => ({
  id: 1, name: 'Energy north', surface: 'portfolio',
  params: { q: null, vertical: 'Energy', branch: 'North', owner: null, sort: 'name', dir: 'desc', page: '2', ps: null },
  schema_version: 1, created_at: '2026-11-01T00:00:00Z', updated_at: '2026-11-01T00:00:00Z', ...over,
});

const CURRENT = { q: 'synth', vertical: 'Healthcare', branch: null, owner: 'unassigned', sort: null, dir: null, page: null, ps: null };

function openMenu() {
  fireEvent.click(screen.getByRole('button', { name: 'Saved views' }));
}

describe('SavedViewsMenu', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    apiMock.listSavedViews.mockResolvedValue({ views: [view(), view({ id: 2, name: 'My rep book' })] });
    apiMock.listVerticals.mockResolvedValue({ verticals: [] });
  });

  it('fetches lazily on open and lists the caller view names for the surface', async () => {
    render(<SavedViewsMenu surface="portfolio" currentParams={CURRENT} onApply={vi.fn()} />);
    expect(apiMock.listSavedViews).not.toHaveBeenCalled();
    openMenu();
    expect(screen.getByText('Loading views…')).toBeTruthy();
    expect(await screen.findByRole('button', { name: 'Apply view Energy north' })).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Apply view My rep book' }).textContent).toBe('My rep book');
    expect(apiMock.listSavedViews).toHaveBeenCalledWith('portfolio');
  });

  it('tolerates the bare-array list shape too', async () => {
    apiMock.listSavedViews.mockResolvedValue([view({ id: 9, name: 'Bare' })]);
    render(<SavedViewsMenu surface="portfolio" currentParams={CURRENT} onApply={vi.fn()} />);
    openMenu();
    expect(await screen.findByRole('button', { name: 'Apply view Bare' })).toBeTruthy();
  });

  it('shows the exact empty state', async () => {
    apiMock.listSavedViews.mockResolvedValue({ views: [] });
    render(<SavedViewsMenu surface="portfolio" currentParams={CURRENT} onApply={vi.fn()} />);
    openMenu();
    expect((await screen.findByTestId('saved-views-empty')).textContent).toBe('No saved views yet.');
  });

  it('shows the exact error state and retries', async () => {
    apiMock.listSavedViews.mockRejectedValueOnce(new Error('boom'));
    render(<SavedViewsMenu surface="portfolio" currentParams={CURRENT} onApply={vi.fn()} />);
    openMenu();
    const err = await screen.findByTestId('saved-views-error');
    expect(err.textContent).toContain('Views unavailable. Try again.');
    expect(err.textContent).not.toContain('boom');
    fireEvent.click(within(err).getByRole('button', { name: 'Retry' }));
    expect(await screen.findByRole('button', { name: 'Apply view Energy north' })).toBeTruthy();
    expect(apiMock.listSavedViews).toHaveBeenCalledTimes(2);
  });

  it('load: onApply receives the stored params exactly and the menu closes', async () => {
    const onApply = vi.fn();
    render(<SavedViewsMenu surface="portfolio" currentParams={CURRENT} onApply={onApply} />);
    openMenu();
    fireEvent.click(await screen.findByRole('button', { name: 'Apply view Energy north' }));
    expect(onApply).toHaveBeenCalledTimes(1);
    expect(onApply.mock.calls[0][0]).toStrictEqual(view().params);
    expect(screen.queryByTestId('saved-views-panel')).toBeNull();
  });

  it('save: sends surface + trimmed name + the verbatim current params, then refreshes; created → "View saved."', async () => {
    apiMock.saveView.mockResolvedValue({ view: view({ id: 3, name: 'Fresh' }), created: true });
    render(<SavedViewsMenu surface="portfolio" currentParams={CURRENT} onApply={vi.fn()} />);
    openMenu();
    await screen.findByRole('button', { name: 'Apply view Energy north' });
    fireEvent.click(screen.getByRole('button', { name: 'Save current' }));
    const input = screen.getByRole('textbox', { name: 'View name' }) as HTMLInputElement;
    expect(input.maxLength).toBe(100);
    const submit = screen.getByRole('button', { name: 'Save' }) as HTMLButtonElement;
    expect(submit.disabled).toBe(true); // 0 chars
    fireEvent.change(input, { target: { value: '   ' } });
    expect(submit.disabled).toBe(true); // whitespace only
    fireEvent.change(input, { target: { value: '  Fresh  ' } });
    expect(submit.disabled).toBe(false);
    fireEvent.click(submit);
    await waitFor(() => expect(screen.getByTestId('saved-views-feedback').textContent).toBe('View saved.'));
    expect(apiMock.saveView).toHaveBeenCalledWith('portfolio', 'Fresh', CURRENT);
    expect(apiMock.saveView.mock.calls[0][2]).toBe(CURRENT); // the same object — no fabrication
    expect(apiMock.listSavedViews).toHaveBeenCalledTimes(2);
    expect(screen.queryByRole('textbox', { name: 'View name' })).toBeNull();
  });

  it('save: created:false → "View updated."', async () => {
    apiMock.saveView.mockResolvedValue({ view: view(), created: false });
    render(<SavedViewsMenu surface="portfolio" currentParams={CURRENT} onApply={vi.fn()} />);
    openMenu();
    fireEvent.click(await screen.findByRole('button', { name: 'Save current' }));
    fireEvent.change(screen.getByRole('textbox', { name: 'View name' }), { target: { value: 'energy NORTH' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save' }));
    await waitFor(() => expect(screen.getByTestId('saved-views-feedback').textContent).toBe('View updated.'));
  });

  it('save: a 422 message is rendered verbatim and the input stays open', async () => {
    apiMock.saveView.mockRejectedValue(new Error('Unknown filter parameter: view'));
    render(<SavedViewsMenu surface="portfolio" currentParams={CURRENT} onApply={vi.fn()} />);
    openMenu();
    fireEvent.click(await screen.findByRole('button', { name: 'Save current' }));
    fireEvent.change(screen.getByRole('textbox', { name: 'View name' }), { target: { value: 'Bad' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save' }));
    expect((await screen.findByTestId('saved-views-action-error')).textContent).toBe('Unknown filter parameter: view');
    expect(screen.getByRole('textbox', { name: 'View name' })).toBeTruthy();
    expect(screen.getByTestId('saved-views-feedback').textContent).toBe('');
  });

  it('delete: confirms, calls deleteSavedView(id) and refreshes the list', async () => {
    const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(true);
    apiMock.deleteSavedView.mockResolvedValue(undefined);
    render(<SavedViewsMenu surface="portfolio" currentParams={CURRENT} onApply={vi.fn()} />);
    openMenu();
    await screen.findByRole('button', { name: 'Apply view Energy north' });
    apiMock.listSavedViews.mockResolvedValue({ views: [view({ id: 2, name: 'My rep book' })] });
    fireEvent.click(screen.getByRole('button', { name: 'Delete view Energy north' }));
    expect(confirmSpy).toHaveBeenCalledWith('Delete saved view "Energy north"? This cannot be undone.');
    await waitFor(() => expect(screen.queryByRole('button', { name: 'Apply view Energy north' })).toBeNull());
    expect(apiMock.deleteSavedView).toHaveBeenCalledWith(1);
    expect(apiMock.listSavedViews).toHaveBeenCalledTimes(2);
    expect(screen.getByTestId('saved-views-feedback').textContent).toBe('View deleted.');
  });

  it('delete: a declined confirm makes no call', async () => {
    vi.spyOn(window, 'confirm').mockReturnValue(false);
    render(<SavedViewsMenu surface="portfolio" currentParams={CURRENT} onApply={vi.fn()} />);
    openMenu();
    fireEvent.click(await screen.findByRole('button', { name: 'Delete view Energy north' }));
    expect(apiMock.deleteSavedView).not.toHaveBeenCalled();
  });

  it('delete: a server error (e.g. 404) is rendered verbatim', async () => {
    vi.spyOn(window, 'confirm').mockReturnValue(true);
    apiMock.deleteSavedView.mockRejectedValue(new Error('View not found'));
    render(<SavedViewsMenu surface="portfolio" currentParams={CURRENT} onApply={vi.fn()} />);
    openMenu();
    fireEvent.click(await screen.findByRole('button', { name: 'Delete view Energy north' }));
    expect((await screen.findByTestId('saved-views-action-error')).textContent).toBe('View not found');
  });

  it('response normalizers', () => {
    expect(normalizeViewList({ views: [view()] })).toHaveLength(1);
    expect(normalizeViewList([])).toEqual([]);
    expect(() => normalizeViewList({})).toThrow();
    expect(savedCreatedFlag({ view: view(), created: true })).toBe(true);
    expect(savedCreatedFlag({ view: view(), created: false })).toBe(false);
    expect(savedCreatedFlag(view())).toBeNull();
  });
});

// ── PortfolioFilterBar regression + integration ────────────────────────────

const ROWS: PortfolioNavRow[] = [
  { id: 1, name: 'Synthetic Alpha', vertical: 'Energy', branch: 'North', primaryRep: 'Rep One', knownMetadata: true },
  { id: 2, name: 'Synthetic Bravo', vertical: 'Healthcare', branch: 'South', primaryRep: null, knownMetadata: true },
] as PortfolioNavRow[];
const SORTS: readonly SortKey[] = ['newest', 'name', 'vertical', 'branch', 'owner'];

function Harness({ defaults, spy }: { defaults?: NavDefaults; spy?: (s: PortfolioNavState) => void }) {
  const [state, setState] = useState<PortfolioNavState>(() => defaultNavState(null, defaults));
  spy?.(state);
  return (
    <PortfolioFilterBar
      rows={ROWS} state={state} filteredCount={ROWS.length} sortKeys={SORTS} defaults={defaults}
      onChange={patch => setState(s => applyNavPatch(s, patch))}
      onReset={() => setState(defaultNavState(null, defaults))}
    />
  );
}

describe('PortfolioFilterBar — saved views', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    apiMock.listVerticals.mockResolvedValue({ verticals: ['Energy', 'Healthcare'] });
    apiMock.listSavedViews.mockResolvedValue({ views: [view()] });
  });

  it('keeps every existing control and adds the Views affordance without fetching views up front', async () => {
    render(<Harness />);
    expect(screen.getByRole('searchbox', { name: 'Search customers' })).toBeTruthy();
    expect(screen.getByRole('combobox', { name: 'Filter by vertical' })).toBeTruthy();
    expect(screen.getByRole('combobox', { name: 'Filter by branch' })).toBeTruthy();
    expect(screen.getByRole('combobox', { name: 'Filter by owner' })).toBeTruthy();
    expect(screen.getByRole('combobox', { name: 'Sort by' })).toBeTruthy();
    expect(screen.getByTestId('portfolio-match-count').textContent).toBe('');
    expect(screen.queryByRole('button', { name: 'Reset filters' })).toBeNull();
    expect(screen.getByRole('button', { name: 'Saved views' })).toBeTruthy();
    await waitFor(() => expect(apiMock.listVerticals).toHaveBeenCalled());
    expect(apiMock.listSavedViews).not.toHaveBeenCalled();
  });

  it('search / filter / sort / reset behave as before', () => {
    render(<Harness />);
    fireEvent.change(screen.getByRole('searchbox', { name: 'Search customers' }), { target: { value: 'alpha' } });
    expect((screen.getByRole('searchbox', { name: 'Search customers' }) as HTMLInputElement).value).toBe('alpha');
    expect(screen.getByTestId('portfolio-match-count').textContent).not.toBe('');
    fireEvent.change(screen.getByRole('combobox', { name: 'Sort by' }), { target: { value: 'name' } });
    expect(screen.getByRole('button', { name: 'Sort direction: ascending' })).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: 'Reset filters' }));
    expect((screen.getByRole('searchbox', { name: 'Search customers' }) as HTMLInputElement).value).toBe('');
    expect(screen.queryByRole('button', { name: 'Reset filters' })).toBeNull();
  });

  it('saves the bar state as the URL params (null = default) verbatim', async () => {
    apiMock.saveView.mockResolvedValue({ view: view(), created: true });
    render(<Harness />);
    fireEvent.change(screen.getByRole('searchbox', { name: 'Search customers' }), { target: { value: 'alpha' } });
    fireEvent.change(screen.getByRole('combobox', { name: 'Filter by owner' }), { target: { value: 'unassigned' } });
    openMenu();
    fireEvent.click(await screen.findByRole('button', { name: 'Save current' }));
    fireEvent.change(screen.getByRole('textbox', { name: 'View name' }), { target: { value: 'Unowned alpha' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save' }));
    await waitFor(() => expect(apiMock.saveView).toHaveBeenCalled());
    expect(apiMock.saveView.mock.calls[0]).toStrictEqual(['portfolio', 'Unowned alpha',
      { q: 'alpha', vertical: null, branch: null, owner: 'unassigned', sort: null, dir: null, page: null, ps: null }]);
  });

  it('applying a view sets the full nav state through onChange (page honored, view untouched)', async () => {
    let latest: PortfolioNavState | null = null;
    render(<Harness spy={s => { latest = s; }} />);
    openMenu();
    fireEvent.click(await screen.findByRole('button', { name: 'Apply view Energy north' }));
    await waitFor(() => expect((screen.getByRole('combobox', { name: 'Filter by vertical' }) as HTMLSelectElement).value).toBe('Energy'));
    expect(latest).toMatchObject({ q: '', vertical: 'Energy', branch: 'North', owner: '', sort: 'name', dir: 'desc', page: 2, view: null });
    expect(screen.getByRole('button', { name: 'Reset filters' })).toBeTruthy();
  });

  it('param codec honours surface defaults and drops unknown keys', () => {
    const defaults: NavDefaults = { defaultSort: { sort: 'name', dir: 'asc' } };
    expect(navStateToViewParams(defaultNavState(null, defaults), defaults))
      .toStrictEqual({ q: null, vertical: null, branch: null, owner: null, sort: null, dir: null, page: null, ps: null });
    const patch = viewParamsToNavPatch({ vertical: 'Energy', sort: 'bogus', view: 'all', ps: '7' }, defaults);
    expect(patch).toStrictEqual({ q: '', vertical: 'Energy', branch: '', owner: '', sort: 'name', dir: 'asc', page: 1, pageSize: defaultNavState(null, defaults).pageSize });
  });
});
