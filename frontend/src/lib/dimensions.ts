// Canonical scoring dimensions — frontend mirror of
// backend/services/scoring.py `ScoringService.DIMENSIONS` and its
// normalized-name lookup (`_DIMENSION_BY_NORM`).
//
// Used by the Readiness Insights block (AnalyticsDashboard) to build a
// client-side dimension-readiness profile without a dedicated backend
// endpoint. Kept dependency-free and framework-agnostic.

export interface CanonicalDimension {
  name: string;
  weight: number;
}

/** The 6 canonical dimensions, in display order, with their weights.
 *  Mirrors `ScoringService.DIMENSIONS`. */
export const CANONICAL_DIMENSIONS: CanonicalDimension[] = [
  { name: 'Data Readiness', weight: 0.2 },
  { name: 'Technical Feasibility', weight: 0.2 },
  { name: 'Organizational Readiness', weight: 0.15 },
  { name: 'ROI Potential', weight: 0.2 },
  { name: 'Risk & Compliance', weight: 0.15 },
  { name: 'Implementation Complexity', weight: 0.1 },
];

/** Normalize a dimension name/key to lowercase alphanumerics only, so that
 *  "Risk & Compliance", "risk_compliance" and "risk and compliance" all
 *  collapse to "riskcompliance". Mirrors the backend `_DIMENSION_BY_NORM`
 *  key construction. */
export function normalizeDimensionKey(name: string): string {
  return String(name)
    .toLowerCase()
    .replace(/[^a-z0-9]/g, '');
}

const CANONICAL_BY_NORM = new Map<string, CanonicalDimension>(
  CANONICAL_DIMENSIONS.map((d) => [normalizeDimensionKey(d.name), d]),
);

// Meta keys that appear alongside dimension scores in a flat `scores` dict.
const NON_DIMENSION_KEYS = new Set([
  'overall_score',
  'scored_at',
  'scored_by',
  'reasoning',
  'confidence',
  'summary',
]);

/**
 * Read the per-dimension numeric scores out of a single use case's `scores`
 * JSON. Handles both payload shapes in circulation (same two the backend
 * `extract_dimension_scores` tolerates):
 *   - `{ dimension_scores: [{ name|dimension|key, score }, ...] }`
 *     (live AI scoring / approved score history);
 *   - `{ data_readiness: 80, technical_feasibility: 78, ... }`
 *     (seeded / legacy flat dicts).
 * Returns `{ rawKey: score }` with non-numeric values dropped.
 */
function readUseCaseDimensionScores(useCase: any): Record<string, number> {
  const out: Record<string, number> = {};
  const scores = useCase?.scores;
  if (!scores || typeof scores !== 'object') return out;

  const dimList = (scores as any).dimension_scores;
  if (Array.isArray(dimList)) {
    for (const dim of dimList) {
      if (!dim || typeof dim !== 'object') continue;
      const raw = dim.name ?? dim.dimension ?? dim.key ?? '';
      const value = dim.score;
      if (typeof value === 'number' && Number.isFinite(value) && String(raw)) {
        out[String(raw)] = value;
      }
    }
    return out;
  }

  for (const [key, value] of Object.entries(scores)) {
    if (NON_DIMENSION_KEYS.has(key)) continue;
    if (typeof value === 'number' && Number.isFinite(value)) {
      out[key] = value;
    }
  }
  return out;
}

export interface DimensionAverage {
  name: string;
  weight: number;
  average: number | null;
  count: number;
}

/**
 * Average each canonical dimension's score across the in-scope use cases
 * that are scored (`overall_score != null`) and report that dimension.
 * Dimension keys are matched to canonical names via `normalizeDimensionKey`
 * (with an "and"-stripping fallback, mirroring the backend). Any dimension
 * key found in the data that does not map to a canonical one is kept under
 * its raw name with weight 0 and appended after the canonical six.
 */
export function getDimensionAverages(useCases: any[]): DimensionAverage[] {
  const scoped = (useCases || []).filter((uc) => uc && uc.overall_score != null);

  interface Acc {
    name: string;
    weight: number;
    sum: number;
    count: number;
  }
  const acc = new Map<string, Acc>();
  for (const d of CANONICAL_DIMENSIONS) {
    acc.set(normalizeDimensionKey(d.name), { name: d.name, weight: d.weight, sum: 0, count: 0 });
  }

  for (const uc of scoped) {
    const dims = readUseCaseDimensionScores(uc);
    for (const [rawKey, value] of Object.entries(dims)) {
      const norm = normalizeDimensionKey(rawKey);
      const canonical =
        CANONICAL_BY_NORM.get(norm) || CANONICAL_BY_NORM.get(norm.replace('and', ''));
      const bucketKey = canonical ? normalizeDimensionKey(canonical.name) : norm;
      if (!acc.has(bucketKey)) {
        acc.set(bucketKey, { name: rawKey, weight: 0, sum: 0, count: 0 });
      }
      const entry = acc.get(bucketKey)!;
      entry.sum += value;
      entry.count += 1;
    }
  }

  const result: DimensionAverage[] = [];
  for (const d of CANONICAL_DIMENSIONS) {
    const entry = acc.get(normalizeDimensionKey(d.name))!;
    result.push({
      name: d.name,
      weight: d.weight,
      average: entry.count > 0 ? entry.sum / entry.count : null,
      count: entry.count,
    });
  }
  for (const [norm, entry] of acc) {
    if (CANONICAL_BY_NORM.has(norm)) continue;
    result.push({
      name: entry.name,
      weight: 0,
      average: entry.count > 0 ? entry.sum / entry.count : null,
      count: entry.count,
    });
  }
  return result;
}
