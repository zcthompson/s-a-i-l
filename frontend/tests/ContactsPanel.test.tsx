/**
 * H4 — ContactsPanel component tests (synthetic fixtures only).
 * Mocks the api module (repo pattern: vi.hoisted + vi.mock factory).
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, cleanup, waitFor } from '@testing-library/react';
import { ContactsPanel } from '../src/components/ContactsPanel';

afterEach(() => cleanup());

const ts = '2026-10-01T00:00:00Z';
const BASIS = 'No qualified interaction evidence recorded (editing a contact is not engagement)';
const CONFLICT = 'Contact has linked sales notes; archive the contact instead (historical note references are preserved)';

const contact = (over: Record<string, unknown> = {}) => ({
  id: 1, customer_id: 5, display_name: 'Pat Example', title: 'VP Finance', email: null, phone: null,
  department: null, persona: null, persona_label: null, source: null, observation_date: null,
  verification_state: 'verified', buying_roles: [], related_note_ids: [], related_use_case_ids: [],
  related_technology_ids: [], note_count: 0, archived: false, archived_at: null,
  created_by: 'u', updated_by: 'u', created_at: ts, updated_at: ts, ...over,
});
const role = (r: string, label: string) => ({ role: r, role_label: label, source: null, observation_date: null, verification_state: 'verified' });

const coverage = (over: Record<string, unknown> = {}) => ({
  customer_id: 5, calc_version: 'contact-coverage/1', source: 'customer_contacts',
  contacts_recorded: 1, archived_count: 0,
  roles: { economic_buyer: 0, decision_maker: 0, champion: 0, technical_buyer: 0, influencer: 0, end_user: 0 },
  economic_buyer_recorded: false, champion_recorded: false, personas: {}, persona_unknown: 1,
  gaps: ['No economic buyer recorded', 'No champion recorded'],
  last_contacted: null, last_contacted_basis: BASIS, ...over,
});

const personas = [
  { id: 'executive', label: 'Executive' },
  { id: 'security', label: 'Security' },
];

const { apiMock } = vi.hoisted(() => ({
  apiMock: {
    listCustomerContacts: vi.fn(),
    getContactCoverage: vi.fn(),
    listSalesPersonas: vi.fn(),
    createContact: vi.fn(),
    updateContact: vi.fn(),
    deleteContact: vi.fn(),
  },
}));
vi.mock('../src/lib/api', () => ({ api: apiMock }));

describe('ContactsPanel', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    apiMock.listCustomerContacts.mockResolvedValue([contact()]);
    apiMock.getContactCoverage.mockResolvedValue(coverage());
    apiMock.listSalesPersonas.mockResolvedValue(personas);
    apiMock.createContact.mockResolvedValue(contact());
    apiMock.updateContact.mockResolvedValue(contact());
    apiMock.deleteContact.mockResolvedValue(undefined);
  });

  it('renders backend gap strings and the last-contacted basis verbatim; role is never inferred from title', async () => {
    render(<ContactsPanel customerId={5} userRole="member" />);
    expect(await screen.findByText('Pat Example')).toBeTruthy();
    expect(screen.getByText('VP Finance')).toBeTruthy();
    expect(screen.getByTestId('coverage-economic-buyer').textContent).toBe('Economic buyer: No economic buyer recorded');
    expect(screen.getByTestId('coverage-champion').textContent).toBe('Champion: No champion recorded');
    expect(screen.getByTestId('coverage-last-contacted').textContent).toContain('Last contacted: —');
    expect(screen.getByTestId('coverage-last-contacted-basis').textContent).toBe(BASIS);
    expect(screen.getByTestId('coverage-personas').textContent).toContain('Personas recorded: 0 of 2');
    expect(screen.getByTestId('coverage-personas').textContent).toContain('unknown: 1');
    expect(screen.queryByTestId('role-chip-economic_buyer')).toBeNull();
  });

  it('shows the no-contacts gap string verbatim', async () => {
    apiMock.listCustomerContacts.mockResolvedValue([]);
    apiMock.getContactCoverage.mockResolvedValue(coverage({
      contacts_recorded: 0, persona_unknown: 0,
      gaps: ['No contacts recorded', 'No economic buyer recorded', 'No champion recorded'],
    }));
    render(<ContactsPanel customerId={5} userRole="member" />);
    expect((await screen.findByTestId('coverage-contacts-gap')).textContent).toBe('No contacts recorded');
    expect(screen.getByText('No contacts recorded yet.')).toBeTruthy();
  });

  it('renders multiple role chips, names recorded roles in coverage, persona label, and null fields as —', async () => {
    apiMock.listCustomerContacts.mockResolvedValue([
      contact({
        persona: 'executive', persona_label: 'Executive',
        buying_roles: [role('economic_buyer', 'Economic buyer'), role('champion', 'Champion')],
      }),
    ]);
    apiMock.getContactCoverage.mockResolvedValue(coverage({
      economic_buyer_recorded: true, champion_recorded: true, personas: { executive: 1 }, persona_unknown: 0, gaps: [],
    }));
    render(<ContactsPanel customerId={5} userRole="member" />);
    expect(await screen.findByTestId('role-chip-economic_buyer')).toBeTruthy();
    expect(screen.getByTestId('role-chip-champion')).toBeTruthy();
    expect(screen.getAllByText('Executive').length).toBeGreaterThan(0);
    expect(screen.getByTestId('coverage-economic-buyer').textContent).toBe('Economic buyer: Pat Example');
    expect(screen.getByTestId('coverage-personas').textContent).toContain('Personas recorded: 1 of 2');
    fireEvent.click(screen.getByLabelText('Toggle contact Pat Example'));
    expect(screen.getByTestId('contact-provenance-1').textContent).toBe('Source: — · Observed: —');
    expect(screen.getByText('Email').nextElementSibling?.textContent).toBe('—');
  });

  it('show-archived toggle re-queries with includeArchived and shows the Archived badge', async () => {
    render(<ContactsPanel customerId={5} userRole="member" />);
    await screen.findByText('Pat Example');
    apiMock.listCustomerContacts.mockResolvedValue([contact({ archived: true, archived_at: ts })]);
    fireEvent.click(screen.getByLabelText('Show archived'));
    await waitFor(() => expect(apiMock.listCustomerContacts).toHaveBeenLastCalledWith(5, { includeArchived: true }));
    expect(await screen.findByText('Archived')).toBeTruthy();
    fireEvent.click(screen.getByLabelText('Toggle contact Pat Example'));
    expect(screen.getByLabelText('Restore contact')).toBeTruthy();
  });

  it('archive sends archived:true', async () => {
    render(<ContactsPanel customerId={5} userRole="member" />);
    fireEvent.click(await screen.findByLabelText('Toggle contact Pat Example'));
    fireEvent.click(screen.getByLabelText('Archive contact'));
    await waitFor(() => expect(apiMock.updateContact).toHaveBeenCalledWith(1, { archived: true }));
  });

  it('delete 409 shows the backend message verbatim and suggests archive', async () => {
    apiMock.deleteContact.mockRejectedValue(Object.assign(new Error(CONFLICT), { status: 409 }));
    render(<ContactsPanel customerId={5} userRole="member" />);
    fireEvent.click(await screen.findByLabelText('Toggle contact Pat Example'));
    fireEvent.click(screen.getByLabelText('Delete contact'));
    fireEvent.click(screen.getByLabelText('Confirm delete'));
    expect((await screen.findByTestId('contacts-error')).textContent).toBe(CONFLICT);
    expect(screen.getByText(/Use Archive instead/)).toBeTruthy();
  });

  it('save keeps a stable label, locks while pending and recovers after failure', async () => {
    let reject!: (e: Error) => void;
    apiMock.createContact.mockImplementation(() => new Promise((_, r) => { reject = r; }));
    render(<ContactsPanel customerId={5} userRole="member" />);
    await screen.findByText('Pat Example');
    fireEvent.click(screen.getByLabelText('Add contact'));
    fireEvent.change(screen.getByLabelText('Display name *'), { target: { value: 'Sam Sample' } });
    const save = screen.getByLabelText('Save contact') as HTMLButtonElement;
    fireEvent.click(save);
    await waitFor(() => expect(save.getAttribute('aria-busy')).toBe('true'));
    expect(save.disabled).toBe(true);
    expect(save.textContent).toContain('Add Contact');
    fireEvent.click(save);
    expect(apiMock.createContact).toHaveBeenCalledTimes(1);
    reject(new Error('Synthetic save failure'));
    await waitFor(() => expect(save.disabled).toBe(false));
    expect(save.getAttribute('aria-busy')).toBeNull();
  });

  it('delete is a two-step destructive action: outlined first, solid danger to confirm', async () => {
    render(<ContactsPanel customerId={5} userRole="member" />);
    fireEvent.click(await screen.findByLabelText('Toggle contact Pat Example'));
    const first = screen.getByLabelText('Delete contact');
    expect(first.dataset.variant).toBe('secondary');
    expect(first.dataset.tone).toBe('danger');
    fireEvent.click(first);
    expect(screen.getByLabelText('Confirm delete').dataset.variant).toBe('danger');
    expect(apiMock.deleteContact).not.toHaveBeenCalled();
  });

  it('blocks a blank display name without calling the API', async () => {
    render(<ContactsPanel customerId={5} userRole="member" />);
    await screen.findByText('Pat Example');
    fireEvent.click(screen.getByLabelText('Add contact'));
    fireEvent.change(screen.getByLabelText('Display name *'), { target: { value: '   ' } });
    fireEvent.click(screen.getByLabelText('Save contact'));
    expect(await screen.findByText('Display name is required.')).toBeTruthy();
    expect(apiMock.createContact).not.toHaveBeenCalled();
  });

  it('blocks an unknown persona (not in the registry)', async () => {
    apiMock.listCustomerContacts.mockResolvedValue([contact({ persona: 'legacy_x', persona_label: null })]);
    render(<ContactsPanel customerId={5} userRole="member" />);
    fireEvent.click(await screen.findByLabelText('Toggle contact Pat Example'));
    fireEvent.click(screen.getByLabelText('Edit contact'));
    fireEvent.click(screen.getByLabelText('Save contact'));
    expect(await screen.findByText(/Unknown persona 'legacy_x'/)).toBeTruthy();
    expect(apiMock.updateContact).not.toHaveBeenCalled();
  });

  it('create sends nulls for blank optionals, registry persona, multiple roles with form-level provenance', async () => {
    render(<ContactsPanel customerId={5} userRole="member" />);
    await screen.findByText('Pat Example');
    fireEvent.click(screen.getByLabelText('Add contact'));
    fireEvent.change(screen.getByLabelText('Display name *'), { target: { value: ' Sam Sample ' } });
    fireEvent.change(screen.getByLabelText('Persona'), { target: { value: 'security' } });
    fireEvent.click(screen.getByLabelText('Role Economic buyer'));
    fireEvent.click(screen.getByLabelText('Role Champion'));
    fireEvent.change(screen.getByLabelText('Role source (applies to roles added now)'), { target: { value: 'kickoff call' } });
    fireEvent.click(screen.getByLabelText('Save contact'));
    await waitFor(() => expect(apiMock.createContact).toHaveBeenCalledTimes(1));
    const [cid, payload] = apiMock.createContact.mock.calls[0];
    expect(cid).toBe(5);
    expect(payload).toMatchObject({
      display_name: 'Sam Sample', title: null, email: null, phone: null, department: null,
      persona: 'security', source: null, observation_date: null,
    });
    expect(payload.buying_roles).toEqual([
      { role: 'economic_buyer', source: 'kickoff call', observation_date: null, verification_state: 'verified' },
      { role: 'champion', source: 'kickoff call', observation_date: null, verification_state: 'verified' },
    ]);
  });

  it('hides write controls for auditors', async () => {
    render(<ContactsPanel customerId={5} userRole="auditor" />);
    await screen.findByText('Pat Example');
    expect(screen.queryByLabelText('Add contact')).toBeNull();
    fireEvent.click(screen.getByLabelText('Toggle contact Pat Example'));
    expect(screen.queryByLabelText('Edit contact')).toBeNull();
  });
});
