/** Intelligence Import contract (.hermes/scratch/pipeline_import_contract.md).
 *  Partner pipeline report CSV → matched customers + unmatched report. */

export interface IntelligenceImportSummary {
  import_id: number;
  file_name: string;
  created_at: string;
  imported_by: string;
  total_rows: number;
  matched_accounts: number;
  matched_rows: number;
  unmatched_accounts: number;
  /** Rows not imported (no matching customer name or alias). */
  skipped_rows: number;
}

/** One spelling a file used for a matched account. */
export interface IntelligenceImportSuppliedName {
  name: string;
  row_count: number;
  matched_by: 'name' | 'alias';
}

export interface IntelligenceImportMatched {
  customer_name: string;
  customer_id: number;
  account_name: string;
  row_count: number;
  knowledge_id: number;
  matched_by: 'name' | 'alias';
  supplied_names: IntelligenceImportSuppliedName[];
  est_acv_total: number | null;
  est_tcv_total: number | null;
  amount_coverage?: { acv: PipelineAmountCoverage; tcv: PipelineAmountCoverage };
  /** Technology records this import owns for the account (renewal-derived, sorted). */
  technologies: string[];
}

export interface IntelligenceImportUnmatched {
  account_name: string;
  row_count: number;
  /** ambiguous = the name equals more than one customer (name or alias). */
  reason: 'unmatched' | 'ambiguous';
}

/** An imported row whose amount cell could not be read (recorded as unknown). */
export interface IntelligenceImportAmountIssue {
  source_row: number;
  column: string;
  value: string;
}

/** One partner_pipeline row (dates are ISO strings or null). */
export interface PartnerPipelineRow {
  id: number;
  import_id: number;
  customer_id: number;
  customer_account_name: string;
  opportunity_name: string | null;
  opportunity_number: string | null;
  opp_stage: string | null;
  forecast_category: string | null;
  net_new_vs_renewal: string | null;
  route_to_market: string | null;
  opportunity_channel: string | null;
  partner_account: string | null;
  partner_tier: string | null;
  product_offering_group: string | null;
  product_sku: string | null;
  product_description: string | null;
  est_acv_usd: number | null;
  est_tcv_usd: number | null;
  currency_code: string | null;
  close_date: string | null;
  contract_start_date: string | null;
  contract_end_date: string | null;
  current_contract_start_date: string | null;
  current_contract_end_date: string | null;
  fiscal_quarter: string | null;
  growth_risk_flag: string | null;
  deal_reg_approval_status: string | null;
  opp_create_date: string | null;
  source_row: number | null;
  created_at: string;
}

/** POST response. */
export interface IntelligenceImportResult extends IntelligenceImportSummary {
  file_sha256: string;
  matched: IntelligenceImportMatched[];
  unmatched: IntelligenceImportUnmatched[];
  amount_issues: IntelligenceImportAmountIssue[];
}

/** GET /{id}/ response. */
export interface IntelligenceImportDetail extends IntelligenceImportResult {
  pipeline_rows: PartnerPipelineRow[];
  matched_out_of_scope: number;
}

export interface IntelligenceImportDeleteResult {
  detail: string;
  deleted_rows: number;
  deleted_knowledge: number;
  deleted_technologies: number;
}

/** Amount coverage states (H1): never a fabricated $0. */
export type PipelineAmountCoverage =
  | 'no_data' | 'all_unknown' | 'recorded_zero' | 'partial' | 'quantified';

export interface PipelineAmountGroup {
  total: number | null;
  coverage: PipelineAmountCoverage;
  lines_included: number;
  lines_excluded: number;
}

/** Canonical read-model summary (H1). source is null for no_data. */
export interface CustomerPipelineSummary {
  calculation_version: string;
  as_of: string;
  source: {
    source_type: string;
    import_id: number;
    source_file: string | null;
    imported_at: string | null;
    imported_by: string | null;
    note: string;
  } | null;
  currency_basis: string | null;
  currency_codes: string[];
  currency_note: string | null;
  grain: {
    line_count: number;
    opportunity_count: number;
    unidentified_lines: number;
    ambiguous_opportunities: Array<{ opportunity_number: string; conflicts: string[] }>;
  };
  stages: {
    open: number;
    won: number;
    lost: number;
    unknown: number;
    unknown_stage_values: string[];
  };
  amounts: { acv: PipelineAmountGroup; tcv: PipelineAmountGroup };
  forecast_categories: Record<string, number>;
  reporting: {
    fiscal_quarters?: Record<string, number>;
    net_new_vs_renewal?: Record<string, number>;
  };
  precision_note?: string;
}

export interface CustomerPipelineTotals {
  /** Source line items in the latest snapshot. */
  line_count: number;
  /** Distinct identified opportunities (not lines). */
  deal_count: number;
  /** Opportunities at an open stage. */
  open_deals: number;
  /** Opportunities at an unknown stage. */
  unknown_deals: number;
  growth: number;
  risk: number;
  /** Line total; null when no line records an amount. */
  est_acv_total: number | null;
  est_tcv_total: number | null;
  amount_coverage: { acv: PipelineAmountCoverage; tcv: PipelineAmountCoverage };
}

