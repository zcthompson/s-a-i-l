import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { ThirdPartyServices } from '../src/components/ThirdPartyServices';
import { GlobalAdminDashboard } from '../src/components/GlobalAdminDashboard';

const timestamp = '2026-09-14T10:00:00Z';
const services = [
  {
    id: 11, customer_id: 5, vendor_name: 'Acme Consulting', service_category: 'data_analytics',
    engagement_status: 'active', description: 'Data platform modernization.', sow_reference: 'SOW-44',
    contract_reference: null, started_on: '2026-09-01', ended_on: null, billing_model: 'tm',
    fee_amount: 12500, verification_state: 'verified', notes: null, created_by: 'rep',
    related_use_case_ids: [7, 8], created_at: timestamp, updated_at: timestamp,
  },
  {
    id: 12, customer_id: 5, vendor_name: 'Unknown Terms LLC', service_category: 'technical',
    engagement_status: 'planned', description: 'Scope under review.', sow_reference: null,
    contract_reference: null, started_on: null, ended_on: null, billing_model: null,
    fee_amount: null, verification_state: 'unverified', notes: null, created_by: null,
    related_use_case_ids: [], created_at: timestamp, updated_at: timestamp,
  },
];

const document = {
  id: 91, service_id: 11, customer_id: 5, document_type: 'sow', file_name: 'scope.pdf',
  title: 'Phase one scope', uploaded_by: 'rep', created_at: timestamp,
};

const { apiMock } = vi.hoisted(() => ({
  apiMock: {
    listCustomerThirdPartyServices: vi.fn(),
    createThirdPartyService: vi.fn(),
    updateThirdPartyService: vi.fn(),
    deleteThirdPartyService: vi.fn(),
    listThirdPartyServiceDocuments: vi.fn(),
    uploadThirdPartyServiceDocument: vi.fn(),
    downloadThirdPartyServiceDocument: vi.fn(),
    deleteThirdPartyServiceDocument: vi.fn(),
    listAllThirdPartyServices: vi.fn(),
    getGlobalAdminStats: vi.fn(),
  },
}));

vi.mock('../src/lib/api', () => ({ api: apiMock }));
vi.mock('../src/components/AppHealthCard', () => ({ AppHealthCard: () => <div>Health</div> }));

afterEach(cleanup);

