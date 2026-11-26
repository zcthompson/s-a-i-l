import { api } from './api';
import type { AccountImpactCoverage, PortfolioAccountImpact, PortfolioPipeline } from '../types/use_case';
import type { PortfolioRenewal, PortfolioRenewalRow } from '../types/intelligence_import';
import { formatDate } from './pipelineFormat';

/** Load the portfolio account-impact contract; null when unavailable. */
export async function loadPortfolioImpact(myView?: boolean): Promise<PortfolioAccountImpact | null> {
  try {
    const data = await api.getPortfolioAccountImpact(myView);
    return data && typeof data === 'object' && 'coverage' in data && 'total_impact' in data ? data : null;
  } catch {
    return null;
  }
}

/** Do not infer a currency or completeness from a numeric estimate. */
export function formatImpact(value: number | null | undefined, coverage?: AccountImpactCoverage, currency?: string | null): string {
  if (value === null || value === undefined) {
    return coverage === 'partial' ? 'Partial evidence; not quantified' : 'Not quantified';
  }
  const number = value.toLocaleString();
  const amount = currency === 'USD' ? `$${number}` : currency ? `${number} ${currency}` : `${number} (currency not recorded)`;
  return coverage === 'partial' ? `${amount} (partial)` : amount;
}

/** Explicitly describe how much of the portfolio contributed to impact. */
export function impactCoverage(impact: PortfolioAccountImpact): string {
  if (!impact.rollup) return 'Coverage unavailable';
  const { quantified, partial, not_quantified } = impact.rollup;
  return `${quantified} of ${impact.customer_count} accounts quantified · ${partial} partial · ${not_quantified} not quantified`;
}

/** Honest pipeline money label: "Not recorded" for null (never a fabricated 0). */
export function formatPipelineAmount(value: number | null | undefined, coverage?: string | null): string {
  if (coverage === 'recorded_zero') return '$0 recorded';
  if (value === null || value === undefined) return 'Not recorded';
  const amount = `$${value.toLocaleString()}`;
  return coverage === 'partial' ? `${amount} (partial)` : amount;
}

export const PIPELINE_KPI_LABEL = 'Partner pipeline — unweighted, source-labelled USD';

/** Portfolio pipeline KPI text: ACV headline, TCV kept separate (never summed). */
export function pipelineKpi(pipeline: PortfolioPipeline | null | undefined): { value: string; detail: string } {
  if (!pipeline) return { value: 'Not recorded', detail: 'ACV · no pipeline data' };
  const cov = (a: PortfolioPipeline['acv']) =>
    a.total === null ? 'all_unknown'
      : (a.accounts_partial > 0 || a.accounts_all_unknown > 0 || a.accounts_no_data > 0) ? 'partial'
        : a.accounts_quantified === 0 && a.accounts_recorded_zero > 0 ? 'recorded_zero' : 'quantified';
  const tcv = formatPipelineAmount(pipeline.tcv.total, cov(pipeline.tcv));
  const acv = pipeline.acv;
  const totalAccounts = acv.accounts_quantified + acv.accounts_partial + acv.accounts_recorded_zero + acv.accounts_all_unknown + acv.accounts_no_data;
  const coverage = `${acv.accounts_quantified + acv.accounts_partial + acv.accounts_recorded_zero} of ${totalAccounts} accounts with ACV evidence`;
  return { value: formatPipelineAmount(acv.total, cov(acv)), detail: `ACV · TCV ${tcv} · ${coverage}` };
}

export const RENEWAL_KPI_LABEL = 'Renewals — vendor-reported';

/** Portfolio renewal KPI text (H3). 90d+ merges within_90 + within_180 + beyond_180
 *  for display only. Empty/absent → honest "No renewal evidence recorded". */
export function renewalKpi(renewals: PortfolioRenewal | null | undefined): { value: string; detail: string } {
  const empty = { value: 'No renewal evidence recorded', detail: 'Current contract end dates are not in the latest snapshots' };
  if (!renewals) return empty;
  const c = renewals.counts;
  const far = c.within_90 + c.within_180 + c.beyond_180;
  const parts: string[] = [];
  if (c.overdue > 0) parts.push(`${c.overdue} overdue`);
  if (c.within_30 > 0) parts.push(`${c.within_30} in 30d`);
  if (c.within_60 > 0) parts.push(`${c.within_60} in 60d`);
  if (far > 0) parts.push(`${far} in 90d+`);
  if (c.unknown_date > 0) parts.push(`${c.unknown_date} unknown date`);
  if (parts.length === 0) return empty;
  const next = renewals.next_renewals[0];
  const detail = [
    `Est. ACV exposure ${formatPipelineAmount(renewals.exposure.acv.total, renewals.exposure.acv.coverage)}`,
    next ? `Next: ${next.customer_name} ${formatDate(next.renewal_date)}` : null,
  ].filter(Boolean).join(' · ');
  return { value: parts.join(' · '), detail };
}

/** Per-customer compact renewals line (H3). */
export function renewalRowLine(r: PortfolioRenewalRow | null | undefined): string {
  if (!r) return '—';
  const c = r.counts;
  const dated = c.overdue + c.within_30 + c.within_60 + c.within_90 + c.within_180;
  if (dated + c.unknown_date === 0) return '—';
  return `${c.overdue} overdue · next ${r.next_renewal ? formatDate(r.next_renewal) : '—'}`;
}