export interface CustomerPipeline {
  customer_name: string;
  import_id: number | null;
  source_file: string | null;
  imported_at: string | null;
  rows: PartnerPipelineRow[];
  totals: CustomerPipelineTotals;
  /** Technology records the latest import owns for this account (renewal-derived, sorted). */
  technologies: string[];
  /** Read-model summary for the same snapshot (additive). */
  summary?: CustomerPipelineSummary;
  /** H3: retained snapshots for this account, newest first (additive). */
  history?: PipelineSnapshot[];
  /** H3: renewal attention over the selected snapshot (additive). */
  renewals?: RenewalAttention;
  /** H3: present ONLY when requested with ?compare_with= (absent otherwise). */
  comparison?: PipelineComparison;
}

/** H3 contract S2 — one retained snapshot (import batch) for an account. */
export interface PipelineSnapshot {
  import_id: number;
  source_file: string | null;
  imported_at: string | null;
  imported_by: string | null;
  line_count: number;
  opportunity_count: number;
  /** True on the latest retained batch (the snapshot the current view reads). */
  selected: boolean;
}

/** H3 contract S3 — snapshot side descriptor. imported_at is import time. */
export interface ComparisonSide {
  import_id: number;
  source_file: string | null;
  imported_at: string | null;
  imported_by: string | null;
  note: string;
}

export interface ComparisonOpportunity {
  opportunity_number: string;
  opportunity_name: string | null;
  stage_raw: string | null;
  stage_class: string;
  close_date: string | null;
  est_acv_usd: number | null;
  est_tcv_usd: number | null;
  reported_renewal: boolean;
  line_ids: number[];
  line_source_rows: Array<number | null>;
}

export interface ComparisonAmountSide {
  from: number | null;
  to: number | null;
  delta: number | null;
}

/** H3 contract S3 — opportunity-level comparison of two retained snapshots. */
export interface PipelineComparison {
  calculation_version: string;
  as_of: string;
  from: ComparisonSide;
  to: ComparisonSide;
  opportunity_count: { from: number; to: number };
  unidentified: { from: number; to: number };
  added: ComparisonOpportunity[];
  observed_removed: ComparisonOpportunity[];
  stage_changes: Array<{
    opportunity_number: string;
    from_stage: string | null;
    to_stage: string | null;
    from_class: string;
    to_class: string;
    line_ids_from: number[];
    line_ids_to: number[];
  }>;
  close_date_changes: Array<{
    opportunity_number: string;
    from_close_date: string | null;
    to_close_date: string | null;
    slip_days: number;
    line_ids_from: number[];
    line_ids_to: number[];
  }>;
  /** H3 ruling 2026-10-27: renames are a first-class observed change. */
  name_changes: Array<{
    opportunity_number: string;
    name_from: string | null;
    name_to: string | null;
    line_ids_from: number[];
    line_ids_to: number[];
  }>;
  amount_changes: Array<{
    opportunity_number: string;
    acv: ComparisonAmountSide;
    tcv: ComparisonAmountSide;
    line_ids_from: number[];
    line_ids_to: number[];
  }>;
  unchanged: string[];
  ambiguity: Array<{
    opportunity_number: string;
    from_conflicts: string[];
    to_conflicts: string[];
    note: string;
  }>;
  notes: string[];
}

/** H3 contract S4 — one renewal-attention card (one per opportunity). */
export interface RenewalCard {
  opportunity_number: string;
  opportunity_name: string | null;
  /** Null for unknown_date cards. */
  renewal_date: string | null;
  days: number | null;
  lines: number;
  est_acv: PipelineAmountGroup;
  est_tcv: PipelineAmountGroup;
  reported_renewal: boolean;
  net_new_vs_renewal_values: string[];
  conflicting_end_dates?: string[];
  original_contract_end: string | null;
  line_ids: number[];
  line_source_rows: Array<number | null>;
}

export type RenewalBucketKey =
  | 'overdue' | 'within_30' | 'within_60' | 'within_90' | 'within_180' | 'unknown_date';

export interface RenewalCounts {
  overdue: number;
  within_30: number;
  within_60: number;
  within_90: number;
  within_180: number;
  beyond_180: number;
  unknown_date: number;
}

export interface RenewalAttention {
  calculation_version: string;
  as_of: string;
  reference_date: string;
  /** Null = no selected snapshot (no_data), not "no renewals". */
  snapshot: { import_id: number; source_file: string | null; imported_at: string | null } | null;
  buckets: Record<RenewalBucketKey, RenewalCard[]> & { beyond_180_count: number };
  counts: RenewalCounts;
  note: string;
}

/** H3 contract S5 — per-customer row on the portfolio payload (additive). */
export interface PortfolioRenewalRow {
  counts: RenewalCounts;
  acv_exposure: number | null;
  next_renewal: string | null;
}

/** H3 contract S5 — scoped-portfolio renewal rollup. */
export interface PortfolioRenewal {
  calculation_version: string;
  as_of: string;
  reference_date: string;
  accounts_scoped: number;
  accounts_with_renewal_evidence: number;
  accounts_no_data: number;
  counts: RenewalCounts;
  exposure: { acv: PipelineAmountGroup; tcv: PipelineAmountGroup };
  next_renewals: Array<{
    customer_id: number;
    customer_name: string;
    opportunity_number: string;
    renewal_date: string;
    days: number;
  }>;
}
