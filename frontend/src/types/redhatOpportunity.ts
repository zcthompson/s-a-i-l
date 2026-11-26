export interface RedHatOpportunityImportResult {
  import_id: number;
  total_rows: number;
  matched_rows: number;
  matched_accounts: number;
  skipped: { source_row: number; account: string; reason: string;
    suggestion?: { customer_id: number; customer_name: string } | null }[];
}

export interface RedHatOpportunityImportSummary {
  import_id: number;
  file_name: string;
  imported_by: string;
  created_at: string;
  total_rows: number;
  matched_rows: number;
  matched_accounts: number;
}

export interface RedHatOpportunityReport {
  import: { import_id: number; file_name: string; created_at: string } | null;
  matched_account: string;
  opportunities: { type: string; title: string; vendors: string[]; redhat_representatives: string[] }[];
}
