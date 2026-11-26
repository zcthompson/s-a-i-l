import {
  Radar,
  RadarChart,
  PolarGrid,
  PolarAngleAxis,
  PolarRadiusAxis,
  ResponsiveContainer,
  Tooltip,
  Legend,
} from 'recharts';
import { DimensionScore } from '../types/use_case';

interface RadarChartProps {
  dimensionScores: DimensionScore[];
  title?: string;
  size?: number;
}

export function RadarChartComponent({
  dimensionScores,
  title = 'AI Readiness Radar',
  size = 400,
}: RadarChartProps) {
  const data = dimensionScores.map(dim => ({ subject: dim.name, A: dim.score, fullMark: 100 }));

  if (dimensionScores.length === 0) {
    return <div role="status" aria-live="polite" style={{ padding: '2rem', textAlign: 'center', color: 'var(--neutral-500)' }}>No chart data available.</div>;
  }

  return (
    <div style={{ width: '100%', maxWidth: size, margin: '0 auto' }}>
      <h3 style={{ textAlign: 'center', marginBottom: '1rem' }}>{title}</h3>
      <div role="img" aria-label={`${title}. Radar chart showing ${dimensionScores.map(d => `${d.name} at ${d.score} out of 100`).join('. ')}`}>
      <ResponsiveContainer width="100%" height={size}>
        <RadarChart cx="50%" cy="50%" outerRadius="65%" data={data}>
          <PolarGrid stroke="var(--neutral-300)" />
          <PolarAngleAxis dataKey="subject" tick={<RadarLabel />} />
          {/* Place the scale between the first two spokes so ticks never overlap a dimension label. */}
          <PolarRadiusAxis angle={90 - 180 / dimensionScores.length} domain={[0, 100]} tick={{ fill: 'var(--neutral-600)', fontSize: 10 }} />
          <Radar
            name="Score"
            dataKey="A"
            stroke="var(--brand-300)"
            fill="var(--brand-300)"
            fillOpacity={0.6}
          />
          <Tooltip formatter={(value: number) => `${value.toFixed(1)}`} contentStyle={{ background: 'var(--neutral-0)', border: '1px solid var(--divider)' }} labelStyle={{ color: 'var(--ink)' }} itemStyle={{ color: 'var(--ink)' }} />
          <Legend />
        </RadarChart>
      </ResponsiveContainer>
      </div>
      <details style={{ marginTop: 12, color: 'var(--neutral-700)' }}>
        <summary style={{ cursor: 'pointer' }}>View chart data</summary>
        <div role="region" aria-label={`${title} data`} tabIndex={0} style={{ overflowX: 'auto' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '.85rem' }}>
            <caption>Scores out of 100</caption>
            <thead><tr><th scope="col">Dimension</th><th scope="col">Score</th><th scope="col">Weight</th></tr></thead>
            <tbody>{dimensionScores.map(dim => <tr key={dim.name}><th scope="row" style={{ textAlign: 'left', padding: '8px 4px', overflowWrap: 'anywhere' }}>{dim.name}</th><td style={{ padding: '8px 4px' }}>{dim.score.toFixed(1)}</td><td style={{ padding: '8px 4px' }}>{(dim.weight * 100).toFixed(0)}%</td></tr>)}</tbody>
          </table>
        </div>
      </details>
    </div>
  );
}

/** Keep visual labels contained; the full name remains in the chart summary and data table. */
function RadarLabel({ x = 0, y = 0, payload }: { x?: number; y?: number; payload?: { value: string } }) {
  const label = payload?.value || '';
  return <text x={x} y={y} textAnchor="middle" dominantBaseline="central" fill="var(--neutral-700)" fontSize={11}><title>{label}</title>{label.length > 16 ? `${label.slice(0, 15)}…` : label}</text>;
}
