/**
 * Component tests for CustomerKnowledgeBrowser (Docling
 * normalization UI). Mocks the api module (repo pattern: vi.hoisted +
 * vi.mock factory). Covers: the four processing states (Uploaded neutral /
 * Processing blue / Ready green / Failed red with diagnostic in the `...`
 * menu), the expanded `...` action menu (View details / View normalized
 * content / Reprocess / Download original / Delete), polling while
 * PROCESSING, the normalized-content modal (rendered + raw Markdown), and
 * FAILED → Reprocess recovery.
 *
 * NOTE: the component fetches on mount, so all list assertions use
 * findBy* (async). The polling test uses fake timers and flushes the
 * initial fetch with advanceTimersByTimeAsync(0) first.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, cleanup, waitFor, act } from '@testing-library/react';
import { CustomerKnowledgeBrowser } from '../src/components/CustomerKnowledgeBrowser';
import { MemoryRouter, useLocation, useNavigate } from 'react-router-dom';

afterEach(() => {
  cleanup();
  vi.useRealTimers();
});

const base = (over: Record<string, unknown> = {}) => ({
  id: 1,
  customer_id: 5,
  knowledge_type: 'file',
  file_name: 'engineering-architecture.pdf',
  uploaded_at: '2026-08-01T00:00:00Z',
  processed: true,
  processing_status: 'READY',
  normalized_content_present: true,
  original_content_type: 'application/pdf',
  processor: 'docling',
  processing_error: null,
  ...over,
});

const { apiMock } = vi.hoisted(() => ({
  apiMock: {
    listCustomerKnowledge: vi.fn(),
    getKnowledgeContent: vi.fn(),
    reprocessKnowledge: vi.fn(),
    retryKnowledgeEnrichment: vi.fn(),
    listKnowledgeItems: vi.fn(),
    uploadCustomerKnowledge: vi.fn(),
    deleteCustomerKnowledge: vi.fn(),
    knowledgeDownloadUrl: (id: number) => `/api/customer-knowledge/${id}/download`,
  },
}));

vi.mock('../src/lib/api', () => ({
  api: apiMock,
}));
vi.mock('../src/lib/auth', () => ({
  getAuthToken: () => 'test-token',
}));
vi.mock('marked', () => ({
  marked: { parse: (md: string) => `<div data-marked>${md}</div>` },
}));
vi.mock('dompurify', () => ({
  default: { sanitize: (h: string) => h },
}));

function openMenu(file: string) {
  const btn = screen.getByRole('button', { name: new RegExp(`Actions for ${file}`, 'i') });
  fireEvent.click(btn);
}

function KnowledgeRouteProbe() {
  const location = useLocation();
  const navigate = useNavigate();
  return <><output data-testid="knowledge-url">{location.search}</output><button onClick={() => navigate(-1)}>History back</button></>;
}

describe('CustomerKnowledgeBrowser — processing status UI', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    apiMock.listCustomerKnowledge.mockResolvedValue([]);
    apiMock.getKnowledgeContent.mockResolvedValue({
      id: 1, customer_id: 5, file_name: 'x.pdf', normalized_format: 'markdown',
      normalized_content: '# Normalized x', processor: 'docling', processing_status: 'READY',
    });
    apiMock.reprocessKnowledge.mockResolvedValue(base({ processing_status: 'PROCESSING' }));
    apiMock.retryKnowledgeEnrichment.mockResolvedValue(base({ processing_status: 'READY', enrichment_status: 'ENRICHED' }));
    apiMock.listKnowledgeItems.mockResolvedValue([]);
    apiMock.deleteCustomerKnowledge.mockResolvedValue(undefined);
  });

  it('restores an authorized document link and follows history', async () => {
    apiMock.listCustomerKnowledge.mockResolvedValue([base({ file_name: 'linked.pdf' })]);
    render(<MemoryRouter initialEntries={['/?knowledge_owner=5&knowledge_id=1']}><KnowledgeRouteProbe /><CustomerKnowledgeBrowser allowWrite={true} customerId={5} /></MemoryRouter>);
    await screen.findByRole('dialog');
    await waitFor(() => expect(apiMock.getKnowledgeContent).toHaveBeenCalledWith(1));
    fireEvent.click(screen.getByRole('button', { name: 'Close details' }));
    expect(screen.queryByRole('dialog')).toBeNull();
    expect(screen.getByTestId('knowledge-url').textContent).not.toContain('knowledge_id');
    fireEvent.click(screen.getByText('History back'));
    await screen.findByRole('dialog');
  });

  it('warns before downloading an older RVTools report', async () => {
    apiMock.listCustomerKnowledge.mockResolvedValue([base({ file_name: 'old.rvtools.md', knowledge_type: 'rvtools_report', processor: 'rvtools-import', processor_version: null })]);
    render(<MemoryRouter initialEntries={['/?knowledge_owner=5&knowledge_id=1']}><CustomerKnowledgeBrowser allowWrite={true} customerId={5} /></MemoryRouter>);
    expect((await screen.findByText(/older report may contain incomplete totals/i)).textContent).toContain('current VMware Footprint');
    expect(screen.getByText(/extracted intelligence and linked records may also reflect those totals/i)).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: 'Close details' }));
    openMenu('old.rvtools.md');
    expect(screen.getByRole('menuitem', { name: /download original \(legacy totals may be incomplete\)/i })).toBeTruthy();
  });

  it('does not open a document link scoped to another customer', async () => {
    apiMock.listCustomerKnowledge.mockResolvedValue([base({ customer_id: 6, file_name: 'other.pdf' })]);
    render(<MemoryRouter initialEntries={['/?knowledge_owner=5&knowledge_id=1']}><CustomerKnowledgeBrowser allowWrite={true} customerId={6} /></MemoryRouter>);
    await screen.findByText('other.pdf');
    expect(screen.queryByRole('dialog')).toBeNull();
    expect(apiMock.getKnowledgeContent).not.toHaveBeenCalled();
  });

  it('shows a generic unavailable message for a missing document', async () => {
    render(<MemoryRouter initialEntries={['/?knowledge_owner=5&knowledge_id=999']}><CustomerKnowledgeBrowser allowWrite={true} customerId={5} /></MemoryRouter>);
    expect(await screen.findByText('Knowledge entry not found or unavailable.')).toBeTruthy();
  });

  it('keeps a forbidden new customer clear when the previous request finishes late', async () => {
    let finishOld!: (value: any) => void;
    apiMock.listCustomerKnowledge.mockImplementation((id: number) => id === 5
      ? new Promise((resolve) => { finishOld = resolve; })
      : Promise.reject(Object.assign(new Error('Unavailable'), { status: 404 })));
    const view = render(<CustomerKnowledgeBrowser allowWrite={true} customerId={5} />);
    view.rerender(<CustomerKnowledgeBrowser allowWrite={true} customerId={6} />);
    expect(await screen.findByText(/Unavailable/)).toBeTruthy();
    await act(async () => finishOld([base({ file_name: 'old-account.pdf' })]));
    expect(screen.queryByText('old-account.pdf')).toBeNull();
  });

  it('closes the old detail and ignores its late content on a customer switch', async () => {
    apiMock.listCustomerKnowledge.mockImplementation((id: number) => Promise.resolve(id === 5
      ? [base({ file_name: 'old-account.pdf' })]
      : [base({ id: 9, customer_id: 6, file_name: 'new-account.pdf' })]));
    let finishContent!: (value: any) => void;
    apiMock.getKnowledgeContent.mockReturnValue(new Promise((resolve) => { finishContent = resolve; }));
    const view = render(<CustomerKnowledgeBrowser allowWrite={true} customerId={5} />);
    await screen.findByText('old-account.pdf');
    openMenu('old-account.pdf');
    fireEvent.click(screen.getByRole('menuitem', { name: 'View normalized content' }));
    await waitFor(() => expect(apiMock.getKnowledgeContent).toHaveBeenCalled());
    view.rerender(<CustomerKnowledgeBrowser allowWrite={true} customerId={6} />);
    await screen.findByText('new-account.pdf');
    await act(async () => finishContent({ normalized_content: 'Private old content' }));
    expect(screen.queryByText('Private old content')).toBeNull();
    expect(screen.queryByRole('dialog')).toBeNull();
  });

  it('ignores a previous customer’s late knowledge list after an account switch', async () => {
    let finishOld!: (value: ReturnType<typeof base>[]) => void;
    apiMock.listCustomerKnowledge.mockImplementation((id: number) => id === 5
      ? new Promise((resolve) => { finishOld = resolve; })
      : Promise.resolve([base({ id: 9, customer_id: 6, file_name: 'new-account.pdf' })]));
    const view = render(<CustomerKnowledgeBrowser allowWrite={true} customerId={5} />);
    view.rerender(<CustomerKnowledgeBrowser allowWrite={true} customerId={6} />);
    await screen.findByText('new-account.pdf');
    await act(async () => finishOld([base({ file_name: 'old-account.pdf' })]));
    await waitFor(() => expect(screen.queryByText('old-account.pdf')).toBeNull());
    expect(screen.getByText('new-account.pdf')).toBeTruthy();
  });

  it('shows the four status chips with the right semantic labels', async () => {
    apiMock.listCustomerKnowledge.mockResolvedValue([
      base({ id: 1, file_name: 'a.md', processing_status: 'UPLOADED', processed: false, normalized_content_present: false }),
      base({ id: 2, file_name: 'b.pdf', processing_status: 'PROCESSING', processed: false, normalized_content_present: false }),
      base({ id: 3, file_name: 'c.pdf', processing_status: 'READY', processed: true, normalized_content_present: true }),
      base({ id: 4, file_name: 'd.pdf', processing_status: 'FAILED', processed: false, normalized_content_present: false, processing_error: 'Docling unreachable' }),
    ]);
    render(<CustomerKnowledgeBrowser allowWrite={true} customerId={5} />);
    expect(await screen.findByText('Uploaded')).toBeTruthy();
    expect(screen.getByText('Processing')).toBeTruthy();
    expect(screen.getByText('Ready')).toBeTruthy();
    expect(screen.getByText('Failed')).toBeTruthy();
    // FAILED exposes the diagnostic in the row's title (tooltip).
    expect(screen.getByTitle('Docling unreachable')).toBeTruthy();
    // All four rows carry the status role for screen readers.
    expect(screen.getAllByRole('status', { name: /Processing status/i }).length).toBe(4);
  });

  it('renders an empty state when there are no entries', async () => {
    apiMock.listCustomerKnowledge.mockResolvedValue([]);
    render(<CustomerKnowledgeBrowser allowWrite={true} customerId={5} />);
    expect(await screen.findByText(/No knowledge entries found/i)).toBeTruthy();
  });

  it('expanded `...` menu offers details / normalized / reprocess / download / delete', async () => {
    apiMock.listCustomerKnowledge.mockResolvedValue([
      base({ file_name: 'e.pdf', processing_status: 'READY', normalized_content_present: true }),
    ]);
    render(<CustomerKnowledgeBrowser allowWrite={true} customerId={5} />);
    await screen.findByText('Ready');
    openMenu('e.pdf');
    expect(screen.getByRole('menuitem', { name: 'View details' })).toBeTruthy();
    expect(screen.getByRole('menuitem', { name: 'View normalized content' })).toBeTruthy();
    expect(screen.getByRole('menuitem', { name: 'Reprocess' })).toBeTruthy();
    expect(screen.getByRole('menuitem', { name: 'Download original' })).toBeTruthy();
    expect(screen.getByRole('menuitem', { name: 'Delete entry' })).toBeTruthy();
  });

  it('disables View normalized content when not READY', async () => {
    apiMock.listCustomerKnowledge.mockResolvedValue([
      base({ file_name: 'f.pdf', processing_status: 'PROCESSING', normalized_content_present: false }),
    ]);
    render(<CustomerKnowledgeBrowser allowWrite={true} customerId={5} />);
    await screen.findByText('Processing');
    openMenu('f.pdf');
    expect((screen.getByRole('menuitem', { name: 'View normalized content' }) as HTMLButtonElement).disabled).toBe(true);
  });

  it('View details opens a modal with rendered Markdown + raw toggle', async () => {
    apiMock.listCustomerKnowledge.mockResolvedValue([
      base({ file_name: 'g.pdf', processing_status: 'READY', normalized_content_present: true }),
    ]);
    render(<CustomerKnowledgeBrowser allowWrite={true} customerId={5} />);
    await screen.findByText('Ready');
    openMenu('g.pdf');
    fireEvent.click(screen.getByRole('menuitem', { name: 'View normalized content' }));
    await waitFor(() => expect(apiMock.getKnowledgeContent).toHaveBeenCalledWith(1));
    // Rendered (marked → sanitized) view.
    expect(await screen.findByText(/# Normalized x/)).toBeTruthy();
    // Raw toggle swaps to the raw markdown source.
    fireEvent.click(screen.getByRole('tab', { name: 'Raw Markdown' }));
    expect(screen.getByText('# Normalized x', { selector: 'pre' })).toBeTruthy();
  });

  it('FAILED details modal shows the diagnostic + a Reprocess action', async () => {
    apiMock.listCustomerKnowledge.mockResolvedValue([
      base({ file_name: 'h.pdf', processing_status: 'FAILED', normalized_content_present: false, processing_error: 'Docling unreachable at http://x:5001' }),
    ]);
    render(<CustomerKnowledgeBrowser allowWrite={true} customerId={5} />);
    await screen.findByText('Failed');
    openMenu('h.pdf');
    fireEvent.click(screen.getByRole('menuitem', { name: 'View details' }));
    expect(await screen.findByText(/Processing failed/i)).toBeTruthy();
    expect(screen.getByText(/Docling unreachable at http:\/\/x:5001/)).toBeTruthy();
    expect(screen.getByRole('button', { name: /Reprocess/i })).toBeTruthy();
  });

  it('Reprocess calls the API and refreshes the list', async () => {
    apiMock.listCustomerKnowledge.mockResolvedValue([
      base({ file_name: 'i.pdf', processing_status: 'FAILED', normalized_content_present: false, processing_error: 'down' }),
    ]);
    render(<CustomerKnowledgeBrowser allowWrite={true} customerId={5} />);
    await screen.findByText('Failed');
    openMenu('i.pdf');
    fireEvent.click(screen.getByRole('menuitem', { name: 'Reprocess' }));
    await waitFor(() => expect(apiMock.reprocessKnowledge).toHaveBeenCalledWith(1));
    await waitFor(() => expect(apiMock.listCustomerKnowledge).toHaveBeenCalledTimes(2));
  });

  it('Delete calls the API and confirms', async () => {
    apiMock.listCustomerKnowledge.mockResolvedValue([
      base({ file_name: 'j.pdf', processing_status: 'READY', normalized_content_present: true }),
    ]);
    const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(true);
    render(<CustomerKnowledgeBrowser allowWrite={true} customerId={5} />);
    await screen.findByText('Ready');
    openMenu('j.pdf');
    fireEvent.click(screen.getByRole('menuitem', { name: 'Delete entry' }));
    await waitFor(() => expect(apiMock.deleteCustomerKnowledge).toHaveBeenCalledWith(1));
    expect(confirmSpy).toHaveBeenCalled();
  });

  it('polls while a row is PROCESSING', async () => {
    vi.useFakeTimers();
    apiMock.listCustomerKnowledge.mockResolvedValue([
      base({ file_name: 'k.pdf', processing_status: 'PROCESSING', normalized_content_present: false }),
    ]);
    render(<CustomerKnowledgeBrowser allowWrite={true} customerId={5} />);
    // Flush the initial fetch (microtasks) before measuring.
    await vi.advanceTimersByTimeAsync(0);
    const initial = apiMock.listCustomerKnowledge.mock.calls.length;
    expect(initial).toBe(1);
    await vi.advanceTimersByTimeAsync(5000);
    expect(apiMock.listCustomerKnowledge.mock.calls.length).toBeGreaterThan(initial);
  });
});

describe('CustomerKnowledgeBrowser — LLM enrichment (PLAN_CUSTOMER_ENRICHMENT)', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    apiMock.listCustomerKnowledge.mockResolvedValue([]);
    apiMock.getKnowledgeContent.mockResolvedValue({
      id: 1, customer_id: 5, file_name: 'x.pdf', normalized_format: 'markdown',
      normalized_content: '# Normalized x', processor: 'docling', processing_status: 'READY',
    });
    apiMock.reprocessKnowledge.mockResolvedValue(base({ processing_status: 'PROCESSING' }));
    apiMock.retryKnowledgeEnrichment.mockResolvedValue(base({ processing_status: 'READY', enrichment_status: 'ENRICHED' }));
    apiMock.listKnowledgeItems.mockResolvedValue([]);
    apiMock.deleteCustomerKnowledge.mockResolvedValue(undefined);
  });

  it('shows the enrichment stage chip on READY documents', async () => {
    apiMock.listCustomerKnowledge.mockResolvedValue([
      base({ id: 1, file_name: 'a.pdf', processing_status: 'READY', enriched: true, enrichment_status: 'ENRICHED' }),
      base({ id: 2, file_name: 'b.pdf', processing_status: 'READY', enrichment_status: 'ENRICHING' }),
      base({ id: 3, file_name: 'c.pdf', processing_status: 'READY', enrichment_status: 'FAILED', enrichment_error: 'Model unavailable' }),
    ]);
    render(<CustomerKnowledgeBrowser allowWrite={true} customerId={5} />);
    expect(await screen.findByText('Enriched')).toBeTruthy();
    expect(screen.getByText('Analyzing')).toBeTruthy();
    expect(screen.getByText('Analysis failed')).toBeTruthy();
    // FAILED analysis exposes its diagnostic (separate from the Docling one).
    expect(screen.getByTitle('Model unavailable')).toBeTruthy();
  });

  it('upload section offers the knowledge category select', async () => {
    apiMock.listCustomerKnowledge.mockResolvedValue([]);
    render(<CustomerKnowledgeBrowser allowWrite={true} customerId={5} />);
    await screen.findByText(/No knowledge entries found/i);
    // UX audit #5 regression: the upload UI is a real dialog opened on
    // demand — open it before touching the category select.
    fireEvent.click(screen.getByRole('button', { name: 'Upload Knowledge File' }));
    await screen.findByRole('dialog', { name: 'Upload Knowledge File' });
    const select = screen.getByLabelText('Knowledge category') as HTMLSelectElement;
    expect(select).toBeTruthy();
    expect(Array.from(select.options).some((o) => o.value === 'technology_infrastructure')).toBe(true);
    expect(select.options[0].value).toBe(''); // auto (LLM decides)
  });

  it('upload passes the selected category to the API', async () => {
    apiMock.listCustomerKnowledge.mockResolvedValue([]);
    apiMock.uploadCustomerKnowledge.mockResolvedValue({
      success: true, knowledge_id: 9, classified_type: 'document',
      entries_count: 0, warnings: [], processing_status: 'PROCESSING',
    });
    render(<CustomerKnowledgeBrowser allowWrite={true} customerId={5} />);
    await screen.findByText(/No knowledge entries found/i);
    fireEvent.click(screen.getByRole('button', { name: 'Upload Knowledge File' }));
    await screen.findByRole('dialog', { name: 'Upload Knowledge File' });
    const select = screen.getByLabelText('Knowledge category') as HTMLSelectElement;
    fireEvent.change(select, { target: { value: 'business_strategy_goals' } });
    const fileInput = document.querySelector('input[type="file"]') as HTMLInputElement;
    const file = new File(['# test'], 'plan.md', { type: 'text/markdown' });
    Object.defineProperty(fileInput, 'files', { value: [file], configurable: true });
    fireEvent.change(fileInput);
    await waitFor(() =>
      expect(apiMock.uploadCustomerKnowledge).toHaveBeenCalledWith(
        file, 5, 'business_strategy_goals',
      ),
    );
  });

  it('UX audit #5 — the entries list is the DEFAULT view; the upload dialog is on demand and Esc-closeable', async () => {
    apiMock.listCustomerKnowledge.mockResolvedValue([
      base({ file_name: 'existing.pdf' }),
    ]);
    render(<CustomerKnowledgeBrowser allowWrite={true} customerId={5} />);
    // The entries list renders first — no upload dialog open by default.
    await screen.findByText('existing.pdf');
    expect(screen.queryByRole('dialog', { name: 'Upload Knowledge File' })).toBeNull();
    // Opening on demand produces a REAL dialog (role + aria-modal).
    fireEvent.click(screen.getByRole('button', { name: 'Upload Knowledge File' }));
    const dialog = await screen.findByRole('dialog', { name: 'Upload Knowledge File' });
    expect(dialog).toBeTruthy();
    // Esc closes it (keyboard users were previously stuck in the overlay).
    fireEvent.keyDown(document, { key: 'Escape' });
    await waitFor(() =>
      expect(screen.queryByRole('dialog', { name: 'Upload Knowledge File' })).toBeNull(),
    );
  });

  it('FAILED enrichment offers a Retry LLM analysis action that calls the enrich endpoint', async () => {
    apiMock.listCustomerKnowledge.mockResolvedValue([
      base({ file_name: 'r.pdf', processing_status: 'READY', normalized_content_present: true, enrichment_status: 'FAILED' }),
    ]);
    render(<CustomerKnowledgeBrowser allowWrite={true} customerId={5} />);
    await screen.findByText('Analysis failed');
    openMenu('r.pdf');
    expect(screen.getByRole('menuitem', { name: 'Retry LLM analysis' })).toBeTruthy();
    fireEvent.click(screen.getByRole('menuitem', { name: 'Retry LLM analysis' }));
    await waitFor(() => expect(apiMock.retryKnowledgeEnrichment).toHaveBeenCalledWith(1));
  });

  it('details modal lists the extracted intelligence items with provenance badges', async () => {
    apiMock.listCustomerKnowledge.mockResolvedValue([
      base({ file_name: 's.pdf', processing_status: 'READY', normalized_content_present: true, enrichment_status: 'ENRICHED', enrichment_model: 'nemotron-lightning' }),
    ]);
    apiMock.listKnowledgeItems.mockResolvedValue([
      {
        id: 11, customer_id: 5, source_knowledge_id: 1, kind: 'technology',
        name: 'VMware vSphere', description: 'Primary virtualization', provenance: 'explicit',
        confidence: 0.95, evidence: 'operates VMware vSphere', source_reference: 'Sec 2',
        applied_status: 'created', applied_object_type: 'technology', applied_object_id: 7,
        enrichment_model: 'nemotron-lightning', extracted_at: '2026-09-11T00:00:00Z',
      },
      {
        id: 12, customer_id: 5, source_knowledge_id: 1, kind: 'opportunity',
        name: 'Modernization candidate', description: null, provenance: 'suggested',
        confidence: 0.6, evidence: null, source_reference: null,
        applied_status: 'created', applied_object_type: 'opportunity', applied_object_id: 3,
        enrichment_model: 'nemotron-lightning', extracted_at: '2026-09-11T00:00:00Z',
      },
    ]);
    render(<CustomerKnowledgeBrowser allowWrite={true} customerId={5} />);
    await screen.findByText('Enriched');
    openMenu('s.pdf');
    fireEvent.click(screen.getByRole('menuitem', { name: 'View details' }));
    expect(await screen.findByText(/Extracted intelligence/i)).toBeTruthy();
    expect(screen.getByText('VMware vSphere')).toBeTruthy();
    // Provenance is visually distinct (item 6): stated vs suggested.
    expect(screen.getByText('Stated')).toBeTruthy();
    expect(screen.getByText('Suggested')).toBeTruthy();
    expect(screen.getByText('Modernization candidate')).toBeTruthy();
    expect(screen.getByText(/nemotron-lightning/)).toBeTruthy();
  });

  it('polls while a row is ENRICHING', async () => {
    vi.useFakeTimers();
    apiMock.listCustomerKnowledge.mockResolvedValue([
      base({ file_name: 't.pdf', processing_status: 'READY', normalized_content_present: true, enrichment_status: 'ENRICHING' }),
    ]);
    render(<CustomerKnowledgeBrowser allowWrite={true} customerId={5} />);
    await vi.advanceTimersByTimeAsync(0);
    const initial = apiMock.listCustomerKnowledge.mock.calls.length;
    expect(initial).toBe(1);
    await vi.advanceTimersByTimeAsync(5000);
    expect(apiMock.listCustomerKnowledge.mock.calls.length).toBeGreaterThan(initial);
  });
});


it('requires an explicit knowledge capability before upload', async () => {
  apiMock.listCustomerKnowledge.mockResolvedValue([]);
  render(<CustomerKnowledgeBrowser customerId={5} />);
  await screen.findByText('No knowledge entries found.');
  const upload = screen.getByLabelText('Upload Knowledge File') as HTMLButtonElement;
  expect(upload.disabled).toBe(true);
  fireEvent.click(upload);
  expect(screen.queryByRole('dialog')).toBeNull();
});
