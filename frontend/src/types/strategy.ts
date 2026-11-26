// H7 — account strategy. Field-for-field with the normative response shapes
// (contract C2/C3/C4). Suggestions are computed read-only by the backend from
// recorded evidence; the FE only prefills EMPTY drafts (lib/strategy.ts).

export const STRATEGY_FIELDS = [
  'objectives', 'desired_outcomes', 'risks', 'plays', 'discovery_gaps',
] as const;
export type StrategyField = (typeof STRATEGY_FIELDS)[number];

export const STRATEGY_FIELD_LABELS: Record<StrategyField, string> = {
  objectives: 'Objectives',
  desired_outcomes: 'Desired outcomes',
  risks: 'Risks',
  plays: 'Plays',
  discovery_gaps: 'Discovery gaps',
};

/** Recorded plan text per field — null means "not recorded". */
export type StrategyFieldValues = Record<StrategyField, string | null>;

export interface StrategyLinkedTask {
  task_id: number;
  title: string;
  status: string;
}

export interface StrategyLinkedContact {
  contact_id: number;
  display_name: string;
}

export interface StrategyLinkedNote {
  note_id: number;
  title: string | null;
}

export interface StrategyLinks {
  tasks: StrategyLinkedTask[];
  contacts: StrategyLinkedContact[];
  notes: StrategyLinkedNote[];
}

/**
 * The editable plan. `links` is present on the GET response only — the
 * PUT/restore responses return the plan dict without it (contract C2).
 */
export interface StrategyPlan extends StrategyFieldValues {
  id: number;
  version: number;
  created_by: string | null;
  created_at: string | null;
  updated_by: string | null;
  updated_at: string | null;
  links?: StrategyLinks;
}

export interface StrategySuggestion {
  text: string;
  source: string;
}

export interface StrategyNextAction {
  task_id: number;
  title: string;
  status: string;
  due: string | null;
  assignee: string | null;
}

export interface StrategySuggestions extends Record<StrategyField, StrategySuggestion[]> {
  calculation_version: string;
  as_of: string;
  reference_date: string;
  next_actions: StrategyNextAction[];
}

export interface StrategySnapshotSummary {
  id: number;
  plan_number: number;
  note: string | null;
  published_by: string | null;
  published_at: string | null;
}

/** GET /api/strategy-snapshots/{id}/ — content is the verbatim published plan. */
export interface StrategySnapshot extends StrategySnapshotSummary {
  content: StrategyFieldValues & { version: number };
}

export interface StrategySnapshotsInfo {
  count: number;
  latest: Pick<StrategySnapshotSummary, 'plan_number' | 'note' | 'published_by' | 'published_at'> | null;
}

/** GET /api/customers/{id}/strategy/ */
export interface StrategyView {
  plan: StrategyPlan | null;
  suggestions: StrategySuggestions;
  snapshots: StrategySnapshotsInfo;
}

/** PUT /api/customers/{id}/strategy/ — omitted = unchanged, null = clear. */
export interface StrategyUpdate extends Partial<StrategyFieldValues> {
  expected_version: number;
}

/** PUT /api/customers/{id}/strategy/links/ — all three required (full set). */
export interface StrategyLinksUpdate {
  task_ids: number[];
  contact_ids: number[];
  note_ids: number[];
}

export interface StrategySnapshotPublish {
  note?: string;
}

export interface StrategySnapshotList {
  snapshots: StrategySnapshotSummary[];
}
