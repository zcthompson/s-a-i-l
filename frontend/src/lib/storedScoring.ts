import type { DimensionScore, ScoredUseCaseResponse, UseCase } from '../types/use_case';

/** Restore only a complete saved breakdown; never fabricate scores or dates. */
export function storedScoring(useCase: UseCase): ScoredUseCaseResponse | null {
  const saved = useCase.scores;
  if (!saved || !Array.isArray(saved.dimension_scores) || saved.dimension_scores.length === 0) return null;
  const overall = useCase.overall_score ?? saved.overall_score;
  const validScore = (value: unknown): value is number => typeof value === 'number' && Number.isFinite(value) && value >= 0 && value <= 100;
  if (!validScore(overall)) return null;
  const dimensions: DimensionScore[] = [];
  for (const dimension of saved.dimension_scores) {
    if (!dimension || typeof dimension !== 'object' || typeof dimension.name !== 'string' || !dimension.name.trim() || !validScore(dimension.score) || typeof dimension.weight !== 'number' || !Number.isFinite(dimension.weight) || dimension.weight < 0 || dimension.weight > 1) return null;
    dimensions.push({ name: dimension.name, score: dimension.score, weight: dimension.weight, description: typeof dimension.description === 'string' ? dimension.description : '' });
  }
  return {
    use_case: useCase,
    scores: {
      dimension_scores: dimensions,
      overall_score: overall,
      reasoning: typeof saved.reasoning === 'string' ? saved.reasoning : '',
      scored_at: useCase.scored_at || (typeof saved.scored_at === 'string' ? saved.scored_at : ''),
      recommendations: Array.isArray(saved.recommendations) ? saved.recommendations.filter((item): item is string => typeof item === 'string') : [],
    },
  };
}
