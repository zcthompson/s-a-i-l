import { useEffect, useState } from 'react';
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  ReferenceLine,
  Cell,
} from 'recharts';
import { api } from '../lib/api';

const scoreColor = (v: number | null | undefined) =>
  v == null ? 'var(--score-unscored)' : v >= 70 ? 'var(--score-high)' : v >= 35 ? 'var(--score-mid)' : 'var(--score-low)';

const classify = (v: number): [string, string] =>
  v >= 70 ? ['Strong', 'var(--score-high)'] : v >= 35 ? ['Moderate', 'var(--score-mid)'] : ['Weak', 'var(--score-low)'];

function DimensionTooltip({ active, payload, label }: any) {
  if (!active || !payload || payload.length === 0) return null;
  const rows = [...payload]
    .filter((e: any) => e && typeof e.value === 'number')
    .sort((a: any, b: any) => b.value - a.value);
  if (rows.length === 0) return null;
  return (
    <div
      style={{
        background: 'var(--neutral-0)',
        boxShadow: 'var(--shadow-raised)',
        borderRadius: 'var(--radius)',
        padding: '12px',
        border: '1px solid var(--divider)',
        fontSize: '12px',
      }}
    >
      <div style={{ fontWeight: 700, fontSize: '0.85rem', color: 'var(--ink)', marginBottom: '4px' }}>{label}</div>
      {rows.map((e: any) => {
        const [word, color] = classify(e.value);
        return (
          <div key={e.name} style={{ display: 'flex', justifyContent: 'space-between', gap: '16px', minWidth: '220px', marginTop: '4px' }}>
            <span style={{ fontSize: '0.8rem', fontWeight: 700, color: 'var(--neutral-700)' }}>{e.name}</span>
            <span style={{ fontSize: '0.8rem', color: 'var(--neutral-800)' }}>
              {e.value.toFixed(1)} · <span style={{ color, fontWeight: 700 }}>{word}</span>
            </span>
          </div>
        );
      })}
    </div>
  );
}

interface DeptComparisonData {
  departments: Array<{
    department: string;
    use_case_count: number;
    avg_overall: number;
    dimension_avgs: Array<{
      dimension: string;
      avg_score: number;
      count: number;
      min_score: number;
      max_score: number;
    }>;
  }>;
  dimensions: string[];
}

interface DeptComparisonProps {
  customerId?: number | null;
  onBack?: () => void;
  /**
   * Which part of the component to render:
   * - 'all' (default): full standalone component (deep-link view)
   * - 'summary': the Department Summary table block
   * - 'comparison': the Department Comparison chart block
   */
  section?: 'all' | 'comparison' | 'summary' | 'breakdown';
}

