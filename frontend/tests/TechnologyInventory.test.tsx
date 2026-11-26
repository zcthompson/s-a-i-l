/**
 * Component tests for TechnologyInventory (structured technology
 * inventory UI). Mocks the api module (repo pattern: vi.hoisted + vi.mock
 * factory). Plain assertions — no @testing-library/jest-dom in this project.
 *
 * NOTE (jsdom, same as SalesEvaluation.test.tsx): native <select> has no
 * resolvable implicit ARIA role here, so selects are queried via their
 * aria-label / wrapping <label> (getByLabelText), never getByRole('select').
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, cleanup } from '@testing-library/react';
import { TechnologyInventory } from '../src/components/TechnologyInventory';

afterEach(() => {
  cleanup();
});

const ts = '2026-08-01T00:00:00Z';
const mockTech = [
  {
    id: 1, customer_id: 5, name: 'Oracle VM', vendor: 'Oracle', category: 'virtualization',
    version_edition: '3.4.2', deployment_model: 'virtual_machine', quantity: 12, footprint: '2 sites',
    purpose: 'Core VMs', lifecycle_state: 'eol', support_state: 'no_support',
    business_criticality: 'critical', source: 'discovery call', date_observed: '2026-07-01',
    verification_state: 'verified', confidence: null, notes: 'Aging platform',
    created_at: ts, updated_at: ts,
  },
  {
    id: 2, customer_id: 5, name: 'PostgreSQL', vendor: 'Postgres', category: 'software',
    version_edition: '13', deployment_model: 'on_premise', quantity: null, footprint: null,
    purpose: 'OLTP', lifecycle_state: 'current', support_state: 'under_support',
    business_criticality: 'high', source: 'assessment', date_observed: '2026-08-15',
    verification_state: 'inferred', confidence: 0.7, notes: null,
    created_at: ts, updated_at: ts,
  },
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

describe('TechnologyInventory component', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    apiMock.listCustomerTechnology.mockResolvedValue(mockTech);
    apiMock.createTechnology.mockResolvedValue(mockTech[0]);
    apiMock.updateTechnology.mockResolvedValue(mockTech[0]);
    apiMock.deleteTechnology.mockResolvedValue(undefined);
  });

  it('renders the inventory grouped by category with summary + verification badges', async () => {
    render(<TechnologyInventory customerId={5} userRole="member" allowWrite={true} />);

    expect(await screen.findByText('Oracle VM')).toBeTruthy();
    expect(screen.getByText('PostgreSQL')).toBeTruthy();
    // Category group headers — the same text also appears as an option in
    // the category filter, so assert on "at least one" via getAllByText.
    expect(screen.getAllByText('virtualization').length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText('software').length).toBeGreaterThanOrEqual(1);
    // Summary cards. "Verified" also appears as the verification badge on
    // the verified item (Oracle VM), so assert it shows at least twice
    // (summary label + badge). The filter option is lowercase "verified"
    // and does not match.
    expect(screen.getByText('Total Items')).toBeTruthy();
    expect(screen.getAllByText('Verified').length).toBeGreaterThanOrEqual(2);
    expect(screen.getByText('End-of-Life')).toBeTruthy();
  });

  it('shows the empty state when there are no items', async () => {
    apiMock.listCustomerTechnology.mockResolvedValue([]);
    render(<TechnologyInventory customerId={5} userRole="member" allowWrite={true} />);
    expect(await screen.findByText('No technology recorded yet.')).toBeTruthy();
  });

  it('shows an error banner when the list call fails', async () => {
    apiMock.listCustomerTechnology.mockRejectedValue(new Error('backend down'));
    render(<TechnologyInventory customerId={5} userRole="member" allowWrite={true} />);
    expect(await screen.findByText('backend down')).toBeTruthy();
  });

  it('narrows the list via the search box', async () => {
    render(<TechnologyInventory customerId={5} userRole="member" allowWrite={true} />);
    await screen.findByText('Oracle VM');

    const search = screen.getByLabelText('Search technology');
    fireEvent.change(search, { target: { value: 'oracle' } });

    expect(screen.getByText('Oracle VM')).toBeTruthy();
    expect(screen.queryByText('PostgreSQL')).toBeNull();
  });

  it('reveals detail fields when an item row is expanded', async () => {
    render(<TechnologyInventory customerId={5} userRole="member" allowWrite={true} />);
    const row = await screen.findByText('Oracle VM');
    fireEvent.click(row);

    // Detail field values only render when expanded.
    expect(await screen.findByText('discovery call')).toBeTruthy();
    expect(screen.getByText('Aging platform')).toBeTruthy();
  });

  it('creates a technology and calls the api with the payload', async () => {
    render(<TechnologyInventory customerId={5} userRole="member" allowWrite={true} />);
    await screen.findByText('Oracle VM');

    fireEvent.click(screen.getByRole('button', { name: 'Add technology' }));
    fireEvent.change(screen.getByLabelText(/Name/), { target: { value: 'New Tech' } });
    fireEvent.change(screen.getByLabelText(/^Category/), { target: { value: 'software' } });

    await fireEvent.click(screen.getByRole('button', { name: 'Save technology' }));

    expect(apiMock.createTechnology).toHaveBeenCalledTimes(1);
    const arg = apiMock.createTechnology.mock.calls[0];
    expect(arg[0]).toBe(5);
    expect(arg[1].name).toBe('New Tech');
    expect(arg[1].category).toBe('software');
  });

  it('refuses to save when name/category are missing', async () => {
    render(<TechnologyInventory customerId={5} userRole="member" allowWrite={true} />);
    await screen.findByText('Oracle VM');

    fireEvent.click(screen.getByRole('button', { name: 'Add technology' }));
    await fireEvent.click(screen.getByRole('button', { name: 'Save technology' }));

    expect(screen.getByText(/Name and category are required/)).toBeTruthy();
    expect(apiMock.createTechnology).not.toHaveBeenCalled();
  });

  it('deletes an item after confirmation', async () => {
    render(<TechnologyInventory customerId={5} userRole="member" allowWrite={true} />);
    const row = await screen.findByText('Oracle VM');
    fireEvent.click(row);

    fireEvent.click(screen.getByRole('button', { name: 'Delete technology' }));
    await fireEvent.click(screen.getByRole('button', { name: 'Confirm delete' }));

    expect(apiMock.deleteTechnology).toHaveBeenCalledWith(1);
  });

  it('hides create/edit/delete affordances for an auditor', async () => {
    render(<TechnologyInventory customerId={5} userRole="auditor" />);
    await screen.findByText('Oracle VM');

    expect(screen.queryByRole('button', { name: 'Add technology' })).toBeNull();
    // Expand a row — an auditor should see no Edit/Delete buttons.
    fireEvent.click(screen.getByText('Oracle VM'));
    expect(screen.queryByRole('button', { name: 'Edit technology' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'Delete technology' })).toBeNull();
  });
});


it('does not infer write capability from a legacy member role', async () => {
  render(<TechnologyInventory customerId={5} userRole="member" />);
  expect(screen.queryByLabelText('Add technology')).toBeNull();
});
