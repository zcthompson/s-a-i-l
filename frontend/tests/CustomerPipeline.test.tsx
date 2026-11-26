// CustomerPipeline panel — rows with money/date formatting, totals strip,
// source line, empty state, and error surface.
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, within, cleanup, fireEvent, waitFor } from '@testing-library/react';
import { CustomerPipeline } from '../src/components/CustomerPipeline';

const { apiMock } = vi.hoisted(() => ({ apiMock: { getCustomerPipeline: vi.fn() } }));
vi.mock('../src/lib/api', () => ({ api: apiMock }));

const row = (over: Record<string, unknown> = {}) => ({
  id: 1, import_id: 7, customer_id: 85, customer_account_name: 'Example Customer B',
  opportunity_name: 'RHEL renewal', opp_stage: 'Proposal', product_offering_group: 'RHEL',
  est_acv_usd: 100000, est_tcv_usd: 300000, close_date: '2026-10-30', growth_risk_flag: 'growth',
  ...over,
});

const totals = () => ({
  line_count: 2, deal_count: 2, open_deals: 1, unknown_deals: 0, growth: 1, risk: 1,
  est_acv_total: null as number | null, est_tcv_total: null as number | null,
  amount_coverage: { acv: 'all_unknown', tcv: 'all_unknown' },
});

const group = (over: Record<string, unknown> = {}) => ({ total: null, coverage: 'all_unknown', lines_included: 0, lines_excluded: 0, ...over });
const summary = (over: Record<string, unknown> = {}) => ({
  calculation_version: 'pipeline-read-model/1', as_of: '2026-10-26T15:30:00Z',
  source: { source_type: 'partner_pipeline', import_id: 7, source_file: 'f.csv', imported_at: '2026-10-25T22:20:01Z', imported_by: 'admin', note: 'n' },
  currency_basis: 'USD (source-labelled line estimates; never converted)', currency_codes: ['USD'], currency_note: null,
  grain: { line_count: 3, opportunity_count: 1, unidentified_lines: 0, ambiguous_opportunities: [] },
  stages: { open: 0, won: 0, lost: 0, unknown: 1, unknown_stage_values: [] },
  amounts: { acv: group(), tcv: group() }, forecast_categories: {}, reporting: {},
  ...over,
});

beforeEach(() => { apiMock.getCustomerPipeline.mockReset(); });
afterEach(cleanup);

