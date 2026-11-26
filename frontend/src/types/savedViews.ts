// E3 — saved views + personal worklist (normative FE contract).
// Backend: /api/saved-views/ + /api/worklist/mine/
import type { MyTask } from "./engagement";

export interface SavedView {
  id: number;
  name: string;
  surface: string;
  // The persisted H2 filter state (PORTFOLIO_FILTER_PARAMS keys only).
  params: Record<string, string | null>;
  schema_version: number;
  created_at: string;
  updated_at: string;
}

// API envelopes (the backend returns wrapped shapes).
export interface SavedViewsResponse {
  views: SavedView[];
}

export interface SaveViewResponse {
  view: SavedView;
  created: boolean;
}

export interface WorklistRenewal {
  customer_id: number;
  customer_name: string;
  opportunity_name: string | null;
  end_date: string | null;
  bucket: string;
  acv_usd: number | null;
  tcv_usd: number | null;
}

export interface WorklistQbr {
  customer_id: number;
  customer_name: string;
  state: "due_soon" | "overdue";
  next_qbr_due: string;
  days_until: number;
}

export interface ClosingDeal {
  id: number; customer_id: number; customer_name: string; name: string; close_date: string;
  amount: { minor: number; currency: string } | null; amount_basis: import('./deals').AmountBasis | null;
}
export interface WorklistResponse {
  closing_deals?: ClosingDeal[];
  // ISO UTC — the server's reference time (injected in tests).
  generated_at: string;
  // The existing /tasks/mine/ shape (my open/in_progress tasks only).
  tasks: MyTask[];
  // Most-urgent renewal per authorized account, capped at 20.
  renewals: WorklistRenewal[];
  // Authorized accounts with QBR due_soon/overdue, most overdue first.
  qbr: WorklistQbr[];
  truncated?: { closing_deals?: boolean; tasks: boolean; renewals: boolean; qbr: boolean };
}
