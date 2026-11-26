// H5 — activities, tasks, and engagement. Field-for-field with the
// normative response shapes (contract C3.1). Unknown values are null.

export const ACTIVITY_TYPES = ['call', 'meeting', 'email', 'demo', 'qbr'] as const;
export type ActivityType = (typeof ACTIVITY_TYPES)[number];

export const ACTIVITY_TYPE_LABELS: Record<ActivityType, string> = {
  call: 'Call',
  meeting: 'Meeting',
  email: 'Email',
  demo: 'Demo',
  qbr: 'QBR',
};

export const TASK_STATUSES = ['open', 'in_progress', 'completed', 'cancelled'] as const;
export type TaskStatus = (typeof TASK_STATUSES)[number];

export const TASK_SOURCE_TYPES = ['note', 'renewal_attention', 'contact_coverage', 'eol_attention'] as const;
export type TaskSourceType = (typeof TASK_SOURCE_TYPES)[number];

export const NEW_NOTIFICATION_TYPES = [
  'task_assigned',
  'task_reassigned',
  'task_completed',
  'task_due_soon',
  'task_overdue',
] as const;

export interface ActivityAttendee {
  contact_id: number;
  display_name: string;
}

export interface Activity {
  id: number;
  customer_id: number;
  type: string;
  occurred_at: string | null;
  occurred_date: string | null;
  actor: string;
  source: string | null;
  outcome: string | null;
  created_by: string;
  created_at: string;
  updated_at: string;
  attendees: ActivityAttendee[];
}

/** Exactly one of occurred_at / occurred_date must be set (backend 422 otherwise). */
export interface ActivityCreate {
  type: string;
  occurred_at?: string | null;
  occurred_date?: string | null;
  actor: string;
  source?: string | null;
  outcome?: string | null;
  contact_ids?: number[];
}

export type ActivityUpdate = Partial<ActivityCreate>;

export interface Task {
  id: number;
  customer_id: number;
  title: string;
  detail: string | null;
  assignee: string | null;
  due_at: string | null;
  due_date: string | null;
  status: string;
  completed_by: string | null;
  completed_at: string | null;
  source_type: string | null;
  source_id: number | null;
  source_key: string | null;
  created_by: string;
  created_at: string;
  updated_at: string;
  version: number;
  evidence_note_count: number;
  evidence_activity_count: number;
  overdue: boolean;
  due_soon: boolean;
  needs_reassignment: boolean;
}

export interface MyTask extends Task {
  customer_name: string;
}

export interface TaskCreate {
  title: string;
  detail?: string | null;
  assignee?: string | null;
  due_at?: string | null;
  due_date?: string | null;
}

/** expected_version is required on every update (409 on mismatch). */
export interface TaskUpdate extends Partial<TaskCreate> {
  expected_version: number;
  status?: string;
}

export interface TaskPromote {
  source_type: TaskSourceType;
  source_id: number;
  title?: string;
  detail?: string;
}

export interface TaskPromotionResponse {
  created: boolean;
  task: Task;
}
