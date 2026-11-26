import { ActionButton } from './ActionButton';
import { SectionIcon } from './SectionIcon';
import { useState } from 'react';
import { ScoredUseCaseResponse } from '../types/use_case';
import { RadarChartComponent } from './RadarChart';
import { api } from '../lib/api';
import { useScopedView } from '../lib/useScopedView';
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  PieChart,
  Pie,
  Cell,
  Legend,
} from 'recharts';

interface ScoringDashboardProps {
  scoredData: ScoredUseCaseResponse;
  onBack: () => void;
}

const SCORE_VIEW_KEYS = ['tab'] as const;

export function ScoringDashboard({ scoredData, onBack }: ScoringDashboardProps) {
  const { use_case, scores } = scoredData;
  const [scoreView, updateScoreView] = useScopedView(use_case.id, 'score', SCORE_VIEW_KEYS);
  const activeTab = scoreView.tab === 'bars' || scoreView.tab === 'detail' ? scoreView.tab : 'radar';
  const [exporting, setExporting] = useState<'pdf' | 'excel' | null>(null);
  const [exportError, setExportError] = useState<string | null>(null);

  const exportResults = async (format: 'pdf' | 'excel') => {
    if (exporting) return;
    setExporting(format);
    setExportError(null);
    try {
      const blob = await (format === 'pdf' ? api.exportPdf : api.exportExcel)(undefined, [use_case.id]);
      const url = window.URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = `sail_${format === 'pdf' ? 'report' : 'export'}_${new Date().toISOString().split('T')[0]}.${format === 'pdf' ? 'pdf' : 'xlsx'}`;
      link.click();
      window.URL.revokeObjectURL(url);
    } catch { setExportError(`${format === 'pdf' ? 'PDF' : 'Excel'} export failed`); }
    finally { setExporting(null); }
  };

  const chartData = scores.dimension_scores.map((dim) => ({
    name: dim.name,
    score: dim.score,
    weight: dim.weight,
  }));

  const pieData = scores.dimension_scores.map((dim) => ({
    name: dim.name,
    value: dim.score,
    color: getColor(dim.score),
  }));

  if (!scores.dimension_scores.length) {
    return (
      <div role="alert" aria-live="assertive" style={{ padding: '16px', background: 'var(--status-negative-soft)', borderLeft: '4px solid var(--status-negative)', color: 'var(--status-negative)' }}>
        <span aria-hidden="true">⚠️ </span>Scoring results are unavailable.
        <button role="button" aria-label="Return from unavailable scoring results" onClick={onBack} style={{ marginLeft: '16px', padding: '6px 12px', cursor: 'pointer' }}>Back</button>
      </div>
    );
  }

  return (
    <div style={{ maxWidth: '900px', margin: '0 auto', padding: '20px' }}>
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: '12px', justifyContent: 'space-between', alignItems: 'center', marginBottom: '2rem' }}>
        <h1 style={{ color: 'var(--ink)' }}><SectionIcon name="📊" /> Scoring Results</h1>
        <ActionButton variant="quiet" role="button" aria-label="Back to assessment list" onClick={onBack}>
          ← Back
        </ActionButton>
      </div>

      {exportError && (
        <div role="alert" aria-label="Export error notification" style={{ background: 'var(--status-negative-soft)', border: '1px solid var(--status-negative)', borderRadius: 'var(--radius)', padding: '12px 16px', marginBottom: '1rem', color: 'var(--status-negative)' }}>
          {exportError}
        </div>
      )}

      {/* Overview Card */}
      <div style={{
        background: 'var(--gradient-brand)',
        color: 'white',
        borderRadius: 'var(--radius)',
        padding: '2rem',
        marginBottom: '2rem',
        textAlign: 'center'
      }}>
        <h2 style={{ margin: '0 0 1rem 0', overflowWrap: 'anywhere' }}>{use_case.title}</h2>
        <div style={{ fontSize: '4rem', fontWeight: 'bold', margin: '1rem 0' }}>
          {scores.overall_score.toFixed(1)}
        </div>
        <div style={{ fontSize: '1.1rem', opacity: 0.9 }}>Overall Readiness Score</div>
        <div style={{ marginTop: '1rem', fontSize: '0.9rem', opacity: 0.8 }}>
          {/* UX audit #11: scored_at can be absent/unscored → new Date(undefined)
              rendered "Invalid Date". Guard it. */}
          Scored on {scores.scored_at ? new Date(scores.scored_at).toLocaleDateString() : '— (not scored)'}
        </div>
      </div>

      {/* Dimension Scores Table */}
      <div style={{ marginBottom: '2rem', padding: '1rem', background: 'var(--neutral-50)', borderRadius: 'var(--radius)' }}>
        <h3>Dimension Scores</h3>
        <div role="region" aria-label="Dimension scores" tabIndex={0} style={{ overflowX: 'auto' }}><table style={{ width: '100%', borderCollapse: 'collapse' }}>
          <thead>
            <tr>
              <th style={thStyle}>Dimension</th>
              <th style={thStyle}>Score</th>
              <th style={thStyle}>Weight</th>
              <th style={thStyle}>Weighted</th>
            </tr>
          </thead>
          <tbody>
            {scores.dimension_scores.map((dim) => (
              <tr key={dim.name}>
                <td style={tdStyle}>{dim.name}</td>
                <td style={tdStyle}>
                  <span style={{ color: getColor(dim.score), fontWeight: 'bold' }}>
                    {dim.score.toFixed(1)}/100
                  </span>
                </td>
                <td style={tdStyle}>{(dim.weight * 100).toFixed(0)}%</td>
                <td style={tdStyle}>{(dim.score * dim.weight).toFixed(1)}</td>
              </tr>
            ))}
          </tbody>
        </table></div>
      </div>

      {/* Tabs */}
      <div style={{ marginBottom: '1.5rem', display: 'flex', flexWrap: 'wrap', gap: '0.5rem' }}>
        {['radar', 'bars', 'detail'].map((tab) => (
          <button role="button" aria-label={`Show ${tab} tab`}
            key={tab}
            aria-pressed={activeTab === tab}
            onClick={() => updateScoreView({ tab })}
            style={{
              padding: '8px 16px',
              background: activeTab === tab ? 'var(--brand-500)' : 'var(--divider)',
              color: activeTab === tab ? 'var(--neutral-0)' : 'var(--neutral-700)',
              border: 'none',
              borderRadius: 'var(--radius-sm)',
              cursor: 'pointer',
              textTransform: 'capitalize'
            }}
          >
            {tab}
          </button>
        ))}
      </div>

      {/* Radar Chart */}
      {activeTab === 'radar' && (
        <div style={{ marginBottom: '2rem' }}>
          <RadarChartComponent
            dimensionScores={scores.dimension_scores}
            title="Radar View - AI Readiness by Dimension"
          />
        </div>
      )}

      {/* Bar Chart */}
      {activeTab === 'bars' && (
        <div style={{ marginBottom: '2rem' }}>
          <h3 style={{ textAlign: 'center', marginBottom: '1rem' }}>Score Comparison</h3>
          <div style={{ width: '100%', overflowX: 'auto' }}>
            <div role="img" aria-label="Bar chart of dimension scores: " style={{ width: '100%', overflowX: 'auto' }}>
              {/* Text summary for screen readers */}
              <div style={{ position: 'absolute', width: '1px', height: '1px', padding: 0, margin: '-1px', overflow: 'hidden', clip: 'rect(0,0,0,0)', whiteSpace: 'nowrap', border: 0 }} aria-hidden="true">
                {chartData.map(d => `${d.name}: ${d.score.toFixed(1)} out of 100, weight ${d.weight * 100}%`).join('. ')}
              </div>
              <ResponsiveContainer width="100%" minHeight={300}>
                <BarChart data={chartData} style={{ minWidth: '400px' }}>
                  <CartesianGrid strokeDasharray="3 3" />
                  <XAxis dataKey="name" fontSize={11} />
                  <YAxis domain={[0, 100]} fontSize={11} />
                  <Tooltip formatter={(value: number) => `${value.toFixed(1)}`} wrapperStyle={{ fontSize: '12px' }} contentStyle={{ background: 'var(--neutral-0)', border: '1px solid var(--divider)', borderRadius: 'var(--radius)' }} itemStyle={{ color: 'var(--ink)' }} labelStyle={{ color: 'var(--ink)' }} />
                  <Legend wrapperStyle={{ fontSize: '12px' }} />
                  <Bar dataKey="score" name="Score" fill="var(--brand-500)" />
                </BarChart>
              </ResponsiveContainer>
            </div>
          </div>
        </div>
      )}

      {/* Pie Chart */}
      {activeTab === 'bars' && (
        <div style={{ marginBottom: '2rem' }}>
          <h3>Score Distribution</h3>
          <div style={{ width: '100%', overflowX: 'auto' }}>
            <div role="img" aria-label="Pie chart showing score distribution by dimension. Scores range from" style={{ width: '100%', overflowX: 'auto' }}>
              {/* Text summary for screen readers */}
              <div style={{ position: 'absolute', width: '1px', height: '1px', padding: 0, margin: '-1px', overflow: 'hidden', clip: 'rect(0,0,0,0)', whiteSpace: 'nowrap', border: 0 }} aria-hidden="true">
                {pieData.map(d => `${d.name}: ${d.value.toFixed(0)} out of 100`).join('. ')}
              </div>
              <ResponsiveContainer width="100%" minHeight={280}>
                <PieChart style={{ minWidth: '400px' }}>
                  <Pie
                    data={pieData}
                    cx="50%"
                    cy="50%"
                    outerRadius={90}
                    dataKey="value"
                    label={({ name, value }) => `${name.split(' ')[0]}: ${value.toFixed(0)}`}
                  >
                    {pieData.map((entry, index) => (
                      <Cell key={`cell-${index}`} fill={entry.color} />
                    ))}
                  </Pie>
                  <Tooltip formatter={(value: number) => `${value.toFixed(0)}`} wrapperStyle={{ fontSize: '12px' }} contentStyle={{ background: 'var(--neutral-0)', border: '1px solid var(--divider)', borderRadius: 'var(--radius)' }} itemStyle={{ color: 'var(--ink)' }} labelStyle={{ color: 'var(--ink)' }} />
                  <Legend wrapperStyle={{ fontSize: '12px' }} />
                </PieChart>
              </ResponsiveContainer>
            </div>
          </div>
        </div>
      )}

      {/* Detail View */}
      {activeTab === 'detail' && (
        <div style={{ marginBottom: '2rem', padding: '1rem', background: 'var(--neutral-0)', borderRadius: 'var(--radius)', border: '1px solid var(--divider)' }}>
          <h3>Use Case Details</h3>
          
          <div style={{ marginBottom: '1rem' }}>
            <strong>Description:</strong>
            <p style={{ margin: '0.5rem 0' }}>{use_case.description || 'No description'}</p>
          </div>

          <div style={{ marginBottom: '1rem' }}>
            <strong>Goals:</strong>
            <ul style={{ margin: '0.5rem 0' }}>
              {use_case.goals?.map((goal, i) => <li key={i}>{goal}</li>)}
            </ul>
          </div>

          <div style={{ marginBottom: '1rem' }}>
            <strong>Challenges:</strong>
            <ul style={{ margin: '0.5rem 0' }}>
              {use_case.challenges?.map((ch, i) => <li key={i}>{ch}</li>)}
            </ul>
          </div>

          <div style={{ marginBottom: '1rem' }}>
            <strong>Pain Points:</strong>
            <ul style={{ margin: '0.5rem 0' }}>
              {use_case.pain_points?.map((pp, i) => <li key={i}>{pp}</li>)}
            </ul>
          </div>

          <div style={{ marginBottom: '1rem' }}>
            <strong>Business Impact:</strong>
            <ul style={{ margin: '0.5rem 0' }}>
              <li>Category: {use_case.impact_category || 'N/A'}</li>
              <li>Description: {use_case.impact_description || 'N/A'}</li>
              <li>Estimated Savings: ${use_case.estimated_savings?.toLocaleString() || '0'}</li>
              <li>Estimated Revenue: ${use_case.estimated_revenue?.toLocaleString() || '0'}</li>
            </ul>
          </div>
        </div>
      )}

      {/* AI Reasoning */}
      <div style={{ padding: '1rem', background: 'var(--brand-50)', borderRadius: 'var(--radius)', marginBottom: '2rem' }}>
        <h3>AI Reasoning</h3>
        <p style={{ margin: '0.5rem 0', lineHeight: '1.6' }}>{scores.reasoning}</p>
      </div>

      {/* Recommendations */}
      {scores.recommendations && scores.recommendations.length > 0 && (
        <div style={{ padding: '1rem', background: 'var(--status-positive-soft)', borderRadius: 'var(--radius)' }}>
          <h3>Recommendations</h3>
          <ul style={{ margin: '0.5rem 0', paddingLeft: '1.5rem' }}>
            {scores.recommendations.map((rec, i) => (
              <li key={i} style={{ marginBottom: '0.5rem', lineHeight: '1.5' }}>{rec}</li>
            ))}
          </ul>
        </div>
      )}

      {/* Report export is a neutral action, never a danger/success color. */}
      {exporting && <p role="status">Preparing {exporting === 'pdf' ? 'PDF' : 'Excel'} report…</p>}
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: '8px', marginTop: '2rem', justifyContent: 'center' }}>
        <ActionButton variant="secondary" aria-label="Export scoring results as PDF" busy={exporting === 'pdf'} disabled={exporting !== null} icon={<SectionIcon name="📄" />} onClick={() => exportResults('pdf')}>Export PDF</ActionButton>
        <ActionButton variant="secondary" aria-label="Export scoring results as Excel" busy={exporting === 'excel'} disabled={exporting !== null} icon={<SectionIcon name="📊" />} onClick={() => exportResults('excel')}>Export Excel</ActionButton>
      </div>
    </div>
  );
}

const thStyle: React.CSSProperties = {
  textAlign: 'left',
  padding: '12px 8px',
  fontWeight: 600,
  borderBottom: '2px solid var(--divider)',
};

const tdStyle: React.CSSProperties = {
  padding: '12px 8px',
  borderBottom: '1px solid var(--divider)',
};

function getColor(score: number): string {
  if (score >= 70) return 'var(--score-high)';
  if (score >= 35) return 'var(--score-mid)';
  return 'var(--score-low)';
}
export default ScoringDashboard;
