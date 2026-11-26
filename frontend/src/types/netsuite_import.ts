/**
 * NetSuite Intelligence Import — API contracts (NS-07 frontend).
 *
 * Mirrors `backend/routes/netsuite_import.py` +
 * `backend/services/netsuite_import_service.py`:
 * - POST /api/netsuite-import/            → NetSuiteImportDetail
 * - GET  /api/netsuite-import/            → NetSuiteImportSummary[] (history)
 * - GET  /api/netsuite-import/{id}/       → NetSuiteImportDetail
 * - GET  /api/netsuite-import/{id}/unmatched/ → NetSuiteImportRow[]
 * - POST /api/netsuite-import/{id}/rematch/   → NetSuiteImportDetail
 *
 * Summary counters describe the latest import/re-match action; scoped
 * readers get the same keys recomputed from visible evidence. `quantity`
 * is the normalized seat-count string from the report (or null — the
 * backend stores it as text). Financial columns never appear here.
 */

export type NetSuiteDisposition =
  | 'created'
  | 'refreshed'
  | 'associated'
  | 'skipped'
  | 'customer_deleted';

/** Row-level counters + batch identity shared by history and detail. */
export interface NetSuiteImportSummary {
  import_id: number;
  file_name: string;
  /** Report layout extension: 'csv' | 'xlsx' */
  layout: string;
  /** Latest invoice date in the file (ISO date) or null. */
  invoice_date: string | null;
  created_at: string;
  imported_by: string;
  /** 'complete' | 'complete_with_skips' */
  status: string;
  total_rows: number;
  matched_rows: number;
  matched_accounts: number;
  skipped_rows: number;
  /** Latest action only — not cumulative across re-matches. */
  technologies_created: number;
  technologies_refreshed: number;
  technologies_associated: number;
  risks_created: number;
  risks_refreshed: number;
  observations_created: number;
}

/** Single globally-unambiguous accessible suggestion; never a match. */
export interface NetSuiteSuggestion {
  customer_id: number;
  customer_name: string;
}

/** One staged subscription row from the uploaded report. */
export interface NetSuiteImportRow {
  id: number;
  /** Supplied End Customer Name (never modified by the import). */
  customer_name: string | null;
  subscription_id: string | null;
  product: string | null;
  term_end: string | null;
  detail_type: string | null;
  /** Normalized seat-count string, or null when unknown/not a seat UOM. */
  quantity: string | null;
  uom: string | null;
  term: string | null;
  term_type: string | null;
  invoice_date: string | null;
  status: string | null;
  notes: string | null;
  source_row: number;
  customer_id: number | null;
  /** 'name' | 'alias' when applied, else null. */
  matched_by: string | null;
  vendor: string | null;
  technology_id: number | null;
  risk_note_id: number | null;
  observation_note_id: number | null;
  disposition: NetSuiteDisposition;
  reason: string | null;
  /** Present only for rows that were not applied (or whose customer was deleted). */
  suggestion: NetSuiteSuggestion | null;
}

/** Stable risk-note identity for one subscription (kind dedupes across batches). */
export interface NetSuiteRiskNoteKey {
  customer_id: number;
  subscription_id: string;
  kind: string;
  note_id: number;
}

/** Detail = summary + staged rows + risk-note evidence + skipped rows. */
export interface NetSuiteImportDetail extends NetSuiteImportSummary {
  rows: NetSuiteImportRow[];
  /** Risk notes (no original observations) currently on record. */
  risk_notes: NetSuiteRiskNoteKey[];
  /** risk_notes.length — risks on record for this batch's subscriptions. */
  risks: number;
  /** Rows not in a created/refreshed/associated disposition (read-only). */
  skipped: NetSuiteImportRow[];
}
