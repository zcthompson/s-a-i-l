/**
 * prefillStrategy pure pins. Synthetic fixtures only.
 */
import { describe, it, expect } from 'vitest';
import { prefillStrategy } from '../src/lib/strategy';
import type { StrategyField } from '../src/types/strategy';

const NONE = { objectives: null, desired_outcomes: null, risks: null, plays: null, discovery_gaps: null } as Record<StrategyField, null>;
const sug = (text: string, source = 'pipeline') => ({ text, source });

describe('prefillStrategy', () => {
  it('fills every empty field with the FIRST suggestion text and lists exactly those fields', () => {
    const r = prefillStrategy(NONE, {
      objectives: [sug('first objective'), sug('second objective')],
      desired_outcomes: [],
      risks: [sug('first risk')],
      plays: [],
      discovery_gaps: [sug('gap')],
    });
    expect(r.fields).toEqual({
      objectives: 'first objective', desired_outcomes: '', risks: 'first risk', plays: '', discovery_gaps: 'gap',
    });
    expect(r.prefilled).toEqual(['objectives', 'risks', 'discovery_gaps']);
  });

  it('never touches a non-empty recorded value, even when a suggestion exists', () => {
    const r = prefillStrategy(
      { ...NONE, objectives: 'user-authored objective', risks: '  kept  ' },
      { objectives: [sug('suggested')], desired_outcomes: [], risks: [sug('suggested risk')], plays: [], discovery_gaps: [] },
    );
    expect(r.fields.objectives).toBe('user-authored objective');
    expect(r.fields.risks).toBe('  kept  ');
    expect(r.prefilled).toEqual([]);
  });

  it('treats undefined, null, and whitespace-only recorded values as empty', () => {
    const r = prefillStrategy(
      { objectives: undefined, desired_outcomes: '   ', risks: null, plays: '', discovery_gaps: null },
      { objectives: [sug('o')], desired_outcomes: [sug('d')], risks: [sug('r')], plays: [sug('p')], discovery_gaps: [sug('g')] },
    );
    expect(r.fields).toEqual({ objectives: 'o', desired_outcomes: 'd', risks: 'r', plays: 'p', discovery_gaps: 'g' });
    expect(r.prefilled).toEqual(['objectives', 'desired_outcomes', 'risks', 'plays', 'discovery_gaps']);
  });

  it('leaves a field with no suggestion empty and out of the prefilled list', () => {
    const r = prefillStrategy(NONE, {
      objectives: [], desired_outcomes: [], risks: [], plays: [], discovery_gaps: [],
    });
    expect(r.fields).toEqual({ objectives: '', desired_outcomes: '', risks: '', plays: '', discovery_gaps: '' });
    expect(r.prefilled).toEqual([]);
  });

  it('keeps a recorded value verbatim when there is no suggestion for it', () => {
    const r = prefillStrategy(
      { ...NONE, plays: 'recorded play' },
      { objectives: [], desired_outcomes: [], risks: [], plays: [sug('ignored')], discovery_gaps: [] },
    );
    expect(r.fields.plays).toBe('recorded play');
    expect(r.prefilled).toEqual([]);
  });

  it('tolerates an absent suggestion key (treated as no suggestion)', () => {
    const r = prefillStrategy(NONE, { objectives: [sug('only objective')] } as Record<StrategyField, { text: string; source: string }[]>);
    expect(r.fields.objectives).toBe('only objective');
    expect(r.fields.risks).toBe('');
    expect(r.prefilled).toEqual(['objectives']);
  });

  it('does not treat an empty first suggestion text as a fill', () => {
    const r = prefillStrategy(NONE, {
      objectives: [sug('')], desired_outcomes: [], risks: [], plays: [], discovery_gaps: [],
    });
    expect(r.fields.objectives).toBe('');
    expect(r.prefilled).toEqual([]);
  });

  it('prefilled is exactly the filled fields, in STRATEGY_FIELDS order', () => {
    const r = prefillStrategy(
      { objectives: 'kept', desired_outcomes: null, risks: null, plays: 'kept', discovery_gaps: null },
      { objectives: [sug('x')], desired_outcomes: [sug('d')], risks: [], plays: [sug('x')], discovery_gaps: [sug('g')] },
    );
    expect(r.prefilled).toEqual(['desired_outcomes', 'discovery_gaps']);
  });
});
