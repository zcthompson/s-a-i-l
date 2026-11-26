// H6 — account brief preview. Mirrors the normative S2 shape. Section dicts
// carry `available` + `source` plus section-specific fields the panel does not
// read (the backend-rendered `markdown` is what the panel shows).

export interface BriefSection {
  available: boolean;
  source: string | null;
  [field: string]: unknown;
}

export interface BriefSourceSnapshots {
  pipeline_import_id: number | null;
  pipeline_source_file: string | null;
  pipeline_imported_at: string | null;
  technology_recorded: number;
  notes_recorded: number;
  contacts_recorded: number;
  activities_recorded: number;
  open_tasks: number;
}

export const BRIEF_SECTION_KEYS = [
  'deals', 'account_snapshot', 'technology', 'pipeline', 'renewals', 'notes', 'attention',
  'contacts', 'persona_questions', 'engagement', 'activities', 'tasks',
] as const;
export type BriefSectionKey = (typeof BRIEF_SECTION_KEYS)[number];

export interface AccountBrief {
  customer_id: number;
  customer_name: string;
  generated_at: string;
  calc_version: string;
  source_snapshots: BriefSourceSnapshots;
  sections: Record<BriefSectionKey, BriefSection>;
  markdown: string;
}
