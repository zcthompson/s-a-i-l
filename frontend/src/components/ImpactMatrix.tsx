/**
 * Business Impact Matrix — scatter plot: impact vs effort.
 * Accepts an optional customerId to scope the query to a single customer.
 */

import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react';
import {
  ScatterChart,
  Scatter,
  XAxis,
  YAxis,
  ZAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
} from 'recharts';
import { api } from '../lib/api';

interface ImpactMatrixData {
  points: Array<{
    id: number;
    title: string;
    department: string;
    overall_score: number;
    total_impact: number;
    effort_level: number;
    effort_label: string;
    impact_category: string;
    status: string;
  }>;
  quadrants: Record<string, string[]>;
}

interface ImpactMatrixProps {
  customerId?: number | null;
  onBack?: () => void;
  /**
   * Which part of the component to render:
   * - 'all' (default): full standalone component (deep-link view)
   * - 'matrix': the Business Impact Matrix chart block
   * - 'quadrant': the Quadrant Breakdown block
   */
  section?: 'all' | 'matrix' | 'quadrant';
}

const compactCurrency = (v: number) => {
  if (v >= 1e6) return `$${(v / 1e6).toFixed(1).replace(/\.0$/, '')}M`;
  if (v >= 1e3) return `$${(v / 1e3).toFixed(0)}k`;
  return `$${v}`;
};

function readinessChip(z: number) {
  const [label, color] =
    z >= 70 ? ['Strong', 'var(--score-high)'] : z >= 35 ? ['Moderate', 'var(--score-mid)'] : ['Weak', 'var(--score-low)'];
  return (
    <span
      style={{
        fontSize: '0.65rem',
        fontWeight: 700,
        padding: '2px 8px',
        borderRadius: 'var(--radius-pill)',
        background: 'var(--neutral-100)',
        color,
      }}
    >
      {label}
    </span>
  );
}

function MatrixTooltip({ active, payload, deptColors }: any) {
  if (!active || !payload || payload.length === 0) return null;
  const p = payload[0]?.payload;
  if (!p) return null;

  const rowLabel: React.CSSProperties = { fontSize: '0.75rem', color: 'var(--neutral-500)' };
  const rowValue: React.CSSProperties = { fontSize: '0.8rem', color: 'var(--neutral-800)' };
  const row: React.CSSProperties = {
    display: 'flex',
    justifyContent: 'space-between',
    alignItems: 'center',
    gap: '16px',
    minWidth: '220px',
    marginTop: '4px',
  };

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
      <div style={{ fontWeight: 700, fontSize: '0.85rem', color: 'var(--ink)', maxWidth: '260px', whiteSpace: 'normal' }}>
        {p.title}
      </div>
      <div style={{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: '0.8rem', color: 'var(--neutral-600)', marginTop: '4px' }}>
        <span
          style={{
            display: 'inline-block',
            width: '10px',
            height: '10px',
            borderRadius: '50%',
            background: deptColors?.[p.department] || 'var(--neutral-400)',
          }}
        />
        {p.department}
      </div>
      <div style={row}>
        <span style={rowLabel}>Impact</span>
        <span style={rowValue}>${p.y?.toLocaleString()}</span>
      </div>
      <div style={row}>
        <span style={rowLabel}>Effort</span>
        <span style={rowValue}>{p.effort_label}</span>
      </div>
      <div style={row}>
        <span style={rowLabel}>Readiness</span>
        <span style={{ ...rowValue, display: 'flex', alignItems: 'center', gap: '6px' }}>
          {typeof p.z === 'number' ? p.z.toFixed(1) : '—'} {readinessChip(p.z ?? 0)}
        </span>
      </div>
      <div style={row}>
        <span style={rowLabel}>Impact category</span>
        <span style={rowValue}>{p.impact_category || '—'}</span>
      </div>
      <div style={row}>
        <span style={rowLabel}>Status</span>
        <span style={rowValue}>{p.status || '—'}</span>
      </div>
    </div>
  );
}

interface MatrixLegendItem {
  name: string;
  color: string;
}

