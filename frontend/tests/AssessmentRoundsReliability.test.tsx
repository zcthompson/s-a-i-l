import { act, cleanup, renderHook, waitFor } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { useAssessmentRounds } from '../src/lib/useAssessmentRounds';
const { listAssessments } = vi.hoisted(() => ({ listAssessments: vi.fn() }));
vi.mock('../src/lib/api', () => ({ api: { listAssessments } }));
afterEach(() => { cleanup(); vi.resetAllMocks(); });
it('ignores late successes and failures after switching customers', async () => {
  let resolveA!: (rows: any[]) => void;
  let rejectB!: (error: Error) => void;
  listAssessments.mockImplementationOnce(() => new Promise(resolve => { resolveA = resolve; }))
    .mockImplementationOnce(() => new Promise((_resolve, reject) => { rejectB = reject; }))
    .mockResolvedValueOnce([{ id: 3, name: 'C round' }]);
  const { result, rerender } = renderHook(({ name }) => useAssessmentRounds(name), { initialProps: { name: 'A' } });
  rerender({ name: 'B' });
  rerender({ name: 'C' });
  await waitFor(() => expect(result.current.assessments[0]?.id).toBe(3));
  await act(async () => { resolveA([{ id: 1 }]); rejectB(new Error('late')); });
  expect(result.current.assessments[0].id).toBe(3);
  expect(result.current.roundsLoadError).toBe(false);
  expect(result.current.roundsLoading).toBe(false);
});
it('distinguishes failure from empty results and retries the same account', async () => {
  listAssessments.mockRejectedValueOnce(new Error('offline')).mockResolvedValueOnce([]);
  const { result } = renderHook(() => useAssessmentRounds('A'));
  await waitFor(() => expect(result.current.roundsLoadError).toBe(true));
  await act(async () => { await result.current.loadAssessments(); });
  expect(result.current.roundsLoadError).toBe(false);
  expect(result.current.assessments).toEqual([]);
  expect(listAssessments.mock.calls).toEqual([['A'], ['A']]);
});
