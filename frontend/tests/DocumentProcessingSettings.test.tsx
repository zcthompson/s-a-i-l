/**
 * Component tests for the Application Settings "Document Processing"
 * provider section .
 *
 * Pins: provider select + verbatim capability matrix; azure inputs disabled
 * under docling / enabled under azure; the data-leaves-the-app notice only
 * under azure; the env-only API key status line (and no key input); save
 * banners + verbatim 422 detail; submit payload shape.
 *
 * Assertions use plain DOM properties (repo convention — no jest-dom
 * matchers). Mocking follows vi.hoisted + vi.mock factory, as in
 * IntegrationSettingsSsl.test.tsx.
 */
import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen, fireEvent, cleanup, waitFor, within } from '@testing-library/react';
import { IntegrationSettings } from '../src/components/IntegrationSettings';

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

const { apiMock } = vi.hoisted(() => ({
  apiMock: {
    getInferenceConfig: vi.fn(),
    updateInferenceConfig: vi.fn(),
    getDoclingConfig: vi.fn(),
    updateDoclingConfig: vi.fn(),
    getDocumentProcessingConfig: vi.fn(),
    updateDocumentProcessingConfig: vi.fn(),
    getIntegrationConfig: vi.fn(),
    updateIntegrationConfig: vi.fn(),
    deleteConfigEntry: vi.fn(),
    integrationStatus: vi.fn(),
    sendSlack: vi.fn(),
  },
}));

vi.mock('../src/lib/api', () => ({
  api: apiMock,
}));

const NOTICE =
  'When Azure Document Intelligence is selected, uploaded customer documents are sent to Microsoft Azure for processing.';

const DOCS_DEFAULT = {
  provider: 'docling',
  azure_endpoint: '',
  azure_timeout_seconds: 600,
  azure_ssl_verify: 'full',
  azure_ssl_ca_bundle: null,
  api_key_configured: false,
};

const AZURE_FIELDS = [
  'Azure Document Intelligence endpoint',
  'Azure Document Intelligence timeout seconds',
  'Azure Document Intelligence SSL verification mode',
];

function mount(docs: Record<string, unknown> = DOCS_DEFAULT) {
  apiMock.getInferenceConfig.mockResolvedValue({ ai_endpoint: '', ai_model: '', ssl_verify: 'full', ssl_ca_bundle: null });
  apiMock.getDoclingConfig.mockResolvedValue({ server_url: '', timeout_seconds: 600, ssl_verify: 'full', ssl_ca_bundle: null });
  apiMock.getDocumentProcessingConfig.mockResolvedValue(docs);
  apiMock.getIntegrationConfig.mockResolvedValue({});
  apiMock.integrationStatus.mockResolvedValue({ slack: false, teams: false, jira: false });
  const view = render(<IntegrationSettings />);
  fireEvent.click(screen.getByRole('link', { name: 'Document processing' }));
  return view;
}

async function selectProvider(value: string) {
  const select = (await screen.findByLabelText('Document provider')) as HTMLSelectElement;
  fireEvent.change(select, { target: { value } });
  return select;
}

