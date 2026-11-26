// Honest pipeline amount formatters — all five coverage states + null.
import { describe, it, expect } from 'vitest';
import { formatAmountWithCoverage, formatDaysUntil, formatRenewalExposure, formatUsd, RENEWAL_BUCKET_LABELS } from '../src/lib/pipelineFormat';
import { formatImpact, formatPipelineAmount, pipelineKpi, renewalKpi, renewalRowLine } from '../src/lib/accountImpact';

describe('formatAmountWithCoverage', () => {
  it('formats each coverage state honestly', () => {
    expect(formatAmountWithCoverage(1234, 'quantified')).toBe('$1,234');
    expect(formatAmountWithCoverage(null, 'all_unknown')).toBe('Not recorded');
    expect(formatAmountWithCoverage(null, 'no_data')).toBe('Not recorded');
    expect(formatAmountWithCoverage(0, 'recorded_zero')).toBe('$0.00 recorded');
    expect(formatAmountWithCoverage(500, 'partial', { included: 3, excluded: 1 })).toBe('$500 (partial — 3 of 4 lines)');
    expect(formatAmountWithCoverage(500, 'partial')).toBe('$500 (partial)');
    expect(formatAmountWithCoverage(undefined, undefined)).toBe('Not recorded');
  });
  it('leaves formatUsd unchanged', () => {
    expect(formatUsd(null)).toBe('—');
    expect(formatUsd(1234)).toBe('$1,234');
  });
});

describe('formatPipelineAmount / pipelineKpi', () => {
  it('is honest for null and numbers', () => {
    expect(formatPipelineAmount(null)).toBe('Not recorded');
    expect(formatPipelineAmount(undefined, 'all_unknown')).toBe('Not recorded');
    expect(formatPipelineAmount(1500, 'quantified')).toBe('$1,500');
    expect(formatPipelineAmount(0, 'recorded_zero')).toBe('$0 recorded');
    expect(formatPipelineAmount(1500, 'partial')).toBe('$1,500 (partial)');
  });
  it('keeps ACV and TCV separate and handles an absent block', () => {
    const amt = (over: object) => ({ total: null, lines: 0, accounts_quantified: 0, accounts_partial: 0, accounts_recorded_zero: 0, accounts_all_unknown: 1, accounts_no_data: 0, ...over });
    const k = pipelineKpi({ calculation_version: 'v', as_of: 'x', note: '', acv: amt({ total: 2000, accounts_quantified: 1 }), tcv: amt({}) });
    expect(k).toEqual({ value: '$2,000 (partial)', detail: 'ACV · TCV Not recorded · 1 of 2 accounts with ACV evidence' });
    expect(pipelineKpi(undefined).value).toBe('Not recorded');
  });
});

describe('account impact currency and coverage', () => {
  it('does not invent currency and preserves partial and zero amounts', () => {
    expect(formatImpact(1500, 'quantified', null)).toBe('1,500 (currency not recorded)');
    expect(formatImpact(0, 'quantified', null)).toBe('0 (currency not recorded)');
    expect(formatImpact(1500, 'partial', 'USD')).toBe('$1,500 (partial)');
    expect(formatImpact(50, 'quantified', 'EUR')).toBe('50 EUR');
    expect(formatImpact(null, 'partial')).toBe('Partial evidence; not quantified');
    expect(formatImpact(null, 'not_quantified')).toBe('Not quantified');
  });
  it('distinguishes complete recorded zero from mixed unknown accounts', () => {
    const amount = (x: object) => ({total: 0, lines: 1, accounts_quantified: 0, accounts_partial: 0, accounts_recorded_zero: 1, accounts_all_unknown: 0, accounts_no_data: 0, ...x});
    const make = (x: object) => ({ calculation_version: 'v', as_of: 'x', note: '', acv: amount(x), tcv: amount({}) });
    expect(pipelineKpi(make({})).value).toBe('$0 recorded');
    expect(pipelineKpi(make({ accounts_all_unknown: 1 })).value).toBe('$0 (partial)');
    expect(pipelineKpi(make({ accounts_no_data: 1 })).value).toBe('$0 (partial)');
  });
});

