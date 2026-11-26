/**
 * Component tests for SalesNotes (structured sales notes UI).
 * Mocks the api module (repo pattern: vi.hoisted + vi.mock factory).
 * Plain assertions — no @testing-library/jest-dom in this project.
 *
 * NOTE (jsdom): native <select> has no resolvable implicit ARIA role here, so
 * selects are queried via aria-label / wrapping <label> (getByLabelText).
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, cleanup, act, waitFor } from '@testing-library/react';
import { SalesNotes } from '../src/components/SalesNotes';
import { MemoryRouter, useLocation, useNavigate } from 'react-router-dom';

afterEach(() => {
  cleanup();
});

const ts = '2026-08-01T00:00:00Z';
const mockNotes = [
  {
    id: 1, customer_id: 5, author: 'jdoe', source: 'discovery call', note_date: '2026-08-20',
    category: 'discovery', title: 'Initial discovery', content: 'Customer is evaluating a refresh.',
    verification_state: 'verified', related_technology_ids: [1, 2], related_use_case_ids: [3],
    created_at: ts, updated_at: ts,
  },
  {
    id: 2, customer_id: 5, author: 'jdoe', source: 'meeting', note_date: '2026-08-25',
    category: 'competitive', title: 'Competitor mentioned', content: 'Nutanix is in the shortlist.',
    verification_state: 'verified', related_technology_ids: [], related_use_case_ids: [],
    created_at: ts, updated_at: ts,
  },
];

const { apiMock } = vi.hoisted(() => ({
  apiMock: {
    listCustomerSalesNotes: vi.fn(),
    createSalesNote: vi.fn(),
    updateSalesNote: vi.fn(),
    deleteSalesNote: vi.fn(),
  },
}));

vi.mock('../src/lib/api', () => ({
  api: apiMock,
  getAuthUsername: () => 'admin',
  getAuthIsAdmin: () => true,
  getAuthSalesRole: () => null,
}));

function NotesRouteProbe() {
  const location = useLocation();
  const navigate = useNavigate();
  return <><output data-testid="notes-url">{location.search}</output><button onClick={() => navigate(-1)}>History back</button></>;
}

describe('Sales Notes links', () => {
  beforeEach(() => { apiMock.listCustomerSalesNotes.mockReset().mockResolvedValue(mockNotes); });
  it('restores category and expanded note, without putting search text into the URL', async () => {
    render(<MemoryRouter initialEntries={['/?notes_owner=5&notes_category=discovery&notes_id=1&extra=1']}><NotesRouteProbe /><SalesNotes customerId={5} userRole="member" allowWrite={true} /></MemoryRouter>);
    expect(await screen.findByText('Customer is evaluating a refresh.')).toBeTruthy();
    expect((screen.getByLabelText('Filter by note category') as HTMLSelectElement).value).toBe('discovery');
    fireEvent.change(screen.getByLabelText('Search notes'), { target: { value: 'private search' } });
    expect(screen.getByTestId('notes-url').textContent).not.toContain('private');
    fireEvent.change(screen.getByLabelText('Filter by note category'), { target: { value: 'competitive' } });
    expect(screen.getByTestId('notes-url').textContent).toContain('notes_category=competitive');
    fireEvent.click(screen.getByText('History back'));
    expect((screen.getByLabelText('Filter by note category') as HTMLSelectElement).value).toBe('discovery');
  });
  it('does not restore a note or category from a different customer', async () => {
    apiMock.listCustomerSalesNotes.mockResolvedValue([{ ...mockNotes[0], customer_id: 6, title: 'New customer note' }]);
    render(<MemoryRouter initialEntries={['/?notes_owner=5&notes_id=1&notes_category=competitive']}><SalesNotes customerId={6} userRole="member" allowWrite={true} /></MemoryRouter>);
    await screen.findByText('New customer note');
    expect((screen.getByLabelText('Filter by note category') as HTMLSelectElement).value).toBe('');
    expect(screen.queryByText('Customer is evaluating a refresh.')).toBeNull();
  });
});

describe('SalesNotes component', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    apiMock.listCustomerSalesNotes.mockResolvedValue(mockNotes);
    apiMock.createSalesNote.mockResolvedValue(mockNotes[0]);
    apiMock.updateSalesNote.mockResolvedValue(mockNotes[0]);
    apiMock.deleteSalesNote.mockResolvedValue(undefined);
  });

  it('keeps a forbidden new customer clear when the previous request finishes late', async () => {
    let finishOld!: (value: any) => void;
    apiMock.listCustomerSalesNotes.mockImplementation((id: number) => id === 5
      ? new Promise((resolve) => { finishOld = resolve; })
      : Promise.reject(Object.assign(new Error('Unavailable'), { status: 404 })));
    const view = render(<SalesNotes customerId={5} userRole="member" allowWrite={true} />);
    view.rerender(<SalesNotes customerId={6} userRole="member" allowWrite={true} />);
    expect(await screen.findByText(/Unavailable/)).toBeTruthy();
    await act(async () => finishOld(mockNotes));
    expect(screen.queryByText('Initial discovery')).toBeNull();
  });

  it('does not show a previous customer’s late notes after switching accounts', async () => {
    let finishOld!: (value: typeof mockNotes) => void;
    apiMock.listCustomerSalesNotes.mockImplementation((id: number) => id === 5
      ? new Promise((resolve) => { finishOld = resolve; })
      : Promise.resolve([{ ...mockNotes[0], id: 9, customer_id: 6, title: 'New customer note' }]));
    const view = render(<SalesNotes customerId={5} userRole="member" allowWrite={true} />);
    view.rerender(<SalesNotes customerId={6} userRole="member" allowWrite={true} />);
    await screen.findByText('New customer note');
    await act(async () => finishOld(mockNotes));
    await waitFor(() => expect(screen.queryByText('Initial discovery')).toBeNull());
    expect(screen.getByText('New customer note')).toBeTruthy();
  });

  it('renders the notes list with category badges, summary, and verification badges', async () => {
    render(<SalesNotes customerId={5} userRole="member" allowWrite={true} />);

    expect(await screen.findByText('Initial discovery')).toBeTruthy();
    expect(screen.getByText('Competitor mentioned')).toBeTruthy();
    // Category badges — the same text also appears as an option in the
    // category filter, so assert on "at least one" via getAllByText.
    expect(screen.getAllByText('discovery').length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText('competitive').length).toBeGreaterThanOrEqual(1);
    // Summary cards.
    expect(screen.getByText('Total Notes')).toBeTruthy();
    expect(screen.getByText('Latest Note')).toBeTruthy();
    // Latest date also renders as a row badge on the newest note.
    expect(screen.getAllByText('2026-08-25').length).toBeGreaterThanOrEqual(1);
  });

  it('shows the empty state when there are no notes', async () => {
    apiMock.listCustomerSalesNotes.mockResolvedValue([]);
    render(<SalesNotes customerId={5} userRole="member" allowWrite={true} />);
    expect(await screen.findByText('No sales notes recorded yet.')).toBeTruthy();
  });

  it('shows an error banner when the list call fails', async () => {
    apiMock.listCustomerSalesNotes.mockRejectedValue(new Error('backend down'));
    render(<SalesNotes customerId={5} userRole="member" allowWrite={true} />);
    expect(await screen.findByText('backend down')).toBeTruthy();
  });

  it('narrows the list via the search box', async () => {
    render(<SalesNotes customerId={5} userRole="member" allowWrite={true} />);
    await screen.findByText('Initial discovery');

    const search = screen.getByLabelText('Search notes');
    fireEvent.change(search, { target: { value: 'competitor' } });

    expect(screen.getByText('Competitor mentioned')).toBeTruthy();
    expect(screen.queryByText('Initial discovery')).toBeNull();
  });

  it('reveals note content + related ids when a note is expanded', async () => {
    render(<SalesNotes customerId={5} userRole="member" allowWrite={true} />);
    const row = await screen.findByText('Initial discovery');
    fireEvent.click(row);

    expect(await screen.findByText('Customer is evaluating a refresh.')).toBeTruthy();
    // Related technology ids render joined.
    expect(screen.getByText('1, 2')).toBeTruthy();
    expect(screen.getByText('3')).toBeTruthy();
  });

  it('creates a note and calls the api with the parsed payload', async () => {
    render(<SalesNotes customerId={5} userRole="member" allowWrite={true} />);
    await screen.findByText('Initial discovery');

    fireEvent.click(screen.getByRole('button', { name: 'Add sales note' }));
    fireEvent.change(screen.getByLabelText(/^Category/), { target: { value: 'discovery' } });
    fireEvent.change(screen.getByLabelText(/^Title/), { target: { value: 'New Note' } });
    fireEvent.change(screen.getByLabelText(/^Content/), { target: { value: 'Some content' } });
    fireEvent.change(screen.getByLabelText(/Related technology ids/), { target: { value: '1, 2' } });

    await fireEvent.click(screen.getByRole('button', { name: 'Save note' }));

    expect(apiMock.createSalesNote).toHaveBeenCalledTimes(1);
    const arg = apiMock.createSalesNote.mock.calls[0];
    expect(arg[0]).toBe(5);
    expect(arg[1].category).toBe('discovery');
    expect(arg[1].title).toBe('New Note');
    expect(arg[1].content).toBe('Some content');
    expect(arg[1].related_technology_ids).toEqual([1, 2]);
  });

  it('refuses to save when required fields are missing', async () => {
    render(<SalesNotes customerId={5} userRole="member" allowWrite={true} />);
    await screen.findByText('Initial discovery');

    fireEvent.click(screen.getByRole('button', { name: 'Add sales note' }));
    await fireEvent.click(screen.getByRole('button', { name: 'Save note' }));

    expect(screen.getByText(/Category, title, and content are required/)).toBeTruthy();
    expect(apiMock.createSalesNote).not.toHaveBeenCalled();
  });

  it('deletes a note after confirmation', async () => {
    render(<SalesNotes customerId={5} userRole="member" allowWrite={true} />);
    const row = await screen.findByText('Initial discovery');
    fireEvent.click(row);

    fireEvent.click(screen.getByRole('button', { name: 'Delete note' }));
    await fireEvent.click(screen.getByRole('button', { name: 'Confirm delete' }));

    expect(apiMock.deleteSalesNote).toHaveBeenCalledWith(1);
  });

  it('hides create/edit/delete affordances for an auditor', async () => {
    render(<SalesNotes customerId={5} userRole="auditor" />);
    await screen.findByText('Initial discovery');

    expect(screen.queryByRole('button', { name: 'Add sales note' })).toBeNull();
    fireEvent.click(screen.getByText('Initial discovery'));
    expect(screen.queryByRole('button', { name: 'Edit note' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'Delete note' })).toBeNull();
  });
});


it('does not infer write capability from a legacy member role', async () => {
  render(<SalesNotes customerId={5} userRole="member" />);
  expect(screen.queryByLabelText('Add sales note')).toBeNull();
});
