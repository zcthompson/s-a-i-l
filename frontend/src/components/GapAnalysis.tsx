import { useState } from 'react';

type GapEntry = {
  category: string;
  severity: 'high' | 'medium' | 'low';
  description: string;
  readiness_dimension?: string;
  environment_factor?: string;
};

interface GapAnalysisProps {
  readiness_dimensions: Record<string, number> | undefined;
  environment_factors: {
    software_completeness?: number;
    hardware_currency?: number;
    process_documentation?: number;
    vendor_diversity?: number;
  } | undefined;
  gaps?: GapEntry[] | undefined;
}

const READINESS_DIMENSIONS = [
  'strategic_fit',
  'technical_feasibility',
  'financial_viability',
  'operational_readiness',
  'risk_tolerance',
  'resource_availability',
] as const;

const ENVIRONMENT_FACTORS = [
  'software_completeness',
  'hardware_currency',
  'process_documentation',
  'vendor_diversity',
] as const;

// Score-band threshold: green 70+
const GREEN_THRESHOLD = 70;

// Color rule (documented):
// Green when environment factor score >= 70 OR env factor >= dimension score
// Amber when env factor is within 15 points below the dimension score
// Red otherwise
function cellClass(envScore: number | undefined, dimScore: number | undefined): string {
  if (envScore === undefined || dimScore === undefined) return 'var(--neutral-400)';
  if (envScore >= GREEN_THRESHOLD || envScore >= dimScore) return 'var(--status-positive)';
  if (dimScore - envScore <= 15 && dimScore >= envScore) return 'var(--status-warning)';
  return 'var(--status-negative)';
}

