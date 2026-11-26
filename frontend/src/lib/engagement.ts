/**
 * H5 — pure date-boundary helpers mirroring the backend evaluator rules
 * (evaluator section). All comparisons are UTC.
 *
 *   date-only due: today = due_soon (NEVER overdue); before today = overdue;
 *                  tomorrow or later = neither.
 *   instant due:   < now = overdue; in (now, now+24h] = due_soon.
 *   undated:       neither (honest — no due is not overdue).
 *   Only open / in_progress tasks can be flagged.
 */

const DAY_MS = 24 * 60 * 60 * 1000;

export interface DueFields {
  due_at: string | null;
  due_date: string | null;
  status?: string;
}

export function isActiveStatus(status: string | undefined): boolean {
  return status === undefined || status === 'open' || status === 'in_progress';
}

function utcDay(d: Date): string {
  return d.toISOString().slice(0, 10);
}

/** Parse a backend ISO instant; naive strings are UTC. */
export function parseInstant(iso: string): Date {
  return new Date(/(Z|[+-]\d\d:?\d\d)$/.test(iso) ? iso : `${iso}Z`);
}

/** The normalized due date (UTC day) or null when undated. */
export function dueDay(t: DueFields): string | null {
  if (t.due_date) return t.due_date;
  if (t.due_at) return utcDay(parseInstant(t.due_at));
  return null;
}

export function isOverdue(t: DueFields, now: Date = new Date()): boolean {
  if (!isActiveStatus(t.status)) return false;
  if (t.due_date) return t.due_date < utcDay(now);
  if (t.due_at) return parseInstant(t.due_at).getTime() < now.getTime();
  return false;
}

export function isDueSoon(t: DueFields, now: Date = new Date()): boolean {
  if (!isActiveStatus(t.status)) return false;
  if (t.due_date) return t.due_date === utcDay(now);
  if (t.due_at) {
    const ms = parseInstant(t.due_at).getTime();
    return ms > now.getTime() && ms <= now.getTime() + DAY_MS;
  }
  return false;
}

/** "YYYY-MM-DD" for date-only, "YYYY-MM-DD HH:MM UTC" for an instant, "—" when undated. */
export function renderDue(t: DueFields): string {
  if (t.due_date) return t.due_date;
  if (t.due_at) {
    const d = parseInstant(t.due_at).toISOString();
    return `${d.slice(0, 10)} ${d.slice(11, 16)} UTC`;
  }
  return '—';
}

/** Same rendering rule for an activity's occurred_at / occurred_date. */
export function renderOccurred(a: { occurred_at: string | null; occurred_date: string | null }): string {
  if (a.occurred_date) return a.occurred_date;
  if (a.occurred_at) {
    const d = parseInstant(a.occurred_at).toISOString();
    return `${d.slice(0, 10)} ${d.slice(11, 16)} UTC`;
  }
  return '—';
}

/** Convert a datetime-local input value ("YYYY-MM-DDTHH:MM", read as UTC) to an ISO instant. */
export function localInputToUtcIso(v: string): string {
  return v.length === 16 ? `${v}:00Z` : `${v}Z`;
}
