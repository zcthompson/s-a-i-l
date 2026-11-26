/**
 * CustomerListPager + useCustomerPager — page sizes 10/20/40/100, default 20.
 */
import { describe, it, expect, afterEach } from 'vitest';
import { render, screen, fireEvent, cleanup } from '@testing-library/react';
import { CustomerListPager, useCustomerPager } from '../src/components/CustomerListPager';

afterEach(() => { cleanup(); });

const ITEMS = Array.from({ length: 55 }, (_, i) => `Customer ${i + 1}`);

function Harness({ items = ITEMS }: { items?: string[] }) {
  const pager = useCustomerPager(items);
  return (
    <div>
      <CustomerListPager {...pager.pagerProps} />
      <ul data-testid="rows">
        {pager.visible.map(n => <li key={n}>{n}</li>)}
      </ul>
    </div>
  );
}

const rows = () => screen.getByTestId('rows').querySelectorAll('li');
const next = () => screen.getByRole('button', { name: 'Next page' }) as HTMLButtonElement;
const prev = () => screen.getByRole('button', { name: 'Previous page' }) as HTMLButtonElement;
const size = () => screen.getByLabelText('Page size') as HTMLSelectElement;

describe('CustomerListPager', () => {
  it('defaults to 20 per page', () => {
    render(<Harness />);
    expect(rows()).toHaveLength(20);
    expect(screen.getByText('Showing 1–20 of 55')).toBeTruthy();
  });

  it('page size 100 shows everything on a single page', () => {
    render(<Harness />);
    fireEvent.change(size(), { target: { value: '100' } });
    expect(rows()).toHaveLength(55);
    expect(screen.getByText('Showing 1–55 of 55')).toBeTruthy();
    expect(next().disabled).toBe(true);
    expect(prev().disabled).toBe(true);
  });

  it('page size 10 then Next shows items 11-20', () => {
    render(<Harness />);
    fireEvent.change(size(), { target: { value: '10' } });
    expect(rows()).toHaveLength(10);
    fireEvent.click(next());
    expect(rows()).toHaveLength(10);
    expect(rows()[0].textContent).toBe('Customer 11');
    expect(rows()[9].textContent).toBe('Customer 20');
    expect(screen.getByText('Showing 11–20 of 55')).toBeTruthy();
  });

  it('changing page size resets to page 1', () => {
    render(<Harness />);
    fireEvent.change(size(), { target: { value: '10' } });
    fireEvent.click(next());
    fireEvent.click(next());
    expect(screen.getByText('Showing 21–30 of 55')).toBeTruthy();
    fireEvent.change(size(), { target: { value: '40' } });
    expect(screen.getByText('Showing 1–40 of 55')).toBeTruthy();
    expect(rows()[0].textContent).toBe('Customer 1');
  });

  it('disables Prev on the first page and Next on the last page', () => {
    render(<Harness />);
    expect(prev().disabled).toBe(true);
    expect(next().disabled).toBe(false);
    fireEvent.click(next());
    fireEvent.click(next());
    expect(screen.getByText('Showing 41–55 of 55')).toBeTruthy();
    expect(rows()).toHaveLength(15);
    expect(next().disabled).toBe(true);
    expect(prev().disabled).toBe(false);
  });

  it('clamps the page when the list shrinks', () => {
    const { rerender } = render(<Harness />);
    fireEvent.click(next());
    fireEvent.click(next());
    rerender(<Harness items={ITEMS.slice(0, 5)} />);
    expect(screen.getByText('Showing 1–5 of 5')).toBeTruthy();
    expect(rows()).toHaveLength(5);
  });

  it('is accessible: labelled page-size select, live range text, size options', () => {
    render(<Harness />);
    const sel = size();
    expect(Array.from(sel.options).map(o => o.value)).toEqual(['10', '20', '40', '100']);
    expect(sel.value).toBe('20');
    const range = screen.getByText(/Showing 1–20 of 55/);
    expect(range.getAttribute('aria-live')).toBe('polite');
  });

  it('reads "Showing 1 of 1" for a single item', () => {
    render(<Harness items={['Only']} />);
    expect(screen.getByText('Showing 1 of 1')).toBeTruthy();
  });
});
