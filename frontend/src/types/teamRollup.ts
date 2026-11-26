// E4 — GET /api/rollups/team/ (active sales managers only).

export interface TeamRollupAmount {
  total: number | null;
  coverage: 'no_data' | 'all_unknown' | 'partial' | 'recorded_zero' | 'quantified';
  lines_included: number;
  lines_excluded: number;
  accounts_no_data: number;
}

export interface TeamRollupSummary {
  rep_deals?: { counts: { open: number; won: number; lost: number }; open_amounts: { currency: string; basis: string | null; minor: number | null; unknown_amounts: number }[] };
  accounts: number;
  pipeline: {
    acv: TeamRollupAmount;
    tcv: TeamRollupAmount;
    stages: { open: number; won: number; lost: number; unknown: number };
  };
  renewal_counts: {
    overdue: number; within_30: number; within_60: number; within_90: number; within_180: number;
    beyond_180: number; unknown_date: number;
  };
  open_tasks: number;
  overdue_tasks: number;
  no_recorded_interaction: number;
  no_contacts_recorded: number;
  no_economic_buyer_recorded: number;
  no_champion_recorded: number;
}

export interface TeamRollupRep extends TeamRollupSummary {
  user_id: number;
  username: string;
  display_name: string | null;
}

export interface TeamRollupResponse {
  generated_at: string;
  team: TeamRollupSummary;
  reps: TeamRollupRep[];
  basis: string;
}