describe('Application Settings — Document Processing section', () => {
  it('renders the provider select and the capability matrix rows verbatim', async () => {
    mount();
    expect(await screen.findByRole('heading', { name: 'Document processing' })).toBeTruthy();
    const select = (await screen.findByLabelText('Document provider')) as HTMLSelectElement;
    const options = Array.from(select.querySelectorAll('option')).map((o) => [o.value, o.textContent]);
    expect(options).toEqual([
      ['docling', 'Docling (local conversion server)'],
      ['azure_document_intelligence', 'Azure Document Intelligence (Microsoft cloud)'],
    ]);
    expect(select.value).toBe('docling');

    const table = screen.getByLabelText('Provider capability matrix');
    const rows = Array.from(within(table).getAllByRole('row')).map((r) =>
      Array.from(r.querySelectorAll('th, td')).map((c) => c.textContent),
    );
    expect(rows).toEqual([
      ['Provider', 'Supported formats'],
      ['Docling', 'PDF, CSV, TSV, TXT, DOC/DOCX, PPT/PPTX, XLS/XLSX, HTML, ODT/ODS/ODP, PNG, JPG, TIFF, BMP, WEBP'],
      ['Azure Document Intelligence', 'PDF, DOCX, XLSX, PPTX, HTML, PNG, JPG, TIFF, BMP, HEIF'],
      ['Both (no provider call)', '.md / .markdown (in-process normalization)'],
    ]);
  });

  it('azure inputs are present but disabled under docling, enabled under azure', async () => {
    mount();
    await screen.findByLabelText('Document provider');
    for (const label of AZURE_FIELDS) {
      expect((screen.getByLabelText(label) as HTMLInputElement).disabled).toBe(true);
    }
    const endpoint = screen.getByLabelText('Azure Document Intelligence endpoint') as HTMLInputElement;
    expect(endpoint.placeholder).toBe('https://<resource>.cognitiveservices.azure.com');
    expect((screen.getByLabelText('Azure Document Intelligence timeout seconds') as HTMLInputElement).value).toBe('600');
    const ca = screen.getByLabelText('Azure Document Intelligence custom CA bundle') as HTMLTextAreaElement;
    expect(ca.disabled).toBe(true);

    await selectProvider('azure_document_intelligence');
    for (const label of AZURE_FIELDS) {
      expect((screen.getByLabelText(label) as HTMLInputElement).disabled).toBe(false);
    }
    // CA bundle stays disabled until the azure ssl mode is "ca".
    expect(ca.disabled).toBe(true);
    const ssl = screen.getByLabelText('Azure Document Intelligence SSL verification mode') as HTMLSelectElement;
    expect(Array.from(ssl.querySelectorAll('option')).map((o) => o.value)).toEqual(['full', 'skip', 'ca']);
    fireEvent.change(ssl, { target: { value: 'ca' } });
    expect(ca.disabled).toBe(false);
  });

  it('renders the data-leaves-the-app notice verbatim only when azure is selected', async () => {
    mount();
    await screen.findByLabelText('Document provider');
    expect(screen.queryByText(NOTICE)).toBeNull();
    await selectProvider('azure_document_intelligence');
    expect(screen.getByText(NOTICE)).toBeTruthy();
    await selectProvider('docling');
    expect(screen.queryByText(NOTICE)).toBeNull();
  });

  it('loads azure provider from the backend and shows the notice', async () => {
    mount({ ...DOCS_DEFAULT, provider: 'azure_document_intelligence', azure_endpoint: 'https://x.cognitiveservices.azure.com' });
    await waitFor(() =>
      expect((screen.getByLabelText('Document provider') as HTMLSelectElement).value).toBe('azure_document_intelligence'),
    );
    expect((screen.getByLabelText('Azure Document Intelligence endpoint') as HTMLInputElement).value)
      .toBe('https://x.cognitiveservices.azure.com');
    expect(screen.getByText(NOTICE)).toBeTruthy();
  });

  it('API key status line reflects api_key_configured; no API key input exists', async () => {
    mount();
    expect(await screen.findByText('API key: set in .env (SAIL_AZURE_DI_API_KEY) — not configured')).toBeTruthy();
    cleanup();
    mount({ ...DOCS_DEFAULT, api_key_configured: true });
    expect(await screen.findByText('API key: set in .env (SAIL_AZURE_DI_API_KEY) — configured')).toBeTruthy();
    await selectProvider('azure_document_intelligence');
    const keyInputs = Array.from(document.querySelectorAll('input, textarea')).filter((el) =>
      /api[\s_-]*key/i.test(el.getAttribute('aria-label') || '') &&
      /azure|document/i.test(el.getAttribute('aria-label') || ''),
    );
    expect(keyInputs).toEqual([]);
    // Nothing in the Document Processing section is an API key input at all.
    const section = screen.getByRole('heading', { name: 'Document processing' }).closest('section')!;
    const sectionKeyInputs = Array.from(section.querySelectorAll('input, textarea')).filter((el) =>
      /key/i.test(el.getAttribute('aria-label') || ''),
    );
    expect(sectionKeyInputs).toEqual([]);
  });

  it('falls back to defaults when the load fails', async () => {
    apiMock.getDocumentProcessingConfig.mockRejectedValueOnce(new Error('boom'));
    apiMock.getInferenceConfig.mockResolvedValue({ ai_endpoint: '', ai_model: '', ssl_verify: 'full', ssl_ca_bundle: null });
    apiMock.getDoclingConfig.mockResolvedValue({ server_url: '', timeout_seconds: 600, ssl_verify: 'full', ssl_ca_bundle: null });
    apiMock.getIntegrationConfig.mockResolvedValue({});
    apiMock.integrationStatus.mockResolvedValue({ slack: false, teams: false, jira: false });
    render(<IntegrationSettings />);
    const select = (await screen.findByLabelText('Document provider')) as HTMLSelectElement;
    expect(select.value).toBe('docling');
    expect(screen.getByText('API key: set in .env (SAIL_AZURE_DI_API_KEY) — not configured')).toBeTruthy();
  });

  it('save success shows the saved banner', async () => {
    apiMock.updateDocumentProcessingConfig.mockResolvedValue(DOCS_DEFAULT);
    mount();
    await screen.findByLabelText('Document provider');
    fireEvent.click(screen.getByRole('button', { name: 'Save document processing settings' }));
    await waitFor(() => expect(apiMock.updateDocumentProcessingConfig).toHaveBeenCalledTimes(1));
    const section = screen.getByRole('heading', { name: 'Document processing' }).closest('section')!;
    await waitFor(() => expect(within(section).getByText('✓ Saved')).toBeTruthy());
  });

  it('save 422 renders the exact backend detail verbatim', async () => {
    const detail = 'azure_endpoint must be an HTTPS endpoint (https://)';
    apiMock.updateDocumentProcessingConfig.mockRejectedValue(new Error(detail));
    mount();
    await selectProvider('azure_document_intelligence');
    fireEvent.change(screen.getByLabelText('Azure Document Intelligence endpoint'), {
      target: { value: 'https://rejected.example' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Save document processing settings' }));
    const alert = await screen.findByText(detail);
    expect(alert.textContent).toBe(detail);
    expect(alert.getAttribute('role')).toBe('alert');
  });

  it('submit payload: provider passed through, fields trimmed, CA bundle empty unless ca', async () => {
    apiMock.updateDocumentProcessingConfig.mockResolvedValue(DOCS_DEFAULT);
    mount();
    await selectProvider('azure_document_intelligence');
    fireEvent.change(screen.getByLabelText('Azure Document Intelligence endpoint'), {
      target: { value: '  https://r.cognitiveservices.azure.com  ' },
    });
    fireEvent.change(screen.getByLabelText('Azure Document Intelligence timeout seconds'), { target: { value: '120' } });
    const ssl = screen.getByLabelText('Azure Document Intelligence SSL verification mode');
    fireEvent.change(ssl, { target: { value: 'ca' } });
    fireEvent.change(screen.getByLabelText('Azure Document Intelligence custom CA bundle'), {
      target: { value: '-----BEGIN CERTIFICATE-----' },
    });
    // Switch away from ca: the typed bundle must not be submitted.
    fireEvent.change(ssl, { target: { value: 'skip' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save document processing settings' }));
    await waitFor(() => expect(apiMock.updateDocumentProcessingConfig).toHaveBeenCalledTimes(1));
    const payload = apiMock.updateDocumentProcessingConfig.mock.calls[0][0];
    expect(payload).toEqual({
      provider: 'azure_document_intelligence',
      azure_endpoint: 'https://r.cognitiveservices.azure.com',
      azure_timeout_seconds: 120,
      azure_ssl_verify: 'skip',
      azure_ssl_ca_bundle: '',
    });
    expect('api_key_configured' in payload).toBe(false);

    // ca mode → the bundle is sent.
    fireEvent.change(ssl, { target: { value: 'ca' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save document processing settings' }));
    await waitFor(() => expect(apiMock.updateDocumentProcessingConfig).toHaveBeenCalledTimes(2));
    expect(apiMock.updateDocumentProcessingConfig.mock.calls[1][0].azure_ssl_ca_bundle).toBe('-----BEGIN CERTIFICATE-----');
  });

  it('docling provider is passed through on save', async () => {
    apiMock.updateDocumentProcessingConfig.mockResolvedValue(DOCS_DEFAULT);
    mount({ ...DOCS_DEFAULT, provider: 'azure_document_intelligence' });
    await waitFor(() =>
      expect((screen.getByLabelText('Document provider') as HTMLSelectElement).value).toBe('azure_document_intelligence'),
    );
    await selectProvider('docling');
    fireEvent.click(screen.getByRole('button', { name: 'Save document processing settings' }));
    await waitFor(() => expect(apiMock.updateDocumentProcessingConfig).toHaveBeenCalledTimes(1));
    expect(apiMock.updateDocumentProcessingConfig.mock.calls[0][0].provider).toBe('docling');
  });
});

it('preserves inactive provider drafts and groups advanced options under document processing', async () => {
  mount();
  await selectProvider('azure_document_intelligence');
  const endpoint = screen.getByLabelText('Azure Document Intelligence endpoint') as HTMLInputElement;
  fireEvent.change(endpoint, { target: { value: 'https://draft.azure.test' } });
  expect(screen.getByText('Advanced Azure settings').closest('details')).toBeTruthy();
  await selectProvider('docling');
  expect(endpoint.closest('[hidden]')).toBeTruthy();
  expect(screen.queryByRole('button', { name: 'Save Docling settings' })).toBeTruthy();
  await selectProvider('azure_document_intelligence');
  expect(endpoint.value).toBe('https://draft.azure.test');
  expect(screen.queryByRole('button', { name: 'Save Docling settings' })).toBeNull();
});

it('focuses the HTTPS endpoint error locally without sending a request', async () => {
  mount();
  await selectProvider('azure_document_intelligence');
  const endpoint = screen.getByLabelText('Azure Document Intelligence endpoint');
  fireEvent.change(endpoint, { target: { value: 'http://insecure.example' } });
  const previous = apiMock.updateDocumentProcessingConfig.mock.calls.length;
  fireEvent.click(screen.getByRole('button', { name: 'Save document processing settings' }));
  expect(document.activeElement).toBe(endpoint);
  expect(endpoint.getAttribute('aria-invalid')).toBe('true');
  expect(apiMock.updateDocumentProcessingConfig.mock.calls.length).toBe(previous);
});
