// H7 — pure prefill helper (contract C4). Fills ONLY empty fields of the
// draft, with the FIRST suggestion text for that field. A recorded non-empty
// value is never touched; a field with no suggestion stays empty.
import { STRATEGY_FIELDS, type StrategyField, type StrategySuggestion } from '../types/strategy';

export interface StrategyPrefill {
  /** The draft after prefill: every field present, '' when nothing applies. */
  fields: Record<StrategyField, string>;
  /** Exactly the fields that received a suggestion, in STRATEGY_FIELDS order. */
  prefilled: StrategyField[];
}

const isEmpty = (v: string | null | undefined): boolean => v == null || v.trim() === '';

export function prefillStrategy(
  recorded: Record<StrategyField, string | null | undefined>,
  suggestions: Record<StrategyField, StrategySuggestion[] | undefined>,
): StrategyPrefill {
  const fields = {} as Record<StrategyField, string>;
  const prefilled: StrategyField[] = [];
  for (const field of STRATEGY_FIELDS) {
    const current = recorded[field];
    const first = suggestions[field]?.[0]?.text;
    if (!isEmpty(current)) {
      fields[field] = current as string;
    } else if (first) {
      fields[field] = first;
      prefilled.push(field);
    } else {
      fields[field] = current ?? '';
    }
  }
  return { fields, prefilled };
}
