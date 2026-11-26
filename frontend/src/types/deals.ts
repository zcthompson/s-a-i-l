// E6 — rep-owned deals and admin-managed pipeline stages.

export type StageClass = 'open' | 'won' | 'lost';
export type AmountBasis = 'one_time' | 'acv' | 'tcv' | 'mrr';
export type DealType = 'new' | 'expansion' | 'renewal' | 'services';

export interface PipelineStage {
  id: number;
  key: string;
  label: string;
  stage_class: StageClass;
  position: number;
  active: boolean;
  /** D5: a suggestion only — never stored on a deal implicitly. */
  default_probability: number | null;
}

export interface DealContactLink {
  contact_id: number;
  role: string | null;
}

export interface Deal {
  id: number;
  customer_id: number;
  name: string;
  owner_user_id: number | null;
  owner_name: string | null;
  stage: PipelineStage;
  stage_id: number;
  probability: number | null;
  suggested_probability: number | null;
  close_date: string | null;
  amount: { minor: number; currency: string } | null;
  amount_minor: number | null;
  currency: string;
  amount_basis: AmountBasis | null;
  deal_type: DealType | null;
  next_step: string | null;
  next_step_date: string | null;
  closed_reason: string | null;
  closed_at: string | null;
  source_type: string | null;
  source_id: number | null;
  source_key: string | null;
  created_by: string;
  created_at: string | null;
  updated_at: string | null;
  version: number;
  vendor_evidence?: { import_id: number; opportunity_number: string }[];
  contacts: DealContactLink[];
  task_ids: number[];
  activity_ids: number[];
  note_ids: number[];
  technology_ids: number[];
}

export interface DealHistoryEntry {
  from_stage: string | null;
  to_stage: string | null;
  actor: string;
  at: string;
  amount: { minor: number; currency: string } | null;
  amount_basis: AmountBasis | null;
  close_date: string | null;
  note: string | null;
}

export interface DealInput {
  contacts?: DealContactLink[];
  task_ids?: number[];
  activity_ids?: number[];
  note_ids?: number[];
  technology_ids?: number[];
  vendor_evidence?: { import_id: number; opportunity_number: string }[];
  name?: string;
  owner_user_id?: number | null;
  stage_id?: number;
  close_date?: string | null;
  amount_minor?: number | null;
  currency?: string;
  amount_basis?: AmountBasis | null;
  probability?: number | null;
  deal_type?: DealType | null;
  next_step?: string | null;
  next_step_date?: string | null;
  closed_reason?: string | null;
}
