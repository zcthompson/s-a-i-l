import { expect, it } from 'vitest';
import { storedScoring } from '../src/lib/storedScoring';
import type { UseCase } from '../src/types/use_case';
const record = { id: 12, title: 'Saved case', overall_score: 0, scores: { dimension_scores: [{ name: 'Strategy', score: 0, weight: 1 }], reasoning: 'Recorded reasoning', recommendations: ['Recorded next step'] } } as unknown as UseCase;
it('preserves valid zero scores and never invents a scoring date', () => {
  expect(storedScoring(record)?.scores).toMatchObject({ overall_score: 0, scored_at: '', reasoning: 'Recorded reasoning', dimension_scores: [{ score: 0 }] });
});
it.each([null, {}, { dimension_scores: [] }, { dimension_scores: [{ name: 'Strategy', score: '50', weight: 1 }] }, { dimension_scores: [{ name: 'Strategy', score: 101, weight: 1 }] }, { dimension_scores: [{ name: 'Strategy', score: 50, weight: -1 }] }])('withholds an absent or malformed saved breakdown: %j', scores => {
  expect(storedScoring({ ...record, scores } as UseCase)).toBeNull();
});
