import { useState, useEffect } from 'react';
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  Cell,
  Legend,
  PieChart,
  Pie,
} from 'recharts';
import { api } from '../lib/api';

interface DrillDownProps {
  useCaseId: number;
  onBack?: () => void;
  showHistoryOnly?: boolean;
}

interface DrillDownData {
  id: number;
  title: string;
  department: string;
  status: string;
  overall_score: number;
  dimension_details: Array<{
    name: string;
    score: number;
    weight: number;
    weighted_score: number;
    description: string;
  }>;
  score_history: Array<{
    timestamp: string;
    overall_score: number;
  }>;
  reasoning: string;
  recommendations: string[];
  business_impact: {
    savings: number;
    revenue: number;
    total: number;
  };
  timeline_estimate: string;
  scored_at: string;
}

function getColor(score: number): string {
  if (score >= 70) return 'var(--score-high)';
  if (score >= 35) return 'var(--score-mid)';
  return 'var(--score-low)';
}

export function ScoreDrillDown({ useCaseId, onBack }: DrillDownProps) {
  const [data, setData] = useState<DrillDownData | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.drillDown(useCaseId)
      .then(setData)
      .catch((err: Error) => setError(err.message));
  }, [useCaseId]);

  const handleBack = () => {
    setData(null);
    setError(null);
    if (onBack) onBack();
  };

  if (error) return <div role="alert" aria-live="assertive" style={{ padding: '16px', background: 'var(--status-negative-soft)', borderLeft: '4px solid var(--status-negative)', borderRadius: 'var(--radius-sm)', color: 'var(--status-negative)', marginBottom: '24px' }}>
    <span aria-hidden="true">⚠️ </span>{error}
    <button role="button" aria-label="Retry loading drill-down" onClick={() => window.location.reload()} style={{ marginLeft: '12px', padding: '6px 12px', border: '1px solid var(--status-negative)', borderRadius: 'var(--radius-sm)', background: 'var(--neutral-0)', color: 'var(--status-negative)', cursor: 'pointer', fontWeight: 600 }}>Retry</button>
  </div>;
  if (!data) return <div role="status" aria-live="polite" style={{ padding: '20px', textAlign: 'center', color: 'var(--neutral-500)' }}>Loading drill-down...</div>;

  const dimensionData = data.dimension_details.map(d => ({
    name: d.name,
    score: d.score,
    weighted: d.weighted_score,
  }));

  const pieData = data.dimension_details.map(d => ({
    name: d.name,
    value: d.weighted_score,
  }));

  const historyData = data.score_history.map(h => ({
    date: new Date(h.timestamp).toLocaleDateString(),
    score: h.overall_score,
  }));

  return (
    <div style={{ maxWidth: '1200px', margin: '0 auto', padding: '20px' }}>
      {/* Header */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '2rem' }}>
        <h1 style={{ margin: 0 }}>Score Breakdown</h1>
        <button role="button" aria-label="Back to scoring dashboard"
          onClick={handleBack}
          style={{
            padding: '8px 16px',
            backgroundColor: 'var(--neutral-500)',
            color: 'var(--neutral-0)',
            border: 'none',
            borderRadius: 'var(--radius)',
            cursor: 'pointer',
          }}
        >
          ← Back
        </button>
      </div>

      {/* Overview */}
      <div style={{
        background: 'var(--gradient-brand)',
        color: 'white',
        borderRadius: 'var(--radius)',
        padding: '2rem',
        marginBottom: '2rem',
        textAlign: 'center',
      }}>
        <h2 style={{ margin: '0 0 1rem' }}>{data.title}</h2>
        <div style={{ fontSize: '4rem', fontWeight: 'bold', margin: '1rem 0', color: getColor(data.overall_score) }}>
          {data.overall_score.toFixed(1)}
        </div>
        <div style={{ opacity: 0.9 }}>Overall Readiness Score</div>
        <div style={{ marginTop: '1rem', fontSize: '0.9rem', opacity: 0.8 }}>
          {data.department || 'Unassigned'} • {data.status} • Scored {new Date(data.scored_at).toLocaleDateString()}
        </div>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '2rem', marginBottom: '2rem' }}>
        {/* Bar chart */}
        <div style={{ padding: '1rem', background: 'var(--neutral-0)', borderRadius: 'var(--radius)', boxShadow: 'var(--shadow-card)' }}>
          <h3 style={{ marginBottom: '1rem' }}>Dimension Scores</h3>
          <ResponsiveContainer width="100%" minHeight={300}>
            <BarChart
              data={dimensionData}
              tabIndex={0}
              role="img"
              aria-label={`Bar chart of dimension scores: ${dimensionData.map(d => `${d.name} at ${d.score}`).join(', ')}.`}
            >
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey="name" fontSize={11} />
              <YAxis domain={[0, 100]} fontSize={11} />
              <Tooltip formatter={(value: number) => `${value.toFixed(1)}`} wrapperStyle={{ fontSize: '12px' }} />
              <Legend wrapperStyle={{ fontSize: '12px' }} />
              <Bar dataKey="score" name="Score">
                {dimensionData.map((entry, index) => (
                  <Cell key={`cell-${index}`} fill={getColor(entry.score)} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>

        {/* Pie chart */}
        <div style={{ padding: '1rem', background: 'var(--neutral-0)', borderRadius: 'var(--radius)', boxShadow: 'var(--shadow-card)' }}>
          <h3 style={{ marginBottom: '1rem' }}>Weighted Contribution</h3>
          <ResponsiveContainer width="100%" minHeight={280}>
            <PieChart
              tabIndex={0}
              role="img"
              aria-label={`Pie chart showing weighted contribution: ${pieData.map(d => `${d.name} at ${d.value.toFixed(0)}`).join(', ')}.`}
            >
              <Pie
                data={pieData}
                cx="50%"
                cy="50%"
                labelLine={false}
                label={({ name, value }) => `${name.split(' ')[0]}: ${value.toFixed(0)}`}
                outerRadius={90}
                dataKey="value"
              >
                {pieData.map((_entry, index) => (
                  <Cell key={`cell-${index}`} fill={getColor(index * 20)} />
                ))}
              </Pie>
              <Tooltip formatter={(value: number) => `${value.toFixed(0)}`} wrapperStyle={{ fontSize: '12px' }} />
              <Legend wrapperStyle={{ fontSize: '12px' }} />
            </PieChart>
          </ResponsiveContainer>
        </div>
      </div>

      {/* Dimension details table */}
      <div style={{ padding: '1rem', background: 'var(--neutral-0)', borderRadius: 'var(--radius)', boxShadow: 'var(--shadow-card)', marginBottom: '2rem' }}>
        <h3 style={{ marginBottom: '1rem' }}>Dimension Details</h3>
        <div style={{ overflowX: 'auto' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse' }}>
            <thead>
              <tr>
                <th style={thStyle}>Dimension</th>
                <th style={thStyle}>Score</th>
                <th style={thStyle}>Weight</th>
                <th style={thStyle}>Weighted Score</th>
                <th style={thStyle}>Description</th>
              </tr>
            </thead>
            <tbody>
              {data.dimension_details.map((dim) => (
                <tr key={dim.name}>
                  <td style={tdStyle}>
                    <span style={{
                      display: 'inline-block',
                      width: '12px',
                      height: '12px',
                      borderRadius: '50%',
                      backgroundColor: getColor(dim.score),
                      marginRight: '8px',
                    }}></span>
                    {dim.name}
                  </td>
                  <td style={tdStyle}>
                    <strong style={{ color: getColor(dim.score) }}>{dim.score.toFixed(1)}</strong>
                  </td>
                  <td style={tdStyle}>{(dim.weight * 100).toFixed(0)}%</td>
                  <td style={tdStyle}>
                    <strong>{dim.weighted_score.toFixed(1)}</strong>
                  </td>
                  <td style={tdStyle}>{dim.description || 'N/A'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* Score history */}
      {historyData.length > 0 && (
        <div style={{ padding: '1rem', background: 'var(--neutral-0)', borderRadius: 'var(--radius)', boxShadow: 'var(--shadow-card)', marginBottom: '2rem' }}>
          <h3 style={{ marginBottom: '1rem' }}>Score History</h3>
          <ResponsiveContainer width="100%" height={200}>
            <BarChart data={historyData}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey="date" />
              <YAxis domain={[0, 100]} />
              <Tooltip />
              <Bar dataKey="score" name="Overall Score" fill="var(--brand-500)" />
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}

      {/* Business impact */}
      <div style={{ padding: '1rem', background: 'var(--brand-50)', borderRadius: 'var(--radius)', marginBottom: '2rem' }}>
        <h3 style={{ marginBottom: '1rem' }}>Business Impact</h3>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: '1rem' }}>
          <div style={{ background: 'var(--neutral-0)', padding: '1rem', borderRadius: 'var(--radius)', textAlign: 'center' }}>
            <div style={{ fontSize: '1.5rem', fontWeight: 'bold', color: 'var(--status-positive)' }}>
              ${data.business_impact.savings.toLocaleString()}
            </div>
            <div style={{ color: 'var(--neutral-500)', fontSize: '0.9rem', marginTop: '0.5rem' }}>Est. Savings</div>
          </div>
          <div style={{ background: 'var(--neutral-0)', padding: '1rem', borderRadius: 'var(--radius)', textAlign: 'center' }}>
            <div style={{ fontSize: '1.5rem', fontWeight: 'bold', color: 'var(--brand-700)' }}>
              ${data.business_impact.revenue.toLocaleString()}
            </div>
            <div style={{ color: 'var(--neutral-500)', fontSize: '0.9rem', marginTop: '0.5rem' }}>Est. Revenue</div>
          </div>
          <div style={{ background: 'var(--neutral-0)', padding: '1rem', borderRadius: 'var(--radius)', textAlign: 'center' }}>
            <div style={{ fontSize: '1.5rem', fontWeight: 'bold', color: 'var(--status-warning)' }}>
              ${data.business_impact.total.toLocaleString()}
            </div>
            <div style={{ color: 'var(--neutral-500)', fontSize: '0.9rem', marginTop: '0.5rem' }}>Total Impact</div>
          </div>
        </div>
      </div>

      {/* Reasoning & Recommendations */}
      {data.reasoning && (
        <div style={{ padding: '1rem', background: 'var(--status-warning-soft)', borderRadius: 'var(--radius)', marginBottom: '2rem' }}>
          <h3 style={{ marginBottom: '1rem' }}>AI Reasoning</h3>
          <p style={{ margin: 0, lineHeight: '1.6' }}>{data.reasoning}</p>
        </div>
      )}

      {data.recommendations?.length > 0 && (
        <div style={{ padding: '1rem', background: 'var(--status-positive-soft)', borderRadius: 'var(--radius)' }}>
          <h3 style={{ marginBottom: '1rem' }}>Recommendations</h3>
          <ul style={{ margin: 0, paddingLeft: '1.5rem' }}>
            {data.recommendations.map((rec, i) => (
              <li key={i} style={{ marginBottom: '0.5rem', lineHeight: '1.5' }}>{rec}</li>
            ))}
          </ul>
        </div>
      )}
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
export default ScoreDrillDown;
