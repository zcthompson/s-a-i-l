import { describe, it, expect } from 'vitest';
import { isDueSoon, isOverdue, renderDue, renderOccurred, dueDay, localInputToUtcIso } from '../src/lib/engagement';

const NOW = new Date('2026-10-28T12:00:00Z');

describe('engagement date boundaries (UTC)', () => {
  it('date-only due today is due_soon, NEVER overdue', () => {
    const t = { due_at: null, due_date: '2026-10-28', status: 'open' };
    expect(isDueSoon(t, NOW)).toBe(true);
    expect(isOverdue(t, NOW)).toBe(false);
  });
  it('date-only yesterday is overdue; tomorrow is neither', () => {
    expect(isOverdue({ due_at: null, due_date: '2026-10-27', status: 'open' }, NOW)).toBe(true);
    const tomorrow = { due_at: null, due_date: '2026-10-29', status: 'open' };
    expect(isOverdue(tomorrow, NOW)).toBe(false);
    expect(isDueSoon(tomorrow, NOW)).toBe(false);
  });
  it('instant: past is overdue, (now, now+24h] is due_soon, beyond is neither', () => {
    expect(isOverdue({ due_at: '2026-10-28T11:59:59Z', due_date: null }, NOW)).toBe(true);
    expect(isOverdue({ due_at: '2026-10-28T12:00:00Z', due_date: null }, NOW)).toBe(false);
    expect(isDueSoon({ due_at: '2026-10-29T12:00:00Z', due_date: null }, NOW)).toBe(true);
    expect(isDueSoon({ due_at: '2026-10-29T12:00:01Z', due_date: null }, NOW)).toBe(false);
    expect(isDueSoon({ due_at: '2026-10-28T12:00:00Z', due_date: null }, NOW)).toBe(false);
  });
  it('naive ISO strings are read as UTC', () => {
    expect(isOverdue({ due_at: '2026-10-28T11:00:00', due_date: null }, NOW)).toBe(true);
  });
  it('undated is neither; completed/cancelled are never flagged', () => {
    const none = { due_at: null, due_date: null, status: 'open' };
    expect(isOverdue(none, NOW)).toBe(false);
    expect(isDueSoon(none, NOW)).toBe(false);
    expect(isOverdue({ due_at: null, due_date: '2026-01-01', status: 'completed' }, NOW)).toBe(false);
    expect(isOverdue({ due_at: null, due_date: '2026-01-01', status: 'cancelled' }, NOW)).toBe(false);
  });
  it('rendering: date-only, instant, undated', () => {
    expect(renderDue({ due_at: null, due_date: '2026-11-02' })).toBe('2026-11-02');
    expect(renderDue({ due_at: '2026-11-02T09:05:00Z', due_date: null })).toBe('2026-11-02 09:05 UTC');
    expect(renderDue({ due_at: null, due_date: null })).toBe('—');
    expect(renderOccurred({ occurred_at: null, occurred_date: '2026-10-01' })).toBe('2026-10-01');
    expect(renderOccurred({ occurred_at: '2026-10-01T14:30:00', occurred_date: null })).toBe('2026-10-01 14:30 UTC');
  });
  it('dueDay normalizes an instant to its UTC day', () => {
    expect(dueDay({ due_at: '2026-11-02T23:59:00Z', due_date: null })).toBe('2026-11-02');
    expect(dueDay({ due_at: null, due_date: null })).toBeNull();
  });
  it('datetime-local value converts to a UTC instant', () => {
    expect(localInputToUtcIso('2026-10-01T10:30')).toBe('2026-10-01T10:30:00Z');
  });
});
