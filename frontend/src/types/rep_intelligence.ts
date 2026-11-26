/** Rep Intelligence Import contract (.hermes/scratch/gi_import_v2_contract.md §2.4/§2.5).
 *  Generic account-intelligence CSV → per-row outcomes + unverified technology records. */

export type RepImportStatus = 'completed' | 'completed_with_issues' | 'failed';
export type RepRowStatus = 'imported' | 'imported_with_issues' | 'skipped';
export type RepIssueSeverity = 'error' | 'warning' | 'info';
export type RepIssueDisposition = 'row_skipped' | 'field_omitted' | 'associated';

export interface RepIntelligenceIssue {
  field: string;
  code: string;
  severity: RepIssueSeverity;
  message: string;
  disposition: RepIssueDisposition;
  /** Raw supplied text when a field was omitted/invalid. */
  value?: string;
}

/** One source row. Customer fields are null when the row was skipped or the
 *  customer is outside the caller's scope. */
export interface RepIntelligenceRow {
  id: number;
  import_id: number;
  source_row: number;
  customer_name_supplied: string | null;
  customer_id: number | null;
  customer_name: string | null;
  technology_name_supplied: string | null;
  hardware_software: 'hardware' | 'software' | null;
  is_sale: 'yes' | 'no' | null;
  amount: number | null;
  currency: string | null;
  vendor: string | null;
  version: string | null;
  quantity: number | null;
  notes: string | null;
  technology_id: number | null;
  status: RepRowStatus;
  issues: RepIntelligenceIssue[];
  created_at: string;
}

export interface RepIntelligenceMatchedCustomer {
  customer_id: number;
  customer_name: string;
}

/** GET / list entry. */
export interface RepIntelligenceSummary {
  import_id: number;
  file_name: string;
  created_at: string;
  imported_by: string;
  total_rows: number;
  imported_rows: number;
  imported_with_issues: number;
  skipped_rows: number;
  status: RepImportStatus;
  technologies_created: number;
  technologies_refreshed: number;
}

/** POST (201) response: batch + full row list + matched customers. */
export interface RepIntelligenceResult extends RepIntelligenceSummary {
  file_sha256?: string;
  rows: RepIntelligenceRow[];
  matched: RepIntelligenceMatchedCustomer[];
  /** Rows skipped because no customer name or alias (you can write to) matched. */
  unmatched_customer_rows?: number;
  can_manage: boolean;
}

/** GET /{id}/ response. */
export interface RepIntelligenceDetail extends RepIntelligenceResult {
  matched_out_of_scope: number;
  affected_customer_ids?: number[];
}

export interface RepIntelligenceDeleteResult {
  detail: string;
  deleted_rows: number;
  deleted_technologies: number;
}
