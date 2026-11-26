import { act, cleanup, fireEvent, render, renderHook, screen, waitFor } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { MemoryRouter, useNavigate } from 'react-router-dom';
import { useCustomerRecord } from '../src/lib/useCustomerRecord';
import { SelectedCustomerRecord, loadCustomerRecord } from '../src/components/SelectedCustomerRecord';
const { getContact } = vi.hoisted(() => ({ getContact: vi.fn() }));
vi.mock('../src/lib/api', () => ({ api: { getContact } }));
afterEach(() => { cleanup(); vi.resetAllMocks(); });
it('restores exact record via URL/history and hides it for another customer', () => {
  const wrapper = ({ children }: any) => <MemoryRouter initialEntries={['/?area=contacts']}>{children}</MemoryRouter>;
  const { result, rerender } = renderHook(({ customer }) => ({ ...useCustomerRecord(customer, 'contacts'), navigate: useNavigate() }), { wrapper, initialProps: { customer: 7 } });
  act(() => result.current.select('contact', 42));
  expect(result.current.record).toEqual({ module: 'contact', id: 42, customerId: 7 });
  act(() => result.current.clear());
  expect(result.current.record).toBeNull();
  act(() => result.current.navigate(-1));
  expect(result.current.record?.id).toBe(42);
  rerender({ customer: 8 });
  expect(result.current.record).toBeNull();
});
it('opens a direct link only in its owning section', () => {
  const wrapper = ({ children }: any) => <MemoryRouter initialEntries={['/?record_module=contact&record_id=42&record_customer=7']}>{children}</MemoryRouter>;
  const { result, rerender } = renderHook(({ area }) => useCustomerRecord(7, area), { wrapper, initialProps: { area: 'contacts' } });
  expect(result.current.record?.id).toBe(42);
  rerender({ area: 'tasks' });
  expect(result.current.record).toBeNull();
});
it('rejects an authorized record belonging to another account', async () => {
  getContact.mockResolvedValue({ id: 42, customer_id: 8, display_name: 'Other customer' });
  await expect(loadCustomerRecord({ module: 'contact', id: 42, customerId: 7 })).rejects.toThrow('Record unavailable');
});
it('offers recovery for a deleted record and displays the exact record on retry', async () => {
  getContact.mockRejectedValueOnce(new Error('404')).mockResolvedValueOnce({ id: 42, customer_id: 7, display_name: 'Selected buyer', email: 'buyer@example.test' });
  render(<SelectedCustomerRecord selection={{ module: 'contact', id: 42, customerId: 7 }} onClose={vi.fn()} />);
  await screen.findByRole('alert');
  fireEvent.click(screen.getByText('Retry record'));
  await screen.findByText('buyer@example.test');
  await waitFor(() => expect(document.activeElement?.textContent).toBe('Selected buyer'));
});
