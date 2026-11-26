// Account 360 timeline + QBR cadence (normative FE contract).
// Backend: GET /api/customers/{customer_id}/timeline/

export type TimelineKind =
  | "note"
  | "activity"
  | "task"
  | "contact"
  | "pipeline_import"
  | "rep_import"
  | "rvtools_import"
  | "strategy_snapshot"
  | "qbr"
  | "deal"
  | "membership";

export interface TimelineItem {
  kind: TimelineKind;
  // null for computed kinds (qbr).
  id: number | null;
  title: string;
  detail: string | null;
  actor: string | null;
  // ISO-8601 UTC; null when the source item is undated.
  timestamp: string | null;
  // true when timestamp is date-granularity (date-only sources).
  date_only: boolean;
  // true for import-derived or non-business events (imports, computed qbr).
  imported: boolean;
  // Stable FE fragment "module=<kind>&id=<id>" (null for qbr).
  source_ref: string | null;
}

export interface TimelineQbr {
  last_qbr_date: string | null;
  cadence_days: number;
  next_qbr_due: string | null;
  state: "not_recorded" | "current" | "due_soon" | "overdue";
  // null when not_recorded; negative when overdue.
  days_until: number | null;
}

export interface AccountTimelineResponse {
  customer_id: number;
  qbr: TimelineQbr;
  items: TimelineItem[];
  // Opaque cursor for the next page (null when no more items).
  next_cursor: string | null;
  more: boolean;
}