export function GapAnalysis({ readiness_dimensions, environment_factors, gaps }: GapAnalysisProps) {
  const [selectedCell, setSelectedCell] = useState<{
    dim: (typeof READINESS_DIMENSIONS)[number];
    factor: (typeof ENVIRONMENT_FACTORS)[number];
  } | null>(null);

  if (!readiness_dimensions || Object.keys(readiness_dimensions).length === 0) {
    return (
      <div style={{ padding: '40px', textAlign: 'center', color: 'var(--neutral-500)' }}>
        No readiness dimensions data available
      </div>
    );
  }

  if (!environment_factors) {
    return (
      <div style={{ padding: '40px', textAlign: 'center', color: 'var(--neutral-500)' }}>
        No environment factors data available
      </div>
    );
  }

  // Matrix data for JSON export — built from live props (not module state).
  const matrixData: Record<string, Record<string, number | undefined>> = {};
  READINESS_DIMENSIONS.forEach((dim) => {
    matrixData[dim] = {};
    ENVIRONMENT_FACTORS.forEach((factor) => {
      matrixData[dim][factor] = environment_factors[factor];
    });
  });

  const copyMatrixJSON = () => {
    navigator.clipboard.writeText(JSON.stringify(matrixData, null, 2));
  };

  const downloadMatrixJSON = () => {
    const blob = new Blob([JSON.stringify(matrixData, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = 'readiness-matrix.json';
    a.click();
    URL.revokeObjectURL(url);
  };

  // Drill-down state for the selected cell (click a matrix cell).
  const selectedDimScore = selectedCell ? readiness_dimensions[selectedCell.dim] : undefined;
  const selectedEnvScore = selectedCell ? environment_factors[selectedCell.factor] : undefined;
  const selectedGaps = selectedCell
    ? (gaps || []).filter(
        (g) =>
          (!g.readiness_dimension || g.readiness_dimension === selectedCell.dim) &&
          (!g.environment_factor || g.environment_factor === selectedCell.factor),
      )
    : [];

  return (
    <div style={{ padding: '20px' }}>
      <h3 style={{ margin: '0 0 16px', color: 'var(--ink)' }}>Readiness Matrix</h3>

      <div style={{ borderCollapse: 'separate', borderSpacing: '0 8px', marginBottom: '20px' }}>
        {/* Column headers: environment factors */}
        <div style={{ display: 'flex', gap: '12px', background: 'var(--neutral-100)', borderRadius: 'var(--radius)', padding: '8px' }}>
          <div style={{ width: '140px' }}>Dimension</div>
          {ENVIRONMENT_FACTORS.map((factor) => (
            <div
              key={factor}
              style={{
                flex: '1', textAlign: 'center', padding: '4px 8px',
                background: 'var(--neutral-200)', borderRadius: 'var(--radius-sm)'
              }}
            >
              {factor}
            </div>
          ))}
        </div>

        {/* Matrix rows: each readiness dimension */}
        {READINESS_DIMENSIONS.map((dim) => {
          const dimScore = readiness_dimensions[dim];
          if (dimScore === undefined) return null;

          return (
            <div key={dim} style={{ borderTop: '1px solid var(--divider)' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '4px', color: 'var(--neutral-500)', fontSize: '0.85rem' }}>
                <span>{dim}</span>
                <span style={{ fontWeight: 'bold', color: 'var(--ink)' }}>{dimScore.toFixed(1)}/100</span>
              </div>
              <div style={{ display: 'flex', gap: '12px' }}>
                {ENVIRONMENT_FACTORS.map((factor) => {
                  const envScore = environment_factors[factor];
                  if (envScore === undefined) return null;
                  const matchingGaps = (gaps || []).filter(
                    (g) =>
                      g.readiness_dimension === dim && g.environment_factor === factor,
                  );
                  return (
                    <div
                      key={factor}
                      role="button"
                      aria-label={`Gap detail for ${dim} vs ${factor}`}
                      onClick={() => setSelectedCell({ dim, factor })}
                      style={{
                        flex: '1', textAlign: 'center', padding: '8px 4px',
                        borderRadius: 'var(--radius-sm)',
                        background: cellClass(envScore, dimScore),
                        color: 'white',
                        minHeight: '32px',
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'center',
                        cursor: 'pointer',
                      }}
                    >
                      {envScore.toFixed(1)}/100
                      {matchingGaps.length > 0 && (
                        <span style={{ marginLeft: '8px', fontSize: '0.7rem', color: 'rgba(255,255,255,0.8)' }}>
                          ⚠ {matchingGaps.length} gap(s)
                        </span>
                      )}
                    </div>
                  );
                })}
              </div>
            </div>
          );
        })}
      </div>

      {/* Cell detail (drill-down): click a matrix cell to inspect it */}
      {selectedCell && (
        <div style={{ marginTop: '16px', padding: '12px 16px', background: 'var(--neutral-100)', borderRadius: 'var(--radius)' }}>
          <div style={{ fontWeight: 600, color: 'var(--ink)', marginBottom: '6px' }}>
            {selectedCell.dim} × {selectedCell.factor}
          </div>
          <div style={{ fontSize: '0.85rem', color: 'var(--neutral-700)', marginBottom: '6px' }}>
            Dimension score: {selectedDimScore !== undefined ? `${selectedDimScore.toFixed(1)}/100` : 'N/A'} ·
            Environment factor score: {selectedEnvScore !== undefined ? `${selectedEnvScore.toFixed(1)}/100` : 'N/A'}
          </div>
          {selectedGaps.length > 0 ? (
            <ul style={{ margin: 0, paddingLeft: '20px', color: 'var(--neutral-700)', fontSize: '0.85rem' }}>
              {selectedGaps.map((g, i) => (
                <li key={i}>
                  <strong>{g.category} — {g.severity}</strong>: {g.description}
                </li>
              ))}
            </ul>
          ) : (
            <div style={{ fontSize: '0.85rem', color: 'var(--neutral-500)' }}>
              No specific gaps recorded for this cell.
            </div>
          )}
        </div>
      )}

      {/* Export the matrix as JSON */}
      <div style={{ marginTop: '20px', padding: '12px', background: 'var(--neutral-100)', borderRadius: 'var(--radius)' }}>
        <button
          onClick={copyMatrixJSON}
          style={{
            padding: '6px 12px', background: 'var(--brand-500)', color: 'var(--neutral-0)', border: 'none', borderRadius: 'var(--radius-sm)', cursor: 'pointer', fontSize: '0.85rem'
          }}
        >
          Copy JSON
        </button>
        <button
          onClick={downloadMatrixJSON}
          style={{
            padding: '6px 12px', background: 'var(--ink)', color: 'var(--neutral-0)', border: 'none', borderRadius: 'var(--radius-sm)', cursor: 'pointer', fontSize: '0.85rem', marginLeft: '8px'
          }}
        >
          Download
        </button>
      </div>
    </div>
  );
}