export function DeptComparison({ customerId, onBack, section = 'all' }: DeptComparisonProps = {}) {
  const [data, setData] = useState<DeptComparisonData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const params: Record<string, string> = {};
    if (customerId !== null && customerId !== undefined) {
      params.customer_id = String(customerId);
    }
    api
      .deptComparison(params)
      .then(setData)
      .catch((err: Error) => setError(err.message))
      .finally(() => setLoading(false));
  }, [customerId]);

  if (loading) return <div style={{ padding: '20px', textAlign: 'center' }}>Loading...</div>;
  if (!data?.departments.length) return <div style={{ padding: '20px', color: 'var(--neutral-500)', textAlign: 'center' }}>No department comparison data available.</div>;
  if (error) return <div role="alert" aria-live="assertive" style={{ padding: '16px', background: 'var(--status-negative-soft)', borderLeft: '4px solid var(--status-negative)', borderRadius: 'var(--radius-sm)', color: 'var(--status-negative)', marginBottom: '24px' }}>
    <span aria-hidden="true">⚠️ </span>{error}
    <button role="button" aria-label="Retry loading" onClick={() => window.location.reload()} style={{ marginLeft: '12px', padding: '6px 12px', border: '1px solid var(--status-negative)', borderRadius: 'var(--radius-sm)', background: 'var(--neutral-0)', color: 'var(--status-negative)', cursor: 'pointer', fontWeight: 600 }}>Retry</button>
  </div>;

  // Build chart data from department data
  const chartData = data.dimensions.map(dimension => {
    const entry: Record<string, any> = { dimension };
    data.departments.forEach(d => {
      const dimData = d.dimension_avgs.find(da => da.dimension === dimension);
      entry[d.department] = dimData ? dimData.avg_score : 0;
    });
    return entry;
  });

  // Build summary table
  const summaryData = data.departments.map((d) => ({
    department: d.department,
    count: d.use_case_count,
    avg_overall: d.avg_overall,
    best: d.dimension_avgs.reduce((best, a) => a.avg_score > best.avg_score ? a : best, d.dimension_avgs[0]),
    worst: d.dimension_avgs.reduce((worst, a) => a.avg_score < worst.avg_score ? a : worst, d.dimension_avgs[0]),
  }));

  const comparisonChart = (
    <div
      style={{ marginBottom: '1.5rem', padding: '1rem', background: 'var(--neutral-0)', borderRadius: 'var(--radius)', boxShadow: 'var(--shadow-card)' }}
      role="region"
      aria-label="Department comparison chart"
    >
      <h3 style={{ marginBottom: '1rem' }}>Average Dimension Scores by Department</h3>
      <div style={{ display: 'flex', gap: '16px', marginBottom: '12px', flexWrap: 'wrap' }}>
        {[
          { label: 'Weak (<35)', color: 'var(--score-low)' },
          { label: 'Moderate (35–69)', color: 'var(--score-mid)' },
          { label: 'Strong (70+)', color: 'var(--score-high)' },
        ].map(c => (
          <span key={c.label} style={{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: '0.8rem', color: 'var(--neutral-600)' }}>
            <span style={{ display: 'inline-block', width: '12px', height: '12px', background: c.color }} />
            {c.label}
          </span>
        ))}
      </div>
      <ResponsiveContainer width="100%" height={420}>
        <BarChart
          data={chartData}
          barGap="18%"
          barCategoryGap="25%"
          tabIndex={0}
          role="img"
          aria-label={`Bar chart comparing dimension scores across ${data.departments.length} departments: ${data.departments.map(d => `${d.department} (${d.use_case_count} use cases)`).join(', ')}.`}
        >
          <CartesianGrid strokeDasharray="3 3" vertical={false} />
          <XAxis dataKey="dimension" interval={0} tick={{ fontSize: 12 }} angle={-25} textAnchor="end" height={70} dy={8} />
          <YAxis domain={[0, 100]} ticks={[0, 35, 70, 100]} tick={{ fontSize: 12 }} />
          <Tooltip content={<DimensionTooltip />} />
          {data.departments.map((dept) => (
            <Bar
              key={dept.department}
              dataKey={dept.department}
              maxBarSize={26}
              radius={[4, 4, 0, 0]}
            >
              {chartData.map((row, i) => (
                <Cell key={i} fill={scoreColor(row[dept.department])} />
              ))}
            </Bar>
          ))}
          <ReferenceLine y={35} stroke="var(--score-mid)" strokeWidth={2} label={{ value: 'Moderate (35)', position: 'right', fill: 'var(--score-mid)', fontSize: 12, fontWeight: 600 }} />
          <ReferenceLine y={70} stroke="var(--score-high)" strokeWidth={2} label={{ value: 'Strong (70)', position: 'right', fill: 'var(--score-high)', fontSize: 12, fontWeight: 600 }} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );

  const summaryTable = (
    <div style={{ overflowX: 'auto' }}>
      <table style={{ width: '100%', borderCollapse: 'collapse' }}>
        <thead>
          <tr>
            <th style={thStyle}>Department</th>
            <th style={thStyle}>Use Cases</th>
            <th style={thStyle}>Avg Overall Score</th>
            <th style={thStyle}>Best Dimension</th>
            <th style={thStyle}>Weakest Dimension</th>
          </tr>
        </thead>
        <tbody>
          {summaryData.map((row) => (
            <tr key={row.department}>
              <td style={tdStyle}>
                {row.department}
              </td>
              <td style={tdStyle}>{row.count}</td>
              <td style={tdStyle}>
                <span style={{
                  fontWeight: 'bold',
                  color: row.avg_overall >= 70 ? 'var(--score-high)' : row.avg_overall >= 35 ? 'var(--score-mid)' : 'var(--score-low)'
                }}>
                  {row.avg_overall.toFixed(1)}
                </span>
              </td>
              <td style={tdStyle}>
                <span style={{ color: 'var(--status-positive)', fontWeight: 'bold' }}>{row.best.dimension}</span>
                {' '}{row.best.avg_score.toFixed(1)}
              </td>
              <td style={tdStyle}>
                <span style={{ color: 'var(--status-negative)', fontWeight: 'bold' }}>{row.worst.dimension}</span>
                {' '}{row.worst.avg_score.toFixed(1)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );

  // Single-section blocks (customer analytics vertical stack)
  if (section === 'summary') {
    return (
      <div style={{ marginBottom: '2rem' }}>
        <h2 style={{ margin: '0 0 1rem 0', color: 'var(--neutral-700)' }}>Department Summary</h2>
        <div style={{ padding: '1rem', background: 'var(--neutral-0)', borderRadius: 'var(--radius)', boxShadow: 'var(--shadow-card)' }}>
          {summaryTable}
        </div>
      </div>
    );
  }
  if (section === 'comparison') {
    return (
      <div style={{ marginBottom: '2rem' }}>
        <h2 style={{ margin: '0 0 1rem 0', color: 'var(--neutral-700)' }}>Department Comparison</h2>
        {comparisonChart}
      </div>
    );
  }
  if (section === 'breakdown') {
    const topDepts = [...data.departments].sort((a, b) => b.use_case_count - a.use_case_count).slice(0, 12);
    const countData = topDepts.map(d => ({ department: d.department, use_cases: d.use_case_count }));
    const scoreData = topDepts.map(d => ({ department: d.department, avg_overall: Math.round(d.avg_overall * 10) / 10 }));
    return (
      <div style={{ marginBottom: '2rem' }}>
        <h2 style={{ margin: '0 0 1rem 0', color: 'var(--neutral-700)' }}>Departmental Breakdown</h2>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(380px, 1fr))', gap: '16px' }}>
          <div style={{ padding: '1rem', background: 'var(--neutral-0)', borderRadius: 'var(--radius)', boxShadow: 'var(--shadow-card)' }}>
            <h3 style={{ marginBottom: '1rem', fontSize: '1rem' }}>Use Cases by Department</h3>
            <ResponsiveContainer width="100%" height={300}>
              <BarChart data={countData} layout="vertical" margin={{ left: 40 }}>
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis type="number" allowDecimals={false} />
                <YAxis type="category" dataKey="department" width={110} tick={{ fontSize: 11 }} />
                <Tooltip />
                <Bar dataKey="use_cases" fill="var(--brand-500)" radius={[0, 4, 4, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
          <div style={{ padding: '1rem', background: 'var(--neutral-0)', borderRadius: 'var(--radius)', boxShadow: 'var(--shadow-card)' }}>
            <h3 style={{ marginBottom: '1rem', fontSize: '1rem' }}>Avg Readiness by Department</h3>
            <ResponsiveContainer width="100%" height={300}>
              <BarChart data={scoreData} layout="vertical" margin={{ left: 40 }}>
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis type="number" domain={[0, 100]} />
                <YAxis type="category" dataKey="department" width={110} tick={{ fontSize: 11 }} />
                <Tooltip formatter={(value: number) => value.toFixed(1)} />
                <Bar dataKey="avg_overall" fill="var(--status-positive)" radius={[0, 4, 4, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div style={{ marginBottom: '2rem' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1rem' }}>
        <h2 style={{ margin: 0, color: 'var(--neutral-700)' }}>Department Comparison</h2>
        {onBack && (
          <button role="button" aria-label="Back to analytics" onClick={onBack} style={{ padding: '8px 16px', background: 'var(--neutral-500)', color: 'var(--neutral-0)', border: 'none', borderRadius: 'var(--radius)', cursor: 'pointer', fontSize: '0.85rem' }}>
            ← Back to Dashboard
          </button>
        )}
      </div>

      {comparisonChart}

      {/* Summary table */}
      <div style={{ padding: '1rem', background: 'var(--neutral-0)', borderRadius: 'var(--radius)', boxShadow: 'var(--shadow-card)' }}>
        <h3 style={{ marginBottom: '1rem' }}>Department Summary</h3>
        {summaryTable}
      </div>
    </div>
  );
}

const thStyle: React.CSSProperties = {
  textAlign: 'left',
  padding: '12px 8px',
  fontWeight: 600,
  color: 'var(--neutral-700)',
  borderBottom: '2px solid var(--divider)',
};

const tdStyle: React.CSSProperties = {
  padding: '12px 8px',
  borderBottom: '1px solid var(--divider)',
};
export default DeptComparison;
