// In-account cross-module search (normative FE contract).
// Backend: GET /api/customers/{customer_id}/search/?q=

export type AccountSearchModule =
  | "deal"
  | "use_case"
  | "note"
  | "contact"
  | "activity"
  | "task"
  | "technology"
  | "strategy"
  | "knowledge";

export interface AccountSearchItem {
  module: AccountSearchModule;
  id: number;
  title: string;
  // Plain-text window (≤160 chars) around the first match; render as text.
  snippet: string;
  // ISO-8601; null when the source record is undated.
  timestamp: string | null;
  // true when timestamp is date-granularity.
  date_only: boolean;
}

export interface AccountSearchResponse {
  customer_id: number;
  // The trimmed query that was searched.
  query: string;
  // Returned (capped) per-module counts.
  counts: Record<AccountSearchModule, number>;
  results: AccountSearchItem[];
  // true when at least one module had more matches than its cap.
  truncated: boolean;
}
