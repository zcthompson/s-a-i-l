// H4 — customer-owned contacts + buying coverage. Field-for-field with the
// backend contract (schemas/contact.py). Unknown values are null, never "".

export type ContactVerificationState = 'verified' | 'unverified' | 'inferred';

export const BUYING_ROLES = [
  'economic_buyer',
  'decision_maker',
  'champion',
  'technical_buyer',
  'influencer',
  'end_user',
] as const;
export type BuyingRoleId = (typeof BUYING_ROLES)[number];

export const BUYING_ROLE_LABELS: Record<BuyingRoleId, string> = {
  economic_buyer: 'Economic buyer',
  decision_maker: 'Decision maker',
  champion: 'Champion',
  technical_buyer: 'Technical buyer',
  influencer: 'Influencer',
  end_user: 'End user',
};

export interface BuyingRole {
  role: string;
  role_label: string;
  source: string | null;
  observation_date: string | null;
  verification_state: string;
}

export interface BuyingRoleInput {
  role: string;
  source?: string | null;
  observation_date?: string | null;
  verification_state?: string;
}

export interface CustomerContact {
  id: number;
  customer_id: number;
  display_name: string;
  title: string | null;
  email: string | null;
  phone: string | null;
  department: string | null;
  persona: string | null;
  persona_label: string | null;
  source: string | null;
  observation_date: string | null;
  verification_state: string;
  buying_roles: BuyingRole[];
  related_note_ids: number[];
  related_use_case_ids: number[];
  related_technology_ids: number[];
  note_count: number;
  archived: boolean;
  archived_at: string | null;
  created_by: string | null;
  updated_by: string | null;
  created_at: string;
  updated_at: string;
}

export interface ContactCreate {
  display_name: string;
  title?: string | null;
  email?: string | null;
  phone?: string | null;
  department?: string | null;
  persona?: string | null;
  source?: string | null;
  observation_date?: string | null;
  verification_state?: string;
  buying_roles?: BuyingRoleInput[];
  related_note_ids?: number[];
  related_use_case_ids?: number[];
  related_technology_ids?: number[];
}

export interface ContactUpdate extends Partial<ContactCreate> {
  archived?: boolean | null;
}

export interface ContactCoverage {
  customer_id: number;
  calc_version: string;
  source: string;
  contacts_recorded: number;
  archived_count: number;
  roles: Record<string, number>;
  economic_buyer_recorded: boolean;
  champion_recorded: boolean;
  personas: Record<string, number>;
  persona_unknown: number;
  gaps: string[];
  last_contacted: string | null;
  last_contacted_basis: string;
}