describe('CustomerPipeline', () => {
  it('renders rows with money/date formatting, totals strip and source line', async () => {
    apiMock.getCustomerPipeline.mockResolvedValue({
      customer_name: 'Example Customer B', import_id: 7,
      source_file: 'PartnerInsights.csv', imported_at: '2026-10-22T15:00:00+00:00',
      rows: [row(), row({ id: 2, opportunity_name: 'OCP', opp_stage: 'Closed Won', est_acv_usd: null, close_date: null, growth_risk_flag: 'risk' })],
      totals: { ...totals(), deal_count: 2, line_count: 2, open_deals: 1, est_acv_total: 100000, est_tcv_total: 600000, amount_coverage: { acv: 'quantified', tcv: 'quantified' } },
      technologies: ['RHEL'],
    });
    render(<CustomerPipeline customerName="Example Customer B" />);
    const r1 = await screen.findByTestId('customer-pipeline-row-1');
    expect(apiMock.getCustomerPipeline).toHaveBeenCalledWith('Example Customer B');
    expect(within(r1).getByText('RHEL renewal')).toBeTruthy();
    expect(within(r1).getByText('$100,000')).toBeTruthy();
    expect(within(r1).getByText('$300,000')).toBeTruthy();
    expect(within(r1).getByText('Oct 30, 2026')).toBeTruthy();
    expect(within(r1).getByText('growth')).toBeTruthy();
    const r2 = screen.getByTestId('customer-pipeline-row-2');
    expect(within(r2).getAllByText('—').length).toBe(2); // null ACV + null close date
    const totalsText = screen.getByTestId('customer-pipeline-totals').textContent!;
    expect(totalsText).toContain('2 opportunities · 2 lines');
    expect(totalsText).toContain('1 open');
    expect(totalsText).toContain('1 growth / 1 risk');
    expect(totalsText).toContain('$100,000');
    expect(totalsText).toContain('$600,000');
    expect(screen.getByTestId('customer-pipeline-source').textContent).toContain('PartnerInsights.csv');
    expect(screen.getByTestId('customer-pipeline-source').textContent).toContain('Oct 22, 2026');
    expect(screen.getByTestId('customer-pipeline-technologies').textContent).toBe('1 technology record from renewal: RHEL');
  });

  it('shows the empty state when no rows were imported', async () => {
    apiMock.getCustomerPipeline.mockResolvedValue({
      customer_name: 'Acme', import_id: null, source_file: null, imported_at: null, rows: [],
      totals: { ...totals(), deal_count: 0, line_count: 0, open_deals: 0, growth: 0, risk: 0, est_acv_total: null, est_tcv_total: null, amount_coverage: { acv: 'no_data', tcv: 'no_data' } },
      technologies: [],
    });
    render(<CustomerPipeline customerName="Acme" />);
    expect((await screen.findByTestId('customer-pipeline-empty')).textContent)
      .toContain('No partner pipeline data imported for this account');
    expect(screen.queryByTestId('customer-pipeline-totals')).toBeNull();
    expect(screen.queryByTestId('customer-pipeline-technologies')).toBeNull();
  });

  it('shows an inline error when the load fails', async () => {
    apiMock.getCustomerPipeline.mockImplementation(() => Promise.reject(new Error('boom')));
    render(<CustomerPipeline customerName="Acme" />);
    expect((await screen.findByTestId('customer-pipeline-error')).textContent).toBe('boom');
  });

  const load = (totalsOver: Record<string, unknown>, summaryOver?: Record<string, unknown>) => {
    apiMock.getCustomerPipeline.mockResolvedValue({
      customer_name: 'Acme', import_id: 7, source_file: 'f.csv', imported_at: '2026-10-22T15:00:00+00:00',
      rows: [row()], totals: { ...totals(), ...totalsOver },
      technologies: [], ...(summaryOver ? { summary: summary(summaryOver) } : {}),
    });
  };

  it('never shows $0 for unknown amounts and separates opportunity from line grain', async () => {
    load({ line_count: 9, deal_count: 3, open_deals: 2, unknown_deals: 1 });
    render(<CustomerPipeline customerName="Acme" />);
    await screen.findByTestId('customer-pipeline-totals');
    const t = screen.getByTestId('customer-pipeline-totals').textContent!;
    expect(t).toContain('3 opportunities · 9 lines');
    expect(t).toContain('2 open / 1 unknown stage');
    expect(screen.getByTestId('customer-pipeline-acv').textContent).toBe('Est. ACV Not recorded');
    expect(screen.getByTestId('customer-pipeline-tcv').textContent).toBe('Est. TCV Not recorded');
    expect(t).not.toContain('$0');
    expect(screen.queryByTestId('customer-pipeline-ambiguity')).toBeNull();
  });

  it('renders partial / recorded-zero amount states, unidentified lines, ambiguity and currency note', async () => {
    load(
      { est_acv_total: 500, est_tcv_total: 0, amount_coverage: { acv: 'partial', tcv: 'recorded_zero' } },
      {
        grain: { line_count: 4, opportunity_count: 1, unidentified_lines: 2, ambiguous_opportunities: [{ opportunity_number: 'OPP-1', conflicts: ["stage: 'A', 'B'"] }] },
        amounts: { acv: group({ total: 500, coverage: 'partial', lines_included: 3, lines_excluded: 1 }), tcv: group({ total: 0, coverage: 'recorded_zero', lines_included: 4 }) },
        currency_note: '1 line(s) carry a non-USD/blank opportunity currency code; amounts remain source-labelled USD',
      },
    );
    render(<CustomerPipeline customerName="Acme" />);
    await screen.findByTestId('customer-pipeline-totals');
    expect(screen.getByTestId('customer-pipeline-grain').textContent).toContain('(2 unidentified lines)');
    expect(screen.getByTestId('customer-pipeline-acv').textContent).toBe('Est. ACV $500 (partial — 3 of 4 lines)');
    expect(screen.getByTestId('customer-pipeline-tcv').textContent).toBe('Est. TCV $0.00 recorded');
    expect(screen.getByTestId('customer-pipeline-ambiguity').textContent).toContain("OPP-1 — stage: 'A', 'B'");
    expect(screen.getByTestId('customer-pipeline-coverage').textContent).toContain('never converted');
    expect(screen.getByTestId('customer-pipeline-currency-note').textContent).toContain('non-USD/blank');
  });
});

