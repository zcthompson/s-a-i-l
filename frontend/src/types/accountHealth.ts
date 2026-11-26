// E5 — account health components + lifecycle/EOL attention (normative FE contract).
// Backend: GET /api/customers/{customer_id}/health/
// The health surface is a set of EXPLAINED COMPONENTS — never a composite
// score (no traffic-light rollup, no 0-100 blend). Unknowns stay honest.

export interface HealthEngagement {
  last_contacted: string | null;
  days_since: number | null;
  // Verbatim from the H5 contact-coverage basis string.
  basis: string;
}

export interface HealthRenewals {
  // The H3 snapshot metadata (import id / source / imported-at) or null.
  snapshot: Record<string, unknown> | null;
  counts: Record<string, number>;
  // Decimal sum of the dated renewal cards' known totals (H1 rules);
  // coverage: no_data (no dated cards) | complete | partial (unknowns excluded,
  // never zero-filled).
  exposure: { acv: number | null; tcv: number | null; coverage: "no_data" | "complete" | "partial" };
  basis: string;
}

export interface HealthBuyingCoverage {
  contacts_recorded: number;
  economic_buyer_recorded: boolean;
  champion_recorded: boolean;
  roles: Record<string, number>;
  gaps: string[];
}

export interface HealthTasks {
  open: number;
  in_progress: number;
  overdue: number;
  basis: string;
}

export interface HealthEolItem {
  id: number;
  name: string;
  vendor: string | null;
  end_of_support_date: string | null;
  eol_source: string | null;
  lifecycle_state: string | null;
  business_criticality: string | null;
}

export interface HealthEol {
  dated_count: number;
  items: HealthEolItem[];
}

export interface HealthDataFreshness {
  pipeline_import: string | null;
  rep_import: string | null;
  rvtools_import: string | null;
  latest_note: string | null;
  latest_activity: string | null;
}

export interface AccountHealthResponse {
  customer_id: number;
  calc_version: string;
  as_of: string;
  components: {
    engagement: HealthEngagement;
    renewals: HealthRenewals;
    buying_coverage: HealthBuyingCoverage;
    tasks: HealthTasks;
    eol: HealthEol;
    data_freshness: HealthDataFreshness;
  };
}
