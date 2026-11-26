// Shared display formatters for the partner pipeline surfaces
// (CustomerPipeline panel + Intelligence Import page).

const USD = new Intl.NumberFormat('en-US', {
  style: 'currency', currency: 'USD', maximumFractionDigits: 0,
});

/** $1,234 — em dash for null/undefined. */
export function formatUsd(value: number | null | undefined): string {
  return value == null ? '—' : USD.format(value);
}

/** Date-only ISO (YYYY-MM-DD) → "Oct 30, 2026" (no timezone shift);
 *  full timestamps render in the local date. Em dash when empty/invalid. */
export function formatDate(value: string | null | undefined): string {
  if (!value) return '—';
  const dateOnly = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value);
  const d = dateOnly
    ? new Date(Date.UTC(+dateOnly[1], +dateOnly[2] - 1, +dateOnly[3]))
    : new Date(value);
  if (Number.isNaN(d.getTime())) return value;
  return d.toLocaleDateString('en-US', {
    year: 'numeric', month: 'short', day: 'numeric',
    timeZone: dateOnly ? 'UTC' : undefined,
  });
}

/** Honest amount label by coverage state: a number only when recorded, never a
 *  fabricated $0 for unknown. `lines` (caller-supplied lines_included /
 *  lines_excluded) adds the "n of m lines" suffix for partial totals. */
export function formatAmountWithCoverage(
  value: number | null | undefined,
  coverage: string | null | undefined,
  lines?: { included: number; excluded: number },
): string {
  if (coverage === 'recorded_zero') return '$0.00 recorded';
  if (value == null) return 'Not recorded';
  const amount = formatUsd(value);
  if (coverage === 'partial') {
    return lines
      ? `${amount} (partial — ${lines.included} of ${lines.included + lines.excluded} lines)`
      : `${amount} (partial)`;
  }
  return amount;
}

/** H3 renewal evidence: "overdue by N days" / "due today" / "in N days".
 *  Null days (no recorded end date) is "date not recorded" — never a guess. */
export function formatDaysUntil(days: number | null | undefined): string {
  if (days == null) return 'date not recorded';
  if (days === 0) return 'due today';
  const n = Math.abs(days);
  const unit = n === 1 ? 'day' : 'days';
  return days < 0 ? `overdue by ${n} ${unit}` : `in ${n} ${unit}`;
}

/** Renewal bucket labels (H3 contract S7). */
export const RENEWAL_BUCKET_LABELS = {
  overdue: 'Overdue',
  within_30: '30 days',
  within_60: '60 days',
  within_90: '90 days',
  within_180: '180 days',
  unknown_date: 'Unknown date',
} as const;

/** Renewal exposure label by coverage — reuses the honest amount formatter. */
export function formatRenewalExposure(
  group: { total: number | null; coverage: string; lines_included: number; lines_excluded: number } | null | undefined,
): string {
  if (!group) return 'Not recorded';
  return formatAmountWithCoverage(group.total, group.coverage, {
    included: group.lines_included, excluded: group.lines_excluded,
  });
}
