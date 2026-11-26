import { act, cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import AccountSearchPanel from '../src/components/AccountSearchPanel';
import type { AccountSearchResponse } from '../src/types/accountSearch';

const { searchAccount } = vi.hoisted(() => ({ searchAccount: vi.fn() }));
vi.mock('../src/lib/api', async importOriginal => {
  const original = await importOriginal<typeof import('../src/lib/api')>();
  return { ...original, api: { ...original.api, searchAccount } };
});

function response(query = 'needle'): AccountSearchResponse {
  return { customer_id: 1, query, counts: { deal: 0, use_case: 0, note: 0, contact: 0, activity: 0, task: 0, technology: 0, strategy: 0, knowledge: 0 }, results: [], truncated: false };
}
function type(query: string) {
  fireEvent.change(screen.getByRole('searchbox'), { target: { value: query } });
}
async function debounce() {
  await act(async () => { await vi.advanceTimersByTimeAsync(300); });
}

beforeEach(() => { vi.useFakeTimers(); searchAccount.mockReset(); searchAccount.mockResolvedValue(response()); });
afterEach(() => { cleanup(); vi.useRealTimers(); });

describe('AccountSearchPanel', () => {
  it('gates one character and debounces rapid input, trimming the request', async () => {
    render(<AccountSearchPanel customerId={1} />);
    expect(screen.queryByText('Search this account (2+ characters).')).toBeNull();
    type('n');
    await debounce();
    expect(searchAccount).not.toHaveBeenCalled();
    type('ne');
    await act(async () => { await vi.advanceTimersByTimeAsync(299); });
    expect(searchAccount).not.toHaveBeenCalled();
    type(' needle ');
    expect(screen.getByText('Searching…')).toBeTruthy();
    await debounce();
    expect(searchAccount).toHaveBeenCalledExactlyOnceWith(1, 'needle');
  });

  it('groups results with counts, renders snippets as text and calls onSelect', async () => {
    const data = response();
    data.counts.note = 1; data.counts.contact = 1;
    data.results = [
      { module: 'note', id: 7, title: 'Synthetic note', snippet: '<img src=x onerror=alert(1)>', timestamp: '2026-11-01', date_only: true },
      { module: 'contact', id: 8, title: 'Synthetic contact', snippet: 'Plain contact', timestamp: null, date_only: false },
    ];
    searchAccount.mockResolvedValue(data);
    const onSelect = vi.fn();
    const { container } = render(<AccountSearchPanel customerId={1} onSelect={onSelect} />);
    type('needle'); await debounce();
    for (const label of ['Notes', 'Contacts']) {
      const group = within(screen.getByRole('region', { name: label }));
      expect(group.getByLabelText(`${label} count`).textContent).toBe('1');
    }
    expect(screen.getByText('<img src=x onerror=alert(1)>')).toBeTruthy();
    expect(container.querySelector('img')).toBeNull();
    expect(screen.getByText('2026-11-01').getAttribute('datetime')).toBe('2026-11-01');
    fireEvent.click(screen.getByRole('button', { name: 'Synthetic note' }));
    expect(onSelect).toHaveBeenCalledWith('note', 7);
  });

  it('shows the exact no matches message', async () => {
    render(<AccountSearchPanel customerId={1} />);
    type('needle'); await debounce();
    expect(screen.getByText("No matches for 'needle'.")).toBeTruthy();
  });

  it('explains capped section counts when results are dense across modules', async () => {
    const data = response();
    const groups = [
      ['note', 'Notes'], ['contact', 'Contacts'], ['activity', 'Activities'],
      ['task', 'Tasks'], ['technology', 'Technology'], ['strategy', 'Strategy'], ['knowledge', 'Knowledge'],
    ] as const;
    for (const [module] of groups) {
      const count = module === 'strategy' ? 1 : 10;
      data.counts[module] = count;
      for (let i = 0; i < count; i++) {
        data.results.push({ module, id: i + 1, title: `${module} ${i}`, snippet: 'needle', timestamp: null, date_only: false });
      }
    }
    data.truncated = true;
    searchAccount.mockResolvedValue(data);
    render(<AccountSearchPanel customerId={1} />);
    type('needle'); await debounce();
    expect(screen.getByText('Showing up to 10 matches per section. Counts show displayed matches; more matches may exist.')).toBeTruthy();
    for (const [module, label] of groups) {
      const group = within(screen.getByRole('region', { name: label }));
      expect(group.getByLabelText(`${label} count`).textContent).toBe(module === 'strategy' ? '1' : '10');
      expect(group.getAllByRole('button')).toHaveLength(module === 'strategy' ? 1 : 10);
    }
  });

  it('shows an error and retries the same search', async () => {
    searchAccount.mockRejectedValueOnce(new Error('synthetic failure')).mockResolvedValueOnce(response());
    render(<AccountSearchPanel customerId={1} />);
    type('needle'); await debounce();
    expect(screen.getByText(/Search unavailable. Try again./)).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: 'Retry' }));
    await debounce();
    expect(searchAccount).toHaveBeenCalledTimes(2);
    expect(screen.getByText("No matches for 'needle'.")).toBeTruthy();
  });

  it('ignores a superseded response arriving after the newest result', async () => {
    let resolveOld!: (data: AccountSearchResponse) => void;
    searchAccount.mockImplementationOnce(() => new Promise<AccountSearchResponse>(resolve => { resolveOld = resolve; }))
      .mockResolvedValueOnce(response('newest'));
    render(<AccountSearchPanel customerId={1} />);
    type('older'); await debounce();
    type('newest'); await debounce();
    await act(async () => { resolveOld(response('older')); });
    expect(screen.getByText("No matches for 'newest'.")).toBeTruthy();
    expect(screen.queryByText("No matches for 'older'.")).toBeNull();
  });

  it('invalidates pending responses immediately when input becomes too short', async () => {
    let resolveOld!: (data: AccountSearchResponse) => void;
    searchAccount.mockImplementationOnce(() => new Promise<AccountSearchResponse>(resolve => { resolveOld = resolve; }));
    render(<AccountSearchPanel customerId={1} />);
    type('older'); await debounce(); type('x');
    await act(async () => { resolveOld(response('older')); });
    expect(screen.queryByText('Search this account (2+ characters).')).toBeNull();
    expect(screen.queryByText("No matches for 'older'.")).toBeNull();
  });
});
