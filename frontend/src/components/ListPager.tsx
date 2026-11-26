/**
 * ListPager — shared in-memory pagination control (presentational only).
 *
 * `useListPager` slices an in-memory list at caller-chosen page sizes
 * (10/20/50/100 by default); `ListPager` renders the single compact control
 * line (range text, page-size select, Prev/Next). No data fetching — the
 * caller passes the full list and renders `visible`.
 *
 * `CustomerListPager` (the 0.2.8 customer listings) keeps its own
 * 10/20/40/100 sizes; this is the general control used by other in-memory
 * lists such as the Customer Ownership queue.
 */
import { useState } from 'react';
import type { CSSProperties } from 'react';

export const DEFAULT_PAGE_SIZES = [10, 20, 50, 100] as const;
export const DEFAULT_PAGE_SIZE = 20;

export interface ListPagerProps {
  total: number;
  page: number;
  start: number;
  end: number;
  pageSize: number;
  pageSizes: readonly number[];
  onPageChange: (page: number) => void;
  onPageSizeChange: (size: number) => void;
  /** Accessible label for the page-size select. */
  ariaLabel?: string;
}

export function useListPager<T>(
  items: T[],
  pageSizes: readonly number[] = DEFAULT_PAGE_SIZES,
  initialSize: number = DEFAULT_PAGE_SIZE,
) {
  const validSizes = pageSizes;
  const [pageSize, setPageSizeState] = useState<number>(
    validSizes.includes(initialSize) ? initialSize : DEFAULT_PAGE_SIZE,
  );
  const [rawPage, setRawPage] = useState(1);

  const total = items.length;
  const lastPage = Math.max(1, Math.ceil(total / pageSize));
  // Clamp on read so a shrinking list never leaves the page overrunning.
  const page = Math.min(Math.max(1, rawPage), lastPage);
  const start = total === 0 ? 0 : (page - 1) * pageSize + 1;
  const end = Math.min(page * pageSize, total);
  const visible = items.slice((page - 1) * pageSize, page * pageSize);

  const setPage = (p: number) => setRawPage(Math.min(Math.max(1, p), lastPage));
  const setPageSize = (size: number) => {
    setPageSizeState(size);
    setRawPage(1);
  };

  const pagerProps: ListPagerProps = {
    total, page, start, end, pageSize, pageSizes: validSizes,
    onPageChange: setPage,
    onPageSizeChange: setPageSize,
  };

  return { page, pageSize, visible, setPageSize, setPage, total, start, end, pagerProps };
}

const barStyle: CSSProperties = {
  display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '12px',
  flexWrap: 'wrap', padding: '8px 0', fontSize: '0.8rem', color: 'var(--neutral-500)',
};
const controlStyle: CSSProperties = {
  padding: '3px 8px', fontSize: '0.8rem', color: 'var(--neutral-700)',
  background: 'var(--neutral-0)', border: '1px solid var(--divider)',
  borderRadius: 'var(--radius-sm)', cursor: 'pointer',
};

export function ListPager({
  total, page, start, end, pageSize, pageSizes, onPageChange, onPageSizeChange,
  ariaLabel = 'Page size',
}: ListPagerProps) {
  const lastPage = Math.max(1, Math.ceil(total / pageSize));
  const rangeText = total === 1 ? 'Showing 1 of 1' : `Showing ${start}–${end} of ${total}`;
  const disabledStyle = (disabled: boolean): CSSProperties =>
    disabled ? { ...controlStyle, opacity: 0.5, cursor: 'not-allowed' } : controlStyle;

  return (
    <div style={barStyle}>
      <span aria-live="polite">{rangeText}</span>
      <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
        <select
          aria-label={ariaLabel}
          value={pageSize}
          onChange={e => onPageSizeChange(Number(e.target.value))}
          style={controlStyle}
        >
          {pageSizes.map(s => <option key={s} value={s}>{s}</option>)}
        </select>
        <button
          type="button"
          aria-label="Previous page"
          disabled={page <= 1}
          onClick={() => onPageChange(page - 1)}
          style={disabledStyle(page <= 1)}
        >
          Prev
        </button>
        <button
          type="button"
          aria-label="Next page"
          disabled={page >= lastPage}
          onClick={() => onPageChange(page + 1)}
          style={disabledStyle(page >= lastPage)}
        >
          Next
        </button>
      </div>
    </div>
  );
}

export default ListPager;