/**
 * Department legend for the Business Impact Matrix — rendered as an HTML
 * list BELOW the chart, not as a recharts <Legend>.
 *
 * Why: recharts draws the bottom XAxis label ("Effort Level",
 * position 'bottom', offset 0) with its text top at the bottom edge of the
 * 30px axis region, extending DOWN into the bottom margin (see recharts
 * Label.js: y = viewBox.y + height + offset, verticalAnchor 'start'). The
 * recharts <Legend> is an absolutely-positioned div anchored at
 * bottom: margin.bottom (32px) — its top edge lands on exactly that same y,
 * so the department names rendered ON TOP of the "Effort Level" text.
 *
 * Below the chart the legend is structurally separated from the axis label:
 * the label bottom ends ~16px above the svg bottom, this block starts 24px
 * below it — 40px of clear space, 12% of the 340px chart height (the
 * requested minimum was 10%), and the block as a whole sits 72-88px
 * (21-26%) lower than the previous in-chart legend position.
 *
 * Rows: the items wrap naturally and are capped at TWO rows using measured
 * item widths (a hidden measurement layer with the same markup, so the cap
 * follows the real font metrics, not estimates). When more departments do
 * not fit in two rows, the overflow collapses into a "+N more" toggle that
 * expands/collapses on demand.
 */
const LEGEND_COL_GAP = 16; // px between items — must match the visible row's columnGap
const LEGEND_CHIP_RESERVE = 110; // px reserved on row 2 for the "+N more" toggle

export function MatrixLegend({ items }: { items: MatrixLegendItem[] }) {
  const [expanded, setExpanded] = useState(false);
  // null = uncapped (unmeasurable layout, or everything fits in two rows)
  const [cap, setCap] = useState<number | null>(null);
  const layerRef = useRef<HTMLDivElement | null>(null);
  const rowRef = useRef<HTMLDivElement | null>(null);

  /**
   * How many items physically fit in the first two rows, greedy fill in
   * DOM (score-ranked) order. Row 2 reserves space for the overflow chip.
   * Returns null when widths are not measurable (e.g. jsdom) → no cap.
   */
  const computeCap = useCallback((): number | null => {
    const layer = layerRef.current;
    const row = rowRef.current;
    if (!layer || !row) return null;
    const available = row.clientWidth;
    if (available <= 0) return null;
    const widths = Array.from(layer.children).map(el => (el as HTMLElement).offsetWidth);
    if (widths.length !== items.length || widths.some(w => w <= 0)) return null;
    const pack = (from: number, budget: number): number => {
      let used = 0;
      let count = from;
      let started = false;
      while (count < widths.length) {
        const need = started ? used + LEGEND_COL_GAP + widths[count] : widths[count];
        if (need > budget) break;
        used = need;
        started = true;
        count += 1;
      }
      return count;
    };
    const row1 = pack(0, available);
    if (row1 === items.length) return items.length; // everything fits
    const row2 = pack(row1, available - LEGEND_CHIP_RESERVE);
    return Math.max(1, row2);
  }, [items.length]);

  // Measure before paint (useLayoutEffect) so the first rendered frame is
  // already capped; re-measure on expand/collapse and container resize.
  useLayoutEffect(() => {
    setCap(expanded ? null : computeCap());
  }, [expanded, computeCap]);

  useLayoutEffect(() => {
    if (expanded) return;
    const row = rowRef.current;
    if (!row || typeof ResizeObserver === 'undefined') return;
    const observer = new ResizeObserver(() => setCap(computeCap()));
    observer.observe(row);
    return () => observer.disconnect();
  }, [expanded, computeCap]);

  // Window resize re-measures as well (covers container width changes in
  // environments without ResizeObserver, e.g. jsdom).
  useLayoutEffect(() => {
    if (expanded) return;
    const onResize = () => setCap(computeCap());
    window.addEventListener('resize', onResize);
    return () => window.removeEventListener('resize', onResize);
  }, [expanded, computeCap]);

  const visibleCount = expanded || cap === null ? items.length : Math.min(cap, items.length);
  const hiddenCount = items.length - visibleCount;

  const itemSpan: React.CSSProperties = {
    display: 'inline-flex',
    alignItems: 'center',
    columnGap: '6px',
    whiteSpace: 'nowrap',
  };
  const dot: React.CSSProperties = {
    display: 'inline-block',
    width: '10px',
    height: '10px',
    borderRadius: '50%',
    flexShrink: 0,
  };

  return (
    <div style={{ position: 'relative', marginTop: '24px' }}>
      <div
        ref={rowRef}
        role="list"
        aria-label="Chart legend: departments ranked by average readiness score"
        style={{ display: 'flex', flexWrap: 'wrap', columnGap: LEGEND_COL_GAP, rowGap: '6px' }}
      >
        {/* Hidden measurement layer: every item at its natural width with the
            same markup/styles as the visible row, so the two-row cap is
            computed from real font metrics. Out of flow, invisible, no
            layout impact. */}
        <div
          ref={layerRef}
          aria-hidden="true"
          style={{ position: 'absolute', left: 0, top: 0, visibility: 'hidden', pointerEvents: 'none', height: 0, overflow: 'hidden', whiteSpace: 'nowrap' }}
        >
          {items.map(item => (
            <span key={item.name} style={itemSpan}>
              <span aria-hidden="true" style={{ ...dot, background: item.color }} />
              {item.name}
            </span>
          ))}
        </div>
        {items.slice(0, visibleCount).map(item => (
          <span key={item.name} role="listitem" style={{ ...itemSpan, fontSize: '12px', color: 'var(--neutral-600)' }}>
            <span aria-hidden="true" style={{ ...dot, background: item.color }} />
            {item.name}
          </span>
        ))}
        {(hiddenCount > 0 || expanded) && (
          <span role="listitem">
            <button
              role="button"
              aria-label={expanded ? 'Collapse department legend' : `Show ${hiddenCount} more departments`}
              onClick={() => setExpanded(v => !v)}
              style={{ display: 'inline-flex', alignItems: 'center', fontSize: '12px', fontWeight: 600, color: 'var(--brand-700)', background: 'var(--brand-50)', border: 'none', borderRadius: 'var(--radius-pill)', padding: '2px 10px', cursor: 'pointer' }}
            >
              {expanded ? 'Show less' : `+${hiddenCount} more`}
            </button>
          </span>
        )}
      </div>
    </div>
  );
}

