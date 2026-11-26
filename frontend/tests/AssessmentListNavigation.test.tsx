import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, useLocation, useNavigate } from 'react-router-dom';
import { AssessmentList } from '../src/pages/AssessmentList';

const { apiMock } = vi.hoisted(() => ({ apiMock: { list: vi.fn(), listCustomers: vi.fn() } }));
vi.mock('../src/lib/api', () => ({ api: apiMock }));
const record = (id: number) => ({ id, title: `Assessment ${id}`, description: '', customer_id: 5, status: 'active', created_at: '2026-01-01T00:00:00Z', overall_score: null });
function Probe() {
  const location = useLocation();
  const navigate = useNavigate();
  return <><output data-testid="url">{location.search}</output><button onClick={() => navigate(-1)}>Back</button><button onClick={() => navigate(1)}>Forward</button></>;
}
const params = () => new URLSearchParams(screen.getByTestId('url').textContent ?? '');
const mount = (url: string) => render(<MemoryRouter initialEntries={[url]}><Probe /><AssessmentList onSelect={() => {}} onScore={() => {}} onEdit={() => {}} /></MemoryRouter>);
beforeEach(() => {
  apiMock.list.mockReset().mockImplementation(({ skip }: { skip: number }) => Promise.resolve(skip === 0 ? Array.from({ length: 50 }, (_, i) => record(i + 1)) : [record(51)]));
  apiMock.listCustomers.mockReset().mockResolvedValue([{ id: 5, name: 'Accessible customer' }]);
});
afterEach(cleanup);

describe('assessment list navigation', () => {
  it('restores a direct link with applied filters, sort and page', async () => {
    mount('/?view=assessment-list&as_q=cloud&as_status=active&as_sort=title&as_customer=5&as_page=2&extra=1');
    await screen.findByText('Assessment 51');
    expect(apiMock.list).toHaveBeenCalledWith({ skip: 50, limit: 50, sort: 'title', status: 'active', search: 'cloud', customer_id: '5' });
    expect((screen.getByLabelText('Search assessments by title or description') as HTMLInputElement).value).toBe('cloud');
    expect((screen.getByLabelText('Filter by status') as HTMLSelectElement).value).toBe('active');
    expect(params().get('as_page')).toBe('2');
    expect(params().get('extra')).toBe('1');
  });

  it('tracks applied changes and restores them with back and forward', async () => {
    mount('/?view=assessment-list&extra=1');
    await screen.findByText('Assessment 1');
    fireEvent.change(screen.getByLabelText('Filter by status'), { target: { value: 'active' } });
    await waitFor(() => expect(params().get('as_status')).toBe('active'));
    fireEvent.change(screen.getByLabelText('Sort assessments'), { target: { value: 'title' } });
    await waitFor(() => expect(params().get('as_sort')).toBe('title'));
    fireEvent.click(screen.getByText('Back'));
    await waitFor(() => expect((screen.getByLabelText('Sort assessments') as HTMLSelectElement).value).toBe('date'));
    expect(params().get('as_status')).toBe('active');
    fireEvent.click(screen.getByText('Forward'));
    await waitFor(() => expect((screen.getByLabelText('Sort assessments') as HTMLSelectElement).value).toBe('title'));
    expect(params().get('extra')).toBe('1');
  });

  it('restores page navigation and resets page when a filter changes', async () => {
    mount('/?view=assessment-list');
    await screen.findByText('Assessment 1');
    fireEvent.click(screen.getByRole('button', { name: 'Next page' }));
    await screen.findByText('Assessment 51');
    expect(params().get('as_page')).toBe('2');
    fireEvent.change(screen.getByLabelText('Filter by status'), { target: { value: 'active' } });
    await screen.findByText('Assessment 1');
    expect(params().has('as_page')).toBe(false);
    fireEvent.click(screen.getByText('Back'));
    await screen.findByText('Assessment 51');
  });

  it('does not replace an inaccessible customer filter with all customers', async () => {
    apiMock.list.mockImplementation(({ customer_id }: { customer_id?: string }) => Promise.resolve(customer_id === '999' ? [] : [record(1)]));
    mount('/?view=assessment-list&as_customer=999');
    await screen.findByText('No assessments match the current filters');
    expect(apiMock.list).toHaveBeenLastCalledWith(expect.objectContaining({ customer_id: '999' }));
    expect(screen.queryByText('Assessment 1')).toBeNull();
    expect((screen.getByLabelText('Filter by customer') as HTMLSelectElement).value).toBe('999');
    expect(screen.getByText('Selected customer unavailable')).toBeTruthy();
  });

  it('does not serialize a search draft until the debounce applies it', async () => {
    mount('/?view=assessment-list');
    await screen.findByText('Assessment 1');
    fireEvent.change(screen.getByLabelText('Search assessments by title or description'), { target: { value: '  cloud  ' } });
    expect(params().has('as_q')).toBe(false);
    await waitFor(() => expect(params().get('as_q')).toBe('cloud'));
    await waitFor(() => expect(apiMock.list).toHaveBeenCalledWith(expect.objectContaining({ search: 'cloud', skip: 0 })));
  });

  it('validates invalid values and falls back to page one when a page is empty', async () => {
    apiMock.list.mockImplementation(({ skip }: { skip: number }) => Promise.resolve(skip > 0 ? [] : [record(1)]));
    mount('/?view=assessment-list&as_status=unknown&as_sort=bad&as_customer=-1&as_page=99');
    await screen.findByText('Assessment 1');
    expect(params().has('as_page')).toBe(false);
    expect(apiMock.list).toHaveBeenLastCalledWith({ skip: 0, limit: 50, sort: 'updated' });
  });
});