describe('ThirdPartyServices customer panel', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    apiMock.listCustomerThirdPartyServices.mockResolvedValue(services);
    apiMock.createThirdPartyService.mockResolvedValue(services[0]);
    apiMock.updateThirdPartyService.mockResolvedValue(services[0]);
    apiMock.deleteThirdPartyService.mockResolvedValue(undefined);
    apiMock.listThirdPartyServiceDocuments.mockResolvedValue([document]);
    apiMock.uploadThirdPartyServiceDocument.mockResolvedValue(document);
    apiMock.downloadThirdPartyServiceDocument.mockResolvedValue(new Blob(['pdf']));
    apiMock.deleteThirdPartyServiceDocument.mockResolvedValue(undefined);
    Object.defineProperty(URL, 'createObjectURL', { configurable: true, value: vi.fn(() => 'blob:test') });
    Object.defineProperty(URL, 'revokeObjectURL', { configurable: true, value: vi.fn() });
    vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => undefined);
  });

  it('renders seeded status, category, vendor, billing, fee, dates, and nulls', async () => {
    render(<ThirdPartyServices customerId={5} userRole="member" />);

    expect(await screen.findByText('Acme Consulting')).toBeTruthy();
    expect(screen.getAllByText('Data / Analytics').length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText('Active').length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText('T&M · $12,500.00 / month')).toBeTruthy();
    expect(screen.getByText('2026-09-01 → —')).toBeTruthy();
    expect(screen.getByText('— → —')).toBeTruthy();
    expect(screen.getByText('Unknown Terms LLC')).toBeTruthy();
  });

  it('validates required fields, date ordering, and fee/billing consistency', async () => {
    render(<ThirdPartyServices customerId={5} userRole="member" />);
    await screen.findByText('Acme Consulting');
    fireEvent.click(screen.getByRole('button', { name: 'Add third-party service' }));
    fireEvent.click(screen.getByRole('button', { name: 'Save third-party service' }));
    expect(screen.getByText('Vendor, category, and description are required.')).toBeTruthy();

    fireEvent.change(screen.getByLabelText('Vendor'), { target: { value: 'New Partner' } });
    fireEvent.change(screen.getByLabelText('Service category'), { target: { value: 'cloud' } });
    fireEvent.change(screen.getByLabelText('Service description'), { target: { value: 'Cloud migration.' } });
    fireEvent.change(screen.getByLabelText('Service start date'), { target: { value: '2026-10-10' } });
    fireEvent.change(screen.getByLabelText('Service end date'), { target: { value: '2026-10-01' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save third-party service' }));
    expect(screen.getByText('End date must be on or after start date.')).toBeTruthy();

    fireEvent.change(screen.getByLabelText('Service end date'), { target: { value: '2026-10-20' } });
    fireEvent.change(screen.getByLabelText('Billing model'), { target: { value: 'tm' } });
    fireEvent.change(screen.getByLabelText('Monthly fee'), { target: { value: '5000' } });
    fireEvent.change(screen.getByLabelText('Billing model'), { target: { value: '' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save third-party service' }));
    expect(screen.getByText('A billing model is required when a monthly fee is entered.')).toBeTruthy();
    expect(apiMock.createThirdPartyService).not.toHaveBeenCalled();
  });

  it('edits an engagement with a full use-case replacement payload', async () => {
    render(<ThirdPartyServices customerId={5} userRole="member" />);
    fireEvent.click(await screen.findByRole('button', { name: 'Expand Acme Consulting service' }));
    fireEvent.click(screen.getByRole('button', { name: 'Edit third-party service' }));
    fireEvent.change(screen.getByLabelText('Vendor'), { target: { value: 'Acme Updated' } });
    fireEvent.change(screen.getByLabelText('Related use case ids'), { target: { value: '12, 14' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save third-party service' }));

    await waitFor(() => expect(apiMock.updateThirdPartyService).toHaveBeenCalledTimes(1));
    expect(apiMock.updateThirdPartyService.mock.calls[0][0]).toBe(11);
    expect(apiMock.updateThirdPartyService.mock.calls[0][1]).toMatchObject({
      vendor_name: 'Acme Updated', use_case_ids: [12, 14], billing_model: 'tm', fee_amount: 12500,
    });
  });

  it('uploads, downloads, and deletes documents from the expanded sub-panel', async () => {
    render(<ThirdPartyServices customerId={5} userRole="member" />);
    fireEvent.click(await screen.findByRole('button', { name: 'Expand Acme Consulting service' }));
    expect(await screen.findByText('scope.pdf')).toBeTruthy();
    expect(screen.getByText('Phase one scope')).toBeTruthy();
    expect(screen.getAllByText('SOW').length).toBeGreaterThanOrEqual(1);

    const file = new File(['contents'], 'new-po.pdf', { type: 'application/pdf' });
    fireEvent.change(screen.getByLabelText('Document type'), { target: { value: 'po' } });
    fireEvent.change(screen.getByLabelText('Document title'), { target: { value: 'Purchase order' } });
    fireEvent.change(screen.getByLabelText('Third-party service document file'), { target: { files: [file] } });
    fireEvent.click(screen.getByRole('button', { name: 'Upload third-party service document' }));
    await waitFor(() => expect(apiMock.uploadThirdPartyServiceDocument).toHaveBeenCalledWith(11, file, 'po', 'Purchase order'));

    fireEvent.click(screen.getByRole('button', { name: 'Download scope.pdf' }));
    await waitFor(() => expect(apiMock.downloadThirdPartyServiceDocument).toHaveBeenCalledWith(91));
    expect(URL.createObjectURL).toHaveBeenCalled();

    fireEvent.click(screen.getByRole('button', { name: 'Delete document scope.pdf' }));
    fireEvent.click(screen.getByRole('button', { name: 'Confirm delete document scope.pdf' }));
    await waitFor(() => expect(apiMock.deleteThirdPartyServiceDocument).toHaveBeenCalledWith(11, 91));
  });

  it('deletes an engagement only after confirmation', async () => {
    render(<ThirdPartyServices customerId={5} userRole="member" />);
    fireEvent.click(await screen.findByRole('button', { name: 'Expand Acme Consulting service' }));
    fireEvent.click(screen.getByRole('button', { name: 'Delete third-party service' }));
    expect(apiMock.deleteThirdPartyService).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button', { name: 'Confirm delete third-party service' }));
    await waitFor(() => expect(apiMock.deleteThirdPartyService).toHaveBeenCalledWith(11));
  });
});

describe('GlobalAdminDashboard third-party services role gate', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    apiMock.listAllThirdPartyServices.mockResolvedValue([services[0]]);
  });

  it('renders the cross-account read-only section for ps_admin', async () => {
    render(<GlobalAdminDashboard userIsAdmin={false} userRole="ps_admin" />);
    expect(await screen.findByRole('heading', { name: 'Third-Party Services' })).toBeTruthy();
    expect(screen.getByText('Acme Consulting')).toBeTruthy();
    expect(screen.getByText('ID 5')).toBeTruthy();
    expect(screen.queryByRole('button', { name: 'Add third-party service' })).toBeNull();
  });

  it('does not render the section for a plain user', () => {
    render(<GlobalAdminDashboard userIsAdmin={false} userRole="user" />);
    expect(screen.queryByRole('heading', { name: 'Third-Party Services' })).toBeNull();
    expect(screen.getByText(/Admin or third-party services administrator privileges required/)).toBeTruthy();
    expect(apiMock.listAllThirdPartyServices).not.toHaveBeenCalled();
  });
});