export function ImpactMatrix({ customerId, onBack, section = 'all' }: ImpactMatrixProps = {}) {
  const [data, setData] = useState<ImpactMatrixData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const params: Record<string, string> = {};
    if (customerId !== null && customerId !== undefined) {
      params.customer_id = String(customerId);
    }
    api
      .impactMatrix(params)
      .then(setData)
      .catch((err: Error) => setError(err.message))
      .finally(() => setLoading(false));
  }, [customerId]);

  // Prepare scatter data from impact matrix
  const chartData = (data?.points ?? []).map(p => ({
    x: p.effort_level,
    y: p.total_impact,
    z: p.overall_score,
    title: p.title,
    department: p.department,
    effort_label: p.effort_label,
    impact_category: p.impact_category,
    status: p.status,
  }));

  // Group by department for colored bubbles. Departments are ranked by their
  // average readiness score (highest first; unscored departments last), so the
  // legend — and the cat-color assignment that follows it — present the top-
  // scoring departments first, then the next-lower, and so on (WP30).
  const departments = data?.points.map(p => p.department).filter(Boolean) ?? [];
  const deptScoreSum: Record<string, number> = {};
  const deptScoreCount: Record<string, number> = {};
  (data?.points ?? []).forEach(p => {
    if (!p.department || p.overall_score == null) return;
    deptScoreSum[p.department] = (deptScoreSum[p.department] ?? 0) + p.overall_score;
    deptScoreCount[p.department] = (deptScoreCount[p.department] ?? 0) + 1;
  });
  const deptAvgScore = (dept: string): number | null =>
    deptScoreCount[dept] ? deptScoreSum[dept] / deptScoreCount[dept] : null;
  const uniqueDepts = [...new Set(departments)].sort((a, b) => {
    const sa = deptAvgScore(a);
    const sb = deptAvgScore(b);
    if (sa == null && sb == null) return 0;
    if (sa == null) return 1;
    if (sb == null) return -1;
    return sb - sa;
  });
  const deptColors: Record<string, string> = {};
  uniqueDepts.forEach((dept, i) => {
    deptColors[dept] = i < 13 ? `var(--cat-${i + 1})` : 'var(--neutral-400)';
  });
  const legendItems = uniqueDepts.map(dept => ({ name: dept, color: deptColors[dept] }));

  if (loading) return <div role="status" aria-live="polite" style={{ padding: '20px', textAlign: 'center', color: 'var(--neutral-500)' }}>Loading impact matrix...</div>;
  if (error) return <div role="alert" aria-live="assertive" style={{ padding: '16px', background: 'var(--status-negative-soft)', borderLeft: '4px solid var(--status-negative)', borderRadius: 'var(--radius-sm)', color: 'var(--status-negative)', marginBottom: '24px' }}>
    <span aria-hidden="true">⚠️ </span>{error}
    <button role="button" aria-label="Retry loading impact matrix" onClick={() => window.location.reload()} style={{ marginLeft: '12px', padding: '6px 12px', border: '1px solid var(--status-negative)', borderRadius: 'var(--radius-sm)', background: 'var(--neutral-0)', color: 'var(--status-negative)', cursor: 'pointer', fontWeight: 600 }}>Retry</button>
  </div>;
  if (!data?.points.length) return <div role="alert" aria-live="polite" style={{ padding: '20px', color: 'var(--neutral-500)', textAlign: 'center' }}>No scored use cases with impact data to display.</div>;

  const avgScore = data.points.reduce((sum, p) => sum + p.overall_score, 0) / data.points.length;
  const totalImpact = data.points.reduce((sum, p) => sum + p.total_impact, 0);

  const kpiCell: React.CSSProperties = {
    padding: '0.75rem 1rem',
    background: 'var(--neutral-50)',
    borderRadius: 'var(--radius-sm)',
  };
  const kpiLabel: React.CSSProperties = {
    fontSize: '0.7rem',
    textTransform: 'uppercase',
    letterSpacing: '0.5px',
    color: 'var(--neutral-500)',
  };
  const kpiValue: React.CSSProperties = { fontSize: '1.4rem', fontWeight: 700, color: 'var(--ink)' };

  const matrixContent = (
    <div>
      {/* Main chart */}
      <div
        style={{ padding: '1.25rem', background: 'var(--neutral-0)', borderRadius: 'var(--radius)', boxShadow: 'var(--shadow-card)' }}
        role="region"
        aria-label="Business impact matrix chart"
      >
        <p style={{ color: 'var(--neutral-500)', fontSize: '0.85rem', marginBottom: '1rem' }}>
          Impact (Y) vs Effort (X) for every scored use case — bubble size is the readiness score; hover a point for full detail. The legend ranks departments by average readiness score (highest first).
        </p>
        <ResponsiveContainer width="100%" height={340}>
          <ScatterChart
            margin={{ top: 24, right: 24, bottom: 32, left: 16 }}
            tabIndex={0}
            role="img"
            aria-label={`Scatter plot showing impact vs effort. Departments: ${uniqueDepts.join(', ')}. Total use cases: ${data.points.length}.`}
          >
            <CartesianGrid strokeDasharray="3 3" />
            <XAxis
              type="number"
              dataKey="x"
              name="Effort"
              domain={[0.5, 3.5]}
              ticks={[1, 2, 3]}
              tickFormatter={(v: number) => {
                const labels: Record<number, string> = { 1: 'Short', 2: 'Medium', 3: 'Long' };
                return labels[v] || String(v);
              }}
              fontSize={12}
              label={{ value: 'Effort Level', position: 'bottom', offset: 0, fill: 'var(--neutral-500)', fontSize: 13 }}
            />
            <YAxis
              type="number"
              dataKey="y"
              name="Impact"
              fontSize={12}
              tickFormatter={compactCurrency}
              label={{ value: 'Total Impact ($)', angle: -90, position: 'insideLeft', offset: 8, fontSize: 13, fill: 'var(--neutral-500)' }}
            />
            <ZAxis type="number" dataKey="z" range={[40, 320]} name="Readiness" />
            <Tooltip content={<MatrixTooltip deptColors={deptColors} />} cursor={{ strokeDasharray: '3 3' }} />
            {uniqueDepts.map((dept) => (
              <Scatter
                key={dept}
                name={dept}
                data={chartData.filter(p => p.department === dept)}
                fill={deptColors[dept]}
                stroke="var(--neutral-0)"
                strokeWidth={1.5}
                tabIndex={0}
                aria-label={`${dept} department data points`}
              />
            ))}
          </ScatterChart>
        </ResponsiveContainer>
        {/* Department legend BELOW the chart: structurally clear of the
            "Effort Level" axis label (40px separation, >10% of the 340px
            chart height) and capped at two rows with a "+N more" expander. */}
        <MatrixLegend items={legendItems} />
      </div>

      {/* Summary stats */}
      <div style={{ marginTop: '1rem', padding: '1.25rem', background: 'var(--neutral-0)', borderRadius: 'var(--radius)', boxShadow: 'var(--shadow-card)' }}>
        <h3 style={{ marginBottom: '1rem' }}>Summary</h3>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(160px, 1fr))', gap: '1rem' }}>
          <div style={kpiCell}>
            <div style={kpiLabel}>Total Use Cases</div>
            <div style={kpiValue}>{data.points.length}</div>
          </div>
          <div style={kpiCell}>
            <div style={kpiLabel}>Departments</div>
            <div style={kpiValue}>{uniqueDepts.length}</div>
          </div>
          <div style={kpiCell}>
            <div style={kpiLabel}>Average Score</div>
            <div style={kpiValue}>{avgScore.toFixed(1)}</div>
          </div>
          <div style={kpiCell}>
            <div style={kpiLabel}>Total Impact</div>
            <div style={kpiValue}>${totalImpact.toLocaleString()}</div>
          </div>
        </div>
      </div>
    </div>
  );

  const quadrantGrid = (
    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: '1rem' }}>
      {Object.entries(data.quadrants).map(([label, titles]) => (
        <div key={label} style={{ padding: '1rem', background: 'var(--neutral-50)', borderRadius: 'var(--radius)', borderLeft: '4px solid', borderColor: label === 'quick_win' ? 'var(--status-positive)' : label === 'major_project' ? 'var(--brand-500)' : label === 'fill_in' ? 'var(--status-warning)' : 'var(--status-negative)' }}>
          <strong style={{ textTransform: 'capitalize', display: 'block', marginBottom: '0.5rem' }}>
            {label === 'quick_win' ? '🚀 Quick Wins' : label === 'major_project' ? '🏗️ Major Projects' : label === 'fill_in' ? '✅ Fill-Ins' : '⚠️ Thankless Tasks'}
          </strong>
          {titles.length > 0 ? (
            <ul style={{ margin: 0, paddingLeft: '1.2rem', fontSize: '0.85rem', lineHeight: 1.5 }}>
              {titles.map((t, i) => <li key={i} style={{ marginBottom: '0.25rem' }}>{t}</li>)}
            </ul>
          ) : (
            <span style={{ color: 'var(--neutral-500)', fontSize: '0.85rem' }}>None</span>
          )}
        </div>
      ))}
    </div>
  );

  // Single-section blocks (customer analytics vertical stack)
  if (section === 'matrix') {
    return (
      <div style={{ marginBottom: '2rem' }}>
        <h2 style={{ margin: '0 0 1rem 0', color: 'var(--neutral-700)' }}>Business Impact Matrix</h2>
        {matrixContent}
      </div>
    );
  }
  if (section === 'quadrant') {
    return (
      <div style={{ marginBottom: '2rem' }}>
        <h2 style={{ margin: '0 0 1rem 0', color: 'var(--neutral-700)' }}>Quadrant Breakdown</h2>
        <div style={{ padding: '1rem', background: 'var(--neutral-0)', borderRadius: 'var(--radius)', boxShadow: 'var(--shadow-card)' }}>
          {quadrantGrid}
        </div>
      </div>
    );
  }

  return (
    <div style={{ marginBottom: '2rem' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1rem' }}>
        <h2 style={{ margin: 0, color: 'var(--neutral-700)' }}>Business Impact Matrix</h2>
        {onBack && (
          <button role="button" aria-label="Back to analytics" onClick={onBack} style={{ padding: '8px 16px', background: 'var(--neutral-500)', color: 'var(--neutral-0)', border: 'none', borderRadius: 'var(--radius)', cursor: 'pointer', fontSize: '0.85rem' }}>
            ← Back to Dashboard
          </button>
        )}
      </div>

      {matrixContent}

      {/* Quadrant breakdown */}
      {data.quadrants && (
        <div style={{ marginTop: '1.5rem', padding: '1rem', background: 'var(--neutral-0)', borderRadius: 'var(--radius)', boxShadow: 'var(--shadow-card)' }}>
          <h3 style={{ marginBottom: '1rem' }}>Quadrant Breakdown</h3>
          {quadrantGrid}
        </div>
      )}
    </div>
  );
}
export default ImpactMatrix;
