/**
 * E5 — TechnologyInventory optional EOL fields (end_of_support_date +
 * eol_source). Same mocking pattern as TechnologyInventory.test.tsx
 * (vi.hoisted + vi.mock factory). Synthetic fixtures only.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, cleanup, waitFor } from '@testing-library/react';
import { TechnologyInventory } from '../src/components/TechnologyInventory';

afterEach(() => cleanup());

const ts = '2026-08-01T00:00:00Z';
const base = {
  customer_id: 5, category: 'software', version_edition: null, deployment_model: null, quantity: null,
  footprint: null, purpose: null, lifecycle_state: 'eol_announced', support_state: null, business_criticality: 'high',
  source: null, date_observed: null, verification_state: 'unverified', confidence: null, notes: null,
  created_at: ts, updated_at: ts,
};
const mockTech = [
  { ...base, id: 1, name: 'Synthetic DB', vendor: 'Synthetic Vendor', end_of_support_date: '2027-03-31', eol_source: 'vendor lifecycle page' },
  { ...base, id: 2, name: 'Synthetic Queue', vendor: null, end_of_support_date: null, eol_source: null },
  { ...base, id: 3, name: 'Synthetic Cache', vendor: null },
];

const { apiMock } = vi.hoisted(() => ({
  apiMock: {
    listCustomerTechnology: vi.fn(),
    createTechnology: vi.fn(),
    updateTechnology: vi.fn(),
    deleteTechnology: vi.fn(),
  },
}));

vi.mock('../src/lib/api', () => ({
  api: apiMock,
  getAuthUsername: () => 'admin',
  getAuthIsAdmin: () => true,
  getAuthSalesRole: () => null,
}));

const HELPER = 'Dated end-of-support evidence feeds the account health End-of-support component and EOL attention cards.';

describe('TechnologyInventory EOL fields', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    apiMock.listCustomerTechnology.mockResolvedValue(mockTech);
    apiMock.createTechnology.mockResolvedValue(mockTech[0]);
    apiMock.updateTechnology.mockResolvedValue(mockTech[0]);
    apiMock.deleteTechnology.mockResolvedValue(undefined);
  });

  it('form renders both optional fields + helper alongside the existing required fields', async () => {
    render(<TechnologyInventory customerId={5} userRole="member" allowWrite={true} />);
    await screen.findByText('Synthetic DB');
    fireEvent.click(screen.getByRole('button', { name: 'Add technology' }));
    expect(screen.getByLabelText(/Name/)).toBeTruthy();
    expect(screen.getByLabelText(/^Category/)).toBeTruthy();
    const date = screen.getByLabelText('End-of-Support Date') as HTMLInputElement;
    const src = screen.getByLabelText('EOL Source') as HTMLInputElement;
    expect(date.type).toBe('date');
    expect(date.value).toBe('');
    expect(src.value).toBe('');
    expect(src.maxLength).toBe(255);
    expect(screen.getByText(HELPER)).toBeTruthy();
  });

  it('a populated create carries both fields in the payload', async () => {
    render(<TechnologyInventory customerId={5} userRole="member" allowWrite={true} />);
    await screen.findByText('Synthetic DB');
    fireEvent.click(screen.getByRole('button', { name: 'Add technology' }));
    fireEvent.change(screen.getByLabelText(/Name/), { target: { value: 'New Synthetic' } });
    fireEvent.change(screen.getByLabelText(/^Category/), { target: { value: 'software' } });
    fireEvent.change(screen.getByLabelText('End-of-Support Date'), { target: { value: '2027-06-30' } });
    fireEvent.change(screen.getByLabelText('EOL Source'), { target: { value: 'vendor bulletin' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save technology' }));
    await waitFor(() => expect(apiMock.createTechnology).toHaveBeenCalledTimes(1));
    const [cid, payload] = apiMock.createTechnology.mock.calls[0];
    expect(cid).toBe(5);
    expect(payload.name).toBe('New Synthetic');
    expect(payload.end_of_support_date).toBe('2027-06-30');
    expect(payload.eol_source).toBe('vendor bulletin');
  });

  it('an empty create sends both fields as null (component convention for optional fields)', async () => {
    render(<TechnologyInventory customerId={5} userRole="member" allowWrite={true} />);
    await screen.findByText('Synthetic DB');
    fireEvent.click(screen.getByRole('button', { name: 'Add technology' }));
    fireEvent.change(screen.getByLabelText(/Name/), { target: { value: 'Plain Synthetic' } });
    fireEvent.change(screen.getByLabelText(/^Category/), { target: { value: 'software' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save technology' }));
    await waitFor(() => expect(apiMock.createTechnology).toHaveBeenCalledTimes(1));
    const payload = apiMock.createTechnology.mock.calls[0][1];
    expect(payload.end_of_support_date).toBeNull();
    expect(payload.eol_source).toBeNull();
    expect(payload.vendor).toBeNull();
  });

  it('edit pre-fills the EOL fields and update carries edited values', async () => {
    render(<TechnologyInventory customerId={5} userRole="member" allowWrite={true} />);
    fireEvent.click(await screen.findByText('Synthetic DB'));
    fireEvent.click(screen.getByRole('button', { name: 'Edit technology' }));
    expect((screen.getByLabelText('End-of-Support Date') as HTMLInputElement).value).toBe('2027-03-31');
    expect((screen.getByLabelText('EOL Source') as HTMLInputElement).value).toBe('vendor lifecycle page');
    fireEvent.change(screen.getByLabelText('EOL Source'), { target: { value: '' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save technology' }));
    await waitFor(() => expect(apiMock.updateTechnology).toHaveBeenCalledTimes(1));
    const [id, payload] = apiMock.updateTechnology.mock.calls[0];
    expect(id).toBe(1);
    expect(payload.end_of_support_date).toBe('2027-03-31');
    expect(payload.eol_source).toBeNull();
  });

  it('row shows the EOL line when present and nothing extra when absent', async () => {
    render(<TechnologyInventory customerId={5} userRole="member" allowWrite={true} />);
    await screen.findByText('Synthetic DB');
    expect(screen.getByTestId('tech-eol-1').textContent).toBe('EOL Mar 31, 2027 · vendor lifecycle page');
    expect(screen.queryByTestId('tech-eol-2')).toBeNull();
    expect(screen.queryByTestId('tech-eol-3')).toBeNull();
  });

  it('existing required-field validation is undisturbed', async () => {
    render(<TechnologyInventory customerId={5} userRole="member" allowWrite={true} />);
    await screen.findByText('Synthetic DB');
    fireEvent.click(screen.getByRole('button', { name: 'Add technology' }));
    fireEvent.change(screen.getByLabelText('EOL Source'), { target: { value: 'only eol' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save technology' }));
    expect(screen.getByText(/Name and category are required/)).toBeTruthy();
    expect(apiMock.createTechnology).not.toHaveBeenCalled();
  });
});