describe('renewal formatters', () => {
  it('formatDaysUntil: null / 0 / negative / positive / singular', () => {
    expect(formatDaysUntil(null)).toBe('date not recorded');
    expect(formatDaysUntil(0)).toBe('due today');
    expect(formatDaysUntil(-5)).toBe('overdue by 5 days');
    expect(formatDaysUntil(-1)).toBe('overdue by 1 day');
    expect(formatDaysUntil(20)).toBe('in 20 days');
    expect(formatDaysUntil(1)).toBe('in 1 day');
  });
  it('bucket labels', () => {
    expect(RENEWAL_BUCKET_LABELS).toEqual({
      overdue: 'Overdue', within_30: '30 days', within_60: '60 days', within_90: '90 days',
      within_180: '180 days', unknown_date: 'Unknown date',
    });
  });
  it('formatRenewalExposure is coverage-honest', () => {
    expect(formatRenewalExposure({ total: 5000, coverage: 'quantified', lines_included: 2, lines_excluded: 0 })).toBe('$5,000');
    expect(formatRenewalExposure({ total: null, coverage: 'all_unknown', lines_included: 0, lines_excluded: 2 })).toBe('Not recorded');
    expect(formatRenewalExposure({ total: 100, coverage: 'partial', lines_included: 1, lines_excluded: 1 })).toBe('$100 (partial — 1 of 2 lines)');
    expect(formatRenewalExposure(undefined)).toBe('Not recorded');
  });
  const counts = (o: object) => ({ overdue: 0, within_30: 0, within_60: 0, within_90: 0, within_180: 0, beyond_180: 0, unknown_date: 0, ...o });
  const rollup = (o: object) => ({
    calculation_version: 'pipeline-renewal/1', as_of: 'x', reference_date: '2026-10-27',
    accounts_scoped: 2, accounts_with_renewal_evidence: 1, accounts_no_data: 1,
    counts: counts({}),
    exposure: { acv: { total: null, coverage: 'no_data', lines_included: 0, lines_excluded: 0 }, tcv: { total: null, coverage: 'no_data', lines_included: 0, lines_excluded: 0 } },
    next_renewals: [], ...o,
  });
  it('renewalKpi merges 90/180/beyond into 90d+ and stays honest when empty/absent', () => {
    const k = renewalKpi(rollup({
      counts: counts({ overdue: 2, within_30: 1, within_90: 1, within_180: 1, beyond_180: 1, unknown_date: 2 }),
      exposure: { acv: { total: 5000, coverage: 'quantified', lines_included: 2, lines_excluded: 0 }, tcv: { total: null, coverage: 'all_unknown', lines_included: 0, lines_excluded: 2 } },
      next_renewals: [{ customer_id: 1, customer_name: 'Acme', opportunity_number: '1', renewal_date: '2026-11-15', days: 19 }],
    }) as any);
    expect(k.value).toBe('2 overdue · 1 in 30d · 3 in 90d+ · 2 unknown date');
    expect(k.detail).toContain('Est. ACV exposure $5,000');
    expect(k.detail).toContain('Next: Acme Nov 15, 2026');
    expect(renewalKpi(rollup({}) as any).value).toBe('No renewal evidence recorded');
    expect(renewalKpi(undefined).value).toBe('No renewal evidence recorded');
    expect(renewalKpi(rollup({ counts: counts({ within_30: 1 }) }) as any).detail).toContain('ACV exposure Not recorded');
  });
  it('renewalRowLine', () => {
    expect(renewalRowLine(undefined)).toBe('—');
    expect(renewalRowLine({ counts: counts({}), acv_exposure: null, next_renewal: null })).toBe('—');
    expect(renewalRowLine({ counts: counts({ overdue: 1, within_30: 1 }), acv_exposure: 5, next_renewal: '2026-11-15' })).toBe('1 overdue · next Nov 15, 2026');
    expect(renewalRowLine({ counts: counts({ unknown_date: 1 }), acv_exposure: null, next_renewal: null })).toBe('0 overdue · next —');
    // beyond-180 alone is not "attention"
    expect(renewalRowLine({ counts: counts({ beyond_180: 3 }), acv_exposure: null, next_renewal: null })).toBe('—');
  });
});