describe('CustomerPipeline — history, comparison, renewals', () => {
  const snap = (id: number, selected: boolean) => ({
    import_id: id, source_file: `f${id}.csv`, imported_at: `2026-10-${10 + id}T00:00:00Z`, imported_by: 'admin',
    line_count: 3, opportunity_count: 2, selected,
  });
  const cnt = (o: object = {}) => ({ overdue: 0, within_30: 0, within_60: 0, within_90: 0, within_180: 0, beyond_180: 0, unknown_date: 0, ...o });
  const emptyBuckets = { overdue: [], within_30: [], within_60: [], within_90: [], within_180: [], unknown_date: [], beyond_180_count: 0 };
  const renewals = (over: Record<string, unknown> = {}) => ({
    calculation_version: 'pipeline-renewal/1', as_of: 'x', reference_date: '2026-10-27',
    snapshot: { import_id: 2, source_file: 'f2.csv', imported_at: '2026-10-12T00:00:00Z' },
    buckets: emptyBuckets, counts: cnt(), note: 'n', ...over,
  });
  const card = (over: Record<string, unknown> = {}) => ({
    opportunity_number: '123', opportunity_name: 'RHEL renewal', renewal_date: '2026-11-16', days: 20, lines: 2,
    est_acv: group({ total: 5000, coverage: 'quantified', lines_included: 2 }),
    est_tcv: group({ lines_excluded: 2 }),
    reported_renewal: true, net_new_vs_renewal_values: ['Renewal'], conflicting_end_dates: [],
    original_contract_end: '2025-11-15', line_ids: [10, 11], line_source_rows: [4, 5], ...over,
  });
  const side = (id: number) => ({ import_id: id, source_file: `f${id}.csv`, imported_at: `2026-10-${10 + id}T00:00:00Z`, imported_by: 'admin', note: 'imported_at is import time, not a business effective date' });
  const opp = (n: string, over: Record<string, unknown> = {}) => ({
    opportunity_number: n, opportunity_name: `Opp ${n}`, stage_raw: 'Negotiate', stage_class: 'open', close_date: '2026-12-31',
    est_acv_usd: 1000, est_tcv_usd: null, reported_renewal: true, line_ids: [10], line_source_rows: [4, 5], ...over,
  });
  const comparison = (over: Record<string, unknown> = {}) => ({
    calculation_version: 'pipeline-snapshot-compare/1', as_of: 'x', from: side(1), to: side(2),
    opportunity_count: { from: 3, to: 4 }, unidentified: { from: 0, to: 0 },
    added: [], observed_removed: [], stage_changes: [], close_date_changes: [], name_changes: [], amount_changes: [], unchanged: [], ambiguity: [],
    notes: [
      'Observed-removed opportunities are absent from the later retained snapshot; this is not evidence of closed-lost, zero pipeline, or churn.',
      'No velocity or win rate is supported by snapshot observations alone.',
    ],
    ...over,
  });
  const base = (extra: Record<string, unknown> = {}) => ({
    customer_name: 'Acme', import_id: 2, source_file: 'f2.csv', imported_at: '2026-10-12T00:00:00Z',
    rows: [row()], totals: { ...totals(), deal_count: 1, line_count: 1 }, technologies: [], summary: summary(), ...extra,
  });

  it('history select appears only with >1 snapshots; lists priors only; 0/1 → no control', async () => {
    apiMock.getCustomerPipeline.mockResolvedValue(base({ history: [snap(2, true), snap(1, false)], renewals: renewals() }));
    render(<CustomerPipeline customerName="Acme" />);
    const hist = await screen.findByTestId('customer-pipeline-history');
    expect(hist.textContent).toContain('Comparing latest: import #2 · f2.csv');
    const sel = screen.getByTestId('customer-pipeline-compare-select') as HTMLSelectElement;
    expect(Array.from(sel.options).map((o) => o.value)).toEqual(['', '1']);
    cleanup();
    apiMock.getCustomerPipeline.mockResolvedValue(base({ history: [snap(2, true)] }));
    render(<CustomerPipeline customerName="Acme" />);
    await screen.findByTestId('customer-pipeline-source');
    expect(screen.queryByTestId('customer-pipeline-history')).toBeNull();
    cleanup();
    apiMock.getCustomerPipeline.mockResolvedValue(base());
    render(<CustomerPipeline customerName="Acme" />);
    await screen.findByTestId('customer-pipeline-source');
    expect(screen.queryByTestId('customer-pipeline-compare-select')).toBeNull();
    expect(screen.queryByTestId('customer-pipeline-comparison')).toBeNull();
  });

  it('select re-requests with compare_with; reset re-requests plain', async () => {
    apiMock.getCustomerPipeline.mockImplementation((_n: string, cw?: number) =>
      Promise.resolve(base({ history: [snap(2, true), snap(1, false)], ...(cw ? { comparison: comparison() } : {}) })));
    render(<CustomerPipeline customerName="Acme" />);
    const sel = await screen.findByTestId('customer-pipeline-compare-select');
    fireEvent.change(sel, { target: { value: '1' } });
    await screen.findByTestId('customer-pipeline-comparison');
    expect(apiMock.getCustomerPipeline).toHaveBeenLastCalledWith('Acme', 1);
    const reset = screen.getByTestId('customer-pipeline-compare-reset');
    expect(reset.textContent).toContain('Showing changes vs import #1');
    fireEvent.click(reset);
    await waitFor(() => expect(screen.queryByTestId('customer-pipeline-comparison')).toBeNull());
    expect(apiMock.getCustomerPipeline).toHaveBeenLastCalledWith('Acme');
  });

  it('comparison: header, every delta list with row linkage, observed-removed note, null sides, ambiguity, unidentified', async () => {
    const cmp = comparison({
      unidentified: { from: 1, to: 2 },
      added: [opp('A1')],
      observed_removed: [opp('R1', { line_source_rows: [7] })],
      stage_changes: [{ opportunity_number: 'S1', from_stage: 'Discover', to_stage: 'Negotiate', from_class: 'open', to_class: 'open', line_ids_from: [3], line_ids_to: [7] }],
      close_date_changes: [{ opportunity_number: 'C1', from_close_date: '2026-11-30', to_close_date: '2027-01-31', slip_days: 62, line_ids_from: [3], line_ids_to: [7] }],
      name_changes: [{ opportunity_number: 'N1', name_from: 'Old Name', name_to: 'New Name', line_ids_from: [3], line_ids_to: [7] }],
      amount_changes: [{ opportunity_number: 'M1', acv: { from: 1000, to: 1200, delta: 200 }, tcv: { from: null, to: 500, delta: null }, line_ids_from: [3], line_ids_to: [7] }],
      unchanged: ['U1', 'U2'],
      ambiguity: [{ opportunity_number: 'X1', from_conflicts: ["stage: 'A', 'B'"], to_conflicts: [], note: 'conflicting source values' }],
    });
    apiMock.getCustomerPipeline.mockResolvedValue(base({ history: [snap(2, true), snap(1, false)], comparison: cmp }));
    render(<CustomerPipeline customerName="Acme" />);
    const root = await screen.findByTestId('customer-pipeline-comparison');
    expect(root.textContent).toContain('Changes from import #1 (Oct 11, 2026) to import #2 (Oct 12, 2026)');
    const added = screen.getByTestId('customer-pipeline-comparison-added-A1').textContent!;
    expect(added).toContain('rows 4, 5 · import #2');
    const removed = screen.getByTestId('customer-pipeline-comparison-removed-R1').textContent!;
    expect(removed).toContain('rows 7 · import #1');
    expect(screen.getByTestId('customer-pipeline-comparison-removed-note').textContent).toContain('not evidence of closed-lost, zero pipeline, or churn');
    expect(screen.getByTestId('customer-pipeline-comparison-stage-S1').textContent).toContain('Discover (open) → Negotiate (open)');
    expect(screen.getByTestId('customer-pipeline-comparison-stage-S1').textContent).toContain('lines #3 · import #1 → lines #7 · import #2');
    expect(screen.getByTestId('customer-pipeline-comparison-close-C1').textContent).toContain('slipped 62 days later');
    const renamed = screen.getByTestId('customer-pipeline-comparison-name-N1').textContent!;
    expect(renamed).toContain('“Old Name” → “New Name”');
    expect(renamed).toContain('lines #3 · import #1 → lines #7 · import #2');
    const amount = screen.getByTestId('customer-pipeline-comparison-amount-M1').textContent!;
    expect(amount).toContain('ACV $1,000 → $1,200 (+$200)');
    expect(amount).toContain('TCV not recorded → $500 (no delta');
    expect(amount).not.toContain('$0');
    expect(screen.getByTestId('customer-pipeline-comparison-unchanged').textContent).toContain('U1');
    expect(screen.getByTestId('customer-pipeline-comparison-ambiguity-X1').textContent).toContain("import #1: stage: 'A', 'B' · import #2: no conflicts");
    expect(screen.getByTestId('customer-pipeline-comparison-unidentified').textContent).toContain('import #1: 1 · import #2: 2');
    expect(screen.queryByTestId('customer-pipeline-comparison-none')).toBeNull();
  });

  it('comparison with only observed-removed still carries the honesty note and no change line', async () => {
    apiMock.getCustomerPipeline.mockResolvedValue(base({ history: [snap(2, true), snap(1, false)], comparison: comparison({ observed_removed: [opp('R1')] }) }));
    render(<CustomerPipeline customerName="Acme" />);
    await screen.findByTestId('customer-pipeline-comparison-removed-R1');
    expect(screen.getByTestId('customer-pipeline-comparison-removed-note')).toBeTruthy();
    expect(screen.queryByTestId('customer-pipeline-comparison-none')).toBeNull();
  });

  it('all-zero deltas collapse to a single "No changes" line', async () => {
    apiMock.getCustomerPipeline.mockResolvedValue(base({ history: [snap(2, true), snap(1, false)], comparison: comparison({ unchanged: ['U1'] }) }));
    render(<CustomerPipeline customerName="Acme" />);
    const none = await screen.findByTestId('customer-pipeline-comparison-none');
    expect(none.textContent).toBe('No changes between these snapshots');
    expect(screen.queryByTestId('customer-pipeline-comparison-added')).toBeNull();
    expect(screen.queryByTestId('customer-pipeline-comparison-removed-note')).toBeNull();
  });

  it('renewals: chips, cards, tag, conflict note, historical original end, linkage, beyond-180 line', async () => {
    apiMock.getCustomerPipeline.mockResolvedValue(base({
      renewals: renewals({
        counts: cnt({ within_30: 2, unknown_date: 1, beyond_180: 2 }),
        buckets: {
          ...emptyBuckets,
          within_30: [card(), card({ opportunity_number: '124', days: 0, renewal_date: '2026-10-27', conflicting_end_dates: ['2026-10-27', '2026-12-31'], reported_renewal: false, original_contract_end: null })],
          unknown_date: [card({ opportunity_number: '125', renewal_date: null, days: null, original_contract_end: null, est_acv: group() })],
          beyond_180_count: 2,
        },
      }),
    }));
    render(<CustomerPipeline customerName="Acme" />);
    const chips = await screen.findByTestId('customer-pipeline-renewal-chips');
    expect(chips.textContent).toContain('30 days 2');
    expect(chips.textContent).toContain('Unknown date 1');
    expect(chips.textContent).toContain('Beyond 180 days 2');
    const c1 = screen.getByTestId('customer-pipeline-renewal-card-123').textContent!;
    expect(c1).toContain('Nov 16, 2026 · in 20 days');
    expect(c1).toContain('2 lines');
    expect(c1).toContain('Est. ACV $5,000');
    expect(c1).toContain('Est. TCV Not recorded');
    expect(c1).toContain('reported renewal');
    expect(c1).toContain('Original contract end Nov 15, 2025 (historical)');
    expect(c1).toContain('rows 4, 5 · import #2');
    const c2 = screen.getByTestId('customer-pipeline-renewal-card-124').textContent!;
    expect(c2).toContain('due today');
    expect(c2).not.toContain('reported renewal');
    expect(screen.getByTestId('customer-pipeline-renewal-conflict-124').textContent).toContain('Oct 27, 2026, Dec 31, 2026');
    const c3 = screen.getByTestId('customer-pipeline-renewal-card-125').textContent!;
    expect(c3).toContain('Current contract end date not recorded');
    expect(c3).not.toContain('$0');
    expect(screen.getByTestId('customer-pipeline-renewal-beyond').textContent).toBe('2 more end beyond 180 days');
  });

  it('renewals honest empties: snapshot with no dates; beyond-only; absent/no-data', async () => {
    apiMock.getCustomerPipeline.mockResolvedValue(base({ renewals: renewals() }));
    render(<CustomerPipeline customerName="Acme" />);
    expect((await screen.findByTestId('customer-pipeline-renewals-none')).textContent).toBe('No current contract end dates recorded in the latest snapshot');
    expect(screen.queryByTestId('customer-pipeline-renewal-chips')).toBeNull();
    cleanup();
    apiMock.getCustomerPipeline.mockResolvedValue(base({ renewals: renewals({ counts: cnt({ beyond_180: 3 }), buckets: { ...emptyBuckets, beyond_180_count: 3 } }) }));
    render(<CustomerPipeline customerName="Acme" />);
    await screen.findByTestId('customer-pipeline-renewal-beyond');
    expect(screen.queryByTestId('customer-pipeline-renewals-none')).toBeNull();
    cleanup();
    apiMock.getCustomerPipeline.mockResolvedValue({ ...base({ rows: [], renewals: renewals({ snapshot: null }) }) });
    render(<CustomerPipeline customerName="Acme" />);
    await screen.findByTestId('customer-pipeline-empty');
    expect(screen.queryByTestId('customer-pipeline-renewals')).toBeNull();
  });
});
