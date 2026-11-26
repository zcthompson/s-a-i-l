import { ActionButton } from './ActionButton';
import { SectionIcon } from './SectionIcon';
import { useEffect, useState } from 'react';
import { api } from '../lib/api';
import { getAuthIsAdmin } from '../lib/auth';
import { DepartmentTrend, AIPrediction, ReadinessInsightResponse } from '../types/use_case';
import { getDimensionAverages } from '../lib/dimensions';
import { RowActions } from './workspacePrimitives';
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  Legend,
} from 'recharts';

/**
 * Trend-prediction horizons for the customer analytics stack:
 * 30–60 days, 3–6 months, 6–12 months (midpoints in days).
 */
const PREDICTION_HORIZONS = [
  { days: 45, label: '30–60 days', sub: 'Short-term' },
  { days: 135, label: '3–6 months', sub: 'Medium-term' },
  { days: 270, label: '6–12 months', sub: 'Long-term' },
];

interface AnalyticsDashboardProps {
  onBack?: () => void;
  selectedCustomerId?: number | null;
  selectedCustomerName?: string;
  /**
   * Which part of the dashboard to render:
   * - 'all' (default): full standalone dashboard (deep-link view)
   * - 'trends': the Analytics Dashboard block (department trend analysis)
   * - 'correlation': the Readiness Insights block (id kept for URL stability)
   * - 'predictions': the multi-horizon Trend Predictions block
   */
  section?: 'all' | 'trends' | 'correlation' | 'predictions';
}

export function AnalyticsDashboard({ onBack, selectedCustomerId, section = 'all' }: AnalyticsDashboardProps) {
  const [deptTrends, setDeptTrends] = useState<DepartmentTrend[]>([]);
  const [readinessUseCases, setReadinessUseCases] = useState<any[]>([]);
  const [predictableUCs, setPredictableUCs] = useState<any[]>([]);
  const [selectedUCIds, setSelectedUCIds] = useState<Set<number>>(new Set());
  const [selectedHorizons, setSelectedHorizons] = useState<Set<number>>(new Set(PREDICTION_HORIZONS.map(h => h.days)));
  const [savedPredictions, setSavedPredictions] = useState<AIPrediction[]>([]);
  const [generating, setGenerating] = useState(false);
  const [predictionStatus, setPredictionStatus] = useState<string | null>(null);
  const [customerRoles, setCustomerRoles] = useState<Record<number, string>>({});
  const [allCustomers, setAllCustomers] = useState<{ id: number; name: string }[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Persisted, LLM-generated per-customer readiness insight (rendered
  // inside the Readiness Insights block, customer-scoped only). Insight
  // fetch/generation failures set insightStatus and never touch `error`.
  const [insightResponse, setInsightResponse] = useState<ReadinessInsightResponse | null>(null);
  const [insightGenerating, setInsightGenerating] = useState(false);
  const [insightStatus, setInsightStatus] = useState<string | null>(null);

  const wantsTrends = section === 'all' || section === 'trends';
  const wantsReadiness = section === 'all' || section === 'correlation';
  const wantsPredictions = section === 'all' || section === 'predictions';

  // Default to the passed customer ID (from customer dashboard)
  const [selectedCustomerIdState, setSelectedCustomerIdState] = useState<number | null>(selectedCustomerId ?? null);

  // Embedded mode: rendered inside a customer's Analytics tab — the parent
  // already shows the customer header, so the inner selector/back/header are
  // hidden and data is strictly scoped to that customer.
  const embedded = selectedCustomerId != null;

  useEffect(() => {
    if (embedded) return;
    loadCustomers();
  }, [embedded]);

  useEffect(() => {
    api.getMyCustomers()
      .then((customers) => setCustomerRoles(Object.fromEntries(
        customers.map((customer) => [customer.customer_id, customer.role]),
      )))
      .catch(() => setCustomerRoles({}));
  }, []);

  useEffect(() => {
    loadAnalytics();
  // eslint-disable-next-line react-hooks/exhaustive-deps -- pre-existing dependency list; change only with UI verification
  }, [selectedCustomerIdState, section]);

  const loadCustomers = async () => {
    try {
      const customers = await api.listCustomers();
      setAllCustomers(customers);
    } catch (err: any) {
      // Surface the failure — an empty selector is otherwise indistinguishable
      // from "no customers"
      setError(err.message || 'Failed to load customers.');
    }
  };

  const loadPredictions = async () => {
    try {
      // Offer the customer's scored use cases for prediction + list saved
      // model-generated predictions (persisted, viewable across sessions)
      const listParams: any = { status: '' };
      if (selectedCustomerIdState !== null) {
        listParams.customer_id = String(selectedCustomerIdState);
      }
      const allUseCases = await api.list(listParams);
      const scored = allUseCases
        .filter((uc: any) => uc.overall_score != null)
        .slice(0, 15);
      setPredictableUCs(scored);
      const saved = await api.savedPredictions(selectedCustomerIdState);
      setSavedPredictions(saved);
    } catch (err: any) {
      // Predictions are optional, but a load failure must not be silent
      setPredictionStatus(`Failed to load predictions: ${err.message || 'unknown error'} — use case selection may be incomplete.`);
    }
  };

  const toggleUC = (id: number) => setSelectedUCIds(prev => {
    const next = new Set(prev);
    if (next.has(id)) { next.delete(id); } else { next.add(id); }
    return next;
  });

  const toggleHorizon = (days: number) => setSelectedHorizons(prev => {
    const next = new Set(prev);
    if (next.has(days)) { next.delete(days); } else { next.add(days); }
    return next;
  });

  const handleGenerate = async () => {
    if (generating || selectedUCIds.size === 0 || selectedHorizons.size === 0) return;
    setGenerating(true);
    setPredictionStatus(null);
    const horizons = PREDICTION_HORIZONS.filter(h => selectedHorizons.has(h.days));
    const total = selectedUCIds.size * horizons.length;
    let done = 0;
    try {
      for (const ucId of Array.from(selectedUCIds)) {
        for (const h of horizons) {
          setPredictionStatus(`Generating… (${done + 1}/${total}) — the model is working, this can take a minute`);
          // F4(c): 300s cap PER prediction fetch (the N×M loop may
          // legitimately run longer than 300s in total — the cap guards
          // against one stalled model call, not the whole batch).
          const predictionController = new AbortController();
          const predictionTimer = setTimeout(() => predictionController.abort(), 300_000);
          try {
            await api.generatePrediction(ucId, h.days, predictionController.signal);
          } finally {
            clearTimeout(predictionTimer);
          }
          done += 1;
        }
      }
      const saved = await api.savedPredictions(selectedCustomerIdState);
      setSavedPredictions(saved);
      setPredictionStatus(`Done — ${total} prediction${total === 1 ? '' : 's'} generated by the model and saved below.`);
    } catch (err: any) {
      setPredictionStatus(`Generation failed: ${err.message || 'unknown error'} — earlier items in this batch may have been saved.`);
      const saved = await api.savedPredictions(selectedCustomerIdState).catch(() => null);
      if (saved) setSavedPredictions(saved);
    } finally {
      setGenerating(false);
    }
  };

  const handleGenerateInsight = async () => {
    if (insightGenerating || selectedCustomerIdState == null) return;
    setInsightGenerating(true);
    setInsightStatus('Generating… (the model is working, this can take a minute)');
    // 300s cap — mirrors the predictions loop's per-fetch AbortController.
    const insightController = new AbortController();
    const insightTimer = setTimeout(() => insightController.abort(), 300_000);
    try {
      await api.generateReadinessInsight(selectedCustomerIdState, insightController.signal);
      const refreshed = await api.readinessInsight(selectedCustomerIdState);
      setInsightResponse(refreshed);
      setInsightStatus('Readiness insight generated.');
    } catch (err: any) {
      setInsightStatus(`Generation failed: ${err?.message || 'unknown error'}`);
    } finally {
      clearTimeout(insightTimer);
      setInsightGenerating(false);
    }
  };

  const canDelete = (prediction: AIPrediction) =>
    getAuthIsAdmin() || (prediction.customer_id != null && customerRoles[prediction.customer_id] === 'owner');

  const handleDeletePrediction = async (prediction: AIPrediction) => {
    const title = prediction.use_case_title || `Use case #${prediction.use_case_id}`;
    if (!window.confirm(`Delete the saved prediction for ${title}? This cannot be undone.`)) return;
    try {
      await api.deletePrediction(prediction.id);
      setSavedPredictions((current) => current.filter((item) => item.id !== prediction.id));
      setPredictionStatus('Prediction deleted.');
    } catch (err: any) {
      setPredictionStatus(`Delete failed: ${err.message}`);
    }
  };

  const loadAnalytics = async () => {
    try {
      setLoading(true);
      setError(null);
      if (wantsTrends) {
        const deptData = await api.departmentTrends(selectedCustomerIdState);
        setDeptTrends(deptData);
      }
      if (wantsReadiness) {
        // Readiness Insights is computed client-side from the use case list
        // (bands + dimension profile) — no dedicated backend endpoint.
        const listParams: any = { status: '' };
        if (selectedCustomerIdState !== null) {
          listParams.customer_id = String(selectedCustomerIdState);
        }
        const readinessData = await api.list(listParams);
        setReadinessUseCases(readinessData);

        // The persisted LLM readiness insight is customer-scoped only. Its
        // own try/catch — a failure here must never break the deterministic
        // readiness block or set the page-level error.
        if (selectedCustomerIdState != null) {
          try {
            const insight = await api.readinessInsight(selectedCustomerIdState);
            setInsightResponse(insight);
            setInsightStatus(null);
          } catch (err: any) {
            setInsightResponse(null);
            setInsightStatus(`Failed to load readiness insight: ${err?.message || 'unknown error'}`);
          }
        } else {
          setInsightResponse(null);
          setInsightStatus(null);
        }
      }
      if (wantsPredictions) {
        await loadPredictions();
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load analytics');
    } finally {
      setLoading(false);
    }
  };

  // ── Section content (shared by standalone 'all' and single-section blocks) ──

  const trendsContent = deptTrends.length > 0 ? (
    <>
      <div style={{ marginBottom: '24px' }}>
        <h3 style={{ fontSize: '1rem', color: 'var(--neutral-500)', marginBottom: '12px' }}>Average Scores by Department</h3>
        <ResponsiveContainer width="100%" height={300}>
          <BarChart
            data={deptTrends}
            tabIndex={0}
            role="img"
            aria-label={`Bar chart of department trend analysis. Departments shown: ${deptTrends.map(d => `${d.department} at ${d.avg_score.toFixed(1)} average score`).join(', ')}.`}
          >
            <CartesianGrid strokeDasharray="3 3" stroke="var(--neutral-100)" />
            <XAxis dataKey="department" fontSize={11} tick={{ fill: 'var(--neutral-600)' }} />
            <YAxis domain={[0, 100]} fontSize={11} tick={{ fill: 'var(--neutral-600)' }} />
            <Tooltip formatter={(value: number) => value.toFixed(1)} wrapperStyle={{ fontSize: '12px' }} contentStyle={{ background: 'var(--neutral-0)', border: '1px solid var(--divider)' }} labelStyle={{ color: 'var(--ink)' }} itemStyle={{ color: 'var(--ink)' }} />
            <Legend wrapperStyle={{ fontSize: '12px' }} aria-label="Chart legend" />
            <Bar dataKey="avg_score" fill="var(--brand-500)" name="Avg Score" />
          </BarChart>
        </ResponsiveContainer>
      </div>
      <div role="region" aria-label="Department trend data" tabIndex={0} style={{ overflowX: 'auto' }}>
        <table style={{ width: '100%', borderCollapse: 'collapse' }}>
          <thead>
            <tr>
              <th style={{ textAlign: 'left', padding: '12px 8px', fontWeight: 600, borderBottom: '2px solid var(--divider)', color: 'var(--neutral-700)' }}>Department</th>
              <th style={{ textAlign: 'left', padding: '12px 8px', fontWeight: 600, borderBottom: '2px solid var(--divider)', color: 'var(--neutral-700)' }}>Use Cases</th>
              <th style={{ textAlign: 'left', padding: '12px 8px', fontWeight: 600, borderBottom: '2px solid var(--divider)', color: 'var(--neutral-700)' }}>Avg Score</th>
              <th style={{ textAlign: 'left', padding: '12px 8px', fontWeight: 600, borderBottom: '2px solid var(--divider)', color: 'var(--neutral-700)' }}>Total Impact</th>
            </tr>
          </thead>
          <tbody>
            {deptTrends.map((dept) => (
              <tr key={dept.department}>
                <td style={{ padding: '12px 8px', borderBottom: '1px solid var(--divider)' }}>
                  <strong>{dept.department}</strong>
                </td>
                <td style={{ padding: '12px 8px', borderBottom: '1px solid var(--divider)' }}>{dept.use_case_count}</td>
                <td style={{ padding: '12px 8px', borderBottom: '1px solid var(--divider)' }}>
                  <span style={{
                    fontWeight: 'bold',
                    color: dept.avg_score >= 70 ? 'var(--score-high)' : dept.avg_score >= 35 ? 'var(--score-mid)' : 'var(--score-low)'
                  }}>
                    {dept.avg_score.toFixed(1)}
                  </span>
                </td>
                <td style={{ padding: '12px 8px', borderBottom: '1px solid var(--divider)' }}>
                  ${dept.total_impact.toLocaleString()}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  ) : (
    <p style={{ color: 'var(--neutral-500)', textAlign: 'center', padding: '2rem' }}>No department data available</p>
  );

  // ── Readiness Insights (client-side, deterministic — no LLM, no backend) ──

  const impactOf = (uc: any) => (uc.estimated_savings || 0) + (uc.estimated_revenue || 0);

  const readinessBandDefs = [
    { key: 'high', label: 'Strong (70+)', color: 'var(--score-high)', test: (s: number | null) => s != null && s >= 70 },
    { key: 'mid', label: 'Moderate (35–69)', color: 'var(--score-mid)', test: (s: number | null) => s != null && s >= 35 && s < 70 },
    { key: 'low', label: 'Weak (<35)', color: 'var(--score-low)', test: (s: number | null) => s != null && s < 35 },
    { key: 'unscored', label: 'Unscored', color: 'var(--score-unscored)', test: (s: number | null) => s == null },
  ];

  const readinessInScopeCount = readinessUseCases.length;
  const readinessTotalImpact = readinessUseCases.reduce((sum, uc) => sum + impactOf(uc), 0);
  const readinessBands = readinessBandDefs.map((band) => {
    const items = readinessUseCases.filter((uc) => band.test(uc.overall_score ?? null));
    const impact = items.reduce((sum, uc) => sum + impactOf(uc), 0);
    return {
      ...band,
      count: items.length,
      pctCount: readinessInScopeCount > 0 ? (items.length / readinessInScopeCount) * 100 : 0,
      impact,
      pctImpact: readinessTotalImpact > 0 ? (impact / readinessTotalImpact) * 100 : 0,
    };
  });

  const dimensionAverages = getDimensionAverages(readinessUseCases);
  const dimensionsBelowTarget = dimensionAverages.filter((d) => d.average != null && d.average < 70);
  const weakestDimension = dimensionsBelowTarget.length > 0
    ? dimensionsBelowTarget.reduce((lowest, d) => (d.average! < lowest.average! ? d : lowest))
    : null;

  const scoredUseCases = readinessUseCases.filter((uc) => uc.overall_score != null);
  const lowUseCases = readinessUseCases.filter((uc) => uc.overall_score != null && uc.overall_score < 35);
  const lowImpact = lowUseCases.reduce((sum, uc) => sum + impactOf(uc), 0);
  const lowImpactPct = readinessTotalImpact > 0 ? (lowImpact / readinessTotalImpact) * 100 : 0;

  let readinessSoWhat: string;
  if (readinessInScopeCount === 0) {
    readinessSoWhat = 'No use cases in scope.';
  } else if (scoredUseCases.length === 0) {
    readinessSoWhat = 'No scored use cases in scope yet — run a scoring pass to populate readiness insights.';
  } else {
    const clauses: string[] = [];
    if (lowUseCases.length > 0) {
      clauses.push(`${lowUseCases.length} of ${scoredUseCases.length} scored use cases score under 35 — ${lowImpactPct.toFixed(0)}% of their total impact`);
    }
    if (weakestDimension) {
      clauses.push(`weakest dimension: ${weakestDimension.name} (avg ${weakestDimension.average!.toFixed(1)})`);
    }
    readinessSoWhat = clauses.length > 0
      ? clauses.join(' · ')
      : `${scoredUseCases.length} of ${readinessInScopeCount} use cases scored — no dimension below target 70`;
  }

  // ── Readiness Insight panel (customer-scoped only) ──────────────
  const insight = insightResponse?.insight ?? null;
  const insightStateData = insightResponse?.state ?? null;
  const insightStale = insightResponse?.stale === true;
  const insightFailed = insightStatus != null
    && (insightStatus.startsWith('Generation failed') || insightStatus.startsWith('Failed to load'));

  // Enabled when the loaded state says so; when the state itself failed to
  // load, fall back to the already-loaded use case list.
  const fallbackGeneratable = readinessUseCases.some(
    (uc) => uc.overall_score != null && uc.status === 'completed',
  );
  const canGenerateInsight = insightStateData ? insightStateData.ready : fallbackGeneratable;

  const insightStatusEl = insightStatus ? (
    <div role={insightFailed ? 'alert' : 'status'} aria-live="polite"
      style={{ marginTop: '10px', fontSize: '0.85rem', color: insightFailed ? 'var(--status-negative)' : 'var(--brand-500)' }}>
      {insightStatus}
    </div>
  ) : null;

  const insightActionButton = (label: string, enabled: boolean) => (
    <ActionButton busy={insightGenerating} role="button" aria-label={`${label}`}
      onClick={handleGenerateInsight}
      disabled={insightGenerating || !enabled} style={{ marginTop: 12 }}
    >
      {label}
    </ActionButton>
  );

  const insightColumns: Array<{ key: string; label: string; items: string[]; marker: string; ordered: boolean }> = insight ? [
    { key: 'strengths', label: 'Strengths', items: insight.insight_data.strengths, marker: 'var(--status-positive)', ordered: false },
    { key: 'weaknesses', label: 'Watch items', items: insight.insight_data.weaknesses, marker: 'var(--status-warning)', ordered: false },
    { key: 'priorities', label: 'Priorities', items: insight.insight_data.priorities, marker: 'var(--brand-500)', ordered: true },
  ] : [];

  const insightPanel = selectedCustomerIdState == null ? null : (
    <div style={{ marginBottom: '24px' }}>
      {insight != null ? (
        <div style={{ background: 'var(--neutral-0)', border: '1px solid var(--divider)', borderRadius: 'var(--radius)', padding: '20px' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', gap: '12px', flexWrap: 'wrap', marginBottom: '10px' }}>
            <span style={{ fontSize: '1rem', color: 'var(--neutral-700)', fontWeight: 600 }}>Readiness Insight</span>
            <span style={{ fontSize: '0.75rem', color: 'var(--neutral-500)' }}>
              Generated {new Date(insight.generated_at as string).toLocaleString()} · {insight.model || 'AI model'}
            </span>
          </div>
          <p style={{ fontSize: '0.9rem', color: 'var(--neutral-600)', lineHeight: 1.5, margin: '0 0 16px 0' }}>
            {insight.insight_data.summary}
          </p>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: '16px' }}>
            {insightColumns.map((col) => (
              <div key={col.key}>
                <div style={{ fontSize: '0.85rem', fontWeight: 600, color: 'var(--neutral-700)', marginBottom: '6px' }}>{col.label}</div>
                <ul style={{ margin: 0, padding: 0, listStyle: 'none', display: 'grid', gap: '4px' }}>
                  {col.items.map((item, i) => (
                    <li key={i} style={{ fontSize: '0.85rem', color: 'var(--neutral-700)', display: 'flex', gap: '6px' }}>
                      <span aria-hidden="true" style={{ color: col.marker, fontWeight: 700 }}>{col.ordered ? `${i + 1}.` : '•'}</span>
                      <span>{item}</span>
                    </li>
                  ))}
                </ul>
              </div>
            ))}
          </div>
          {insight.insight_data.missing_note != null && (
            <div role="note" style={{ background: 'var(--status-warning-soft)', fontSize: '0.8rem', color: 'var(--neutral-700)', padding: '8px 12px', borderRadius: 'var(--radius-sm)', marginTop: '12px' }}>
              {insight.insight_data.missing_note}
            </div>
          )}
          {insightStale && (
            <div style={{ fontSize: '0.8rem', color: 'var(--neutral-500)', marginTop: '12px' }}>
              Scores have changed since this insight was generated — regenerate to refresh.
            </div>
          )}
          {insightActionButton('Regenerate insight', true)}
          {insightStatusEl}
        </div>
      ) : (
        <div style={{ background: 'var(--neutral-50)', padding: '12px 16px', borderRadius: 'var(--radius-sm)', color: 'var(--neutral-600)', fontSize: '0.85rem' }}>
          <div>No readiness insight yet — it is generated by the AI model after scoring completes for this customer.</div>
          {insightActionButton('Generate readiness insight', canGenerateInsight)}
          {!canGenerateInsight && insightStateData != null && (
            <div style={{ fontSize: '0.78rem', color: 'var(--neutral-500)', marginTop: '6px' }}>
              {insightStateData.total === 0
                ? 'No use cases yet'
                : `${insightStateData.total - insightStateData.included} of ${insightStateData.total} use cases are still unscored or not completed`}
            </div>
          )}
          {insightStatusEl}
        </div>
      )}
    </div>
  );

  const readinessContent = readinessInScopeCount === 0 ? (
    <p style={{ color: 'var(--neutral-500)', textAlign: 'center', padding: '2rem' }}>No use cases in scope.</p>
  ) : (
    <div>
      <div style={{ background: 'var(--neutral-50)', padding: '12px 16px', borderRadius: 'var(--radius-sm)', color: 'var(--neutral-600)', fontSize: '0.85rem', marginBottom: '20px' }}>
        {readinessSoWhat}
      </div>

      {insightPanel}

      <h3 style={{ fontSize: '1rem', color: 'var(--neutral-700)', margin: '0 0 12px 0' }}>Organization Use Case Readiness</h3>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(160px, 1fr))', gap: '12px', marginBottom: '16px' }}>
        {readinessBands.map((band) => (
          <div key={band.key} style={{ padding: '14px', borderRadius: 'var(--radius)', borderLeft: `4px solid ${band.color}`, background: 'var(--neutral-0)' }}>
            <div style={{ fontSize: '1.6rem', fontWeight: 'bold', color: band.color }}>{band.count}</div>
            <div style={{ fontSize: '0.85rem', color: 'var(--neutral-700)', fontWeight: 600 }}>{band.label}</div>
            <div style={{ fontSize: '0.78rem', color: 'var(--neutral-500)', marginTop: '2px' }}>{band.pctCount.toFixed(0)}% of use cases</div>
          </div>
        ))}
      </div>
      <div role="region" aria-label="Readiness band data" tabIndex={0} style={{ overflowX: 'auto', marginBottom: '28px' }}>
        <table style={{ width: '100%', borderCollapse: 'collapse' }}>
          <thead>
            <tr>
              {['Band', 'Use cases', '% of use cases', 'Total impact', '% of impact'].map((h) => (
                <th key={h} style={{ textAlign: 'left', padding: '12px 8px', fontWeight: 600, borderBottom: '2px solid var(--divider)', color: 'var(--neutral-700)' }}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {readinessBands.map((band) => (
              <tr key={band.key}>
                <td style={{ padding: '12px 8px', borderBottom: '1px solid var(--divider)' }}>
                  <span style={{ display: 'inline-block', width: '10px', height: '10px', borderRadius: 'var(--radius-pill)', background: band.color, marginRight: '8px' }} />
                  <strong>{band.label}</strong>
                </td>
                <td style={{ padding: '12px 8px', borderBottom: '1px solid var(--divider)' }}>{band.count}</td>
                <td style={{ padding: '12px 8px', borderBottom: '1px solid var(--divider)' }}>{band.pctCount.toFixed(1)}%</td>
                <td style={{ padding: '12px 8px', borderBottom: '1px solid var(--divider)' }}>${band.impact.toLocaleString()}</td>
                <td style={{ padding: '12px 8px', borderBottom: '1px solid var(--divider)' }}>{band.pctImpact.toFixed(1)}%</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <h3 style={{ fontSize: '1rem', color: 'var(--neutral-700)', margin: '0 0 12px 0' }}>Dimension readiness profile</h3>
      <div style={{ display: 'grid', gap: '10px' }}>
        {dimensionAverages.map((dim) => {
          const isWeakest = weakestDimension != null && dim.name === weakestDimension.name;
          const hasData = dim.average != null;
          return (
            <div key={dim.name} data-ui="dimension-profile-row" style={{ display: 'grid', alignItems: 'center', gap: '12px', fontSize: '0.85rem', minWidth: 0 }}>
              <span style={{ color: 'var(--neutral-700)', fontWeight: 600, overflowWrap: 'anywhere' }}>{dim.name}</span>
              <div style={{ background: 'var(--neutral-100)', borderRadius: 'var(--radius-pill)', height: '12px', overflow: 'hidden' }}>
                <div style={{
                  width: hasData ? `${Math.max(0, Math.min(100, dim.average!))}%` : '0%',
                  height: '100%',
                  background: isWeakest ? 'var(--status-negative)' : 'var(--brand-500)',
                }} />
              </div>
              <span style={{ color: 'var(--neutral-600)', textAlign: 'right' }}>
                {hasData ? (
                  <>
                    {dim.average!.toFixed(1)}
                    {dim.average! < 70 && (
                      <span style={{ color: 'var(--neutral-500)', display: 'block', fontSize: '0.75rem' }}>
                        −{(70 - dim.average!).toFixed(1)} vs target 70
                      </span>
                    )}
                  </>
                ) : (
                  <span style={{ color: 'var(--neutral-500)' }}>no data</span>
                )}
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );

  const predictionsContent = (
    <>
      <p style={{ color: 'var(--neutral-500)', marginBottom: '16px' }}>
        Readiness forecasts generated by the AI model (score history → model endpoint).
        Select use cases and horizons, then generate — results are saved and stay viewable below.
      </p>

      <div style={{ background: 'var(--neutral-0)', borderRadius: 'var(--radius)', padding: '16px', marginBottom: '20px' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '8px' }}>
          <strong style={{ fontSize: '0.95rem', color: 'var(--ink)' }}>Use cases (scored)</strong>
          <span style={{ fontSize: '0.8rem', color: 'var(--neutral-500)' }}>{selectedUCIds.size} selected</span>
        </div>
        {predictableUCs.length === 0 ? (
          <p style={{ color: 'var(--neutral-500)', margin: 0, fontSize: '0.9rem' }}>No scored use cases available.</p>
        ) : (
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(min(220px, 100%), 1fr))', gap: '6px', maxHeight: '220px', overflowY: 'auto' }}>
            {predictableUCs.map((uc: any) => (
              <label key={uc.id} style={{ display: 'flex', gap: '8px', alignItems: 'center', fontSize: '0.85rem', color: 'var(--neutral-700)', cursor: 'pointer' }}>
                <input type="checkbox" checked={selectedUCIds.has(uc.id)} onChange={() => toggleUC(uc.id)} style={{ cursor: 'pointer' }} />
                <span style={{ flex: 1, minWidth: 0, overflowWrap: 'anywhere' }}>{uc.title}</span>
                <span style={{ color: 'var(--neutral-500)' }}>{uc.overall_score.toFixed(0)}</span>
              </label>
            ))}
          </div>
        )}
        <div style={{ marginTop: '14px', display: 'flex', gap: '16px', alignItems: 'center', flexWrap: 'wrap' }}>
          <strong style={{ fontSize: '0.95rem', color: 'var(--ink)' }}>Horizons:</strong>
          {PREDICTION_HORIZONS.map((h) => (
            <label key={h.days} style={{ display: 'flex', gap: '6px', alignItems: 'center', fontSize: '0.85rem', color: 'var(--neutral-700)', cursor: 'pointer' }}>
              <input type="checkbox" checked={selectedHorizons.has(h.days)} onChange={() => toggleHorizon(h.days)} style={{ cursor: 'pointer' }} />
              {h.label} ({h.days}d)
            </label>
          ))}
        </div>
        {/* UX audit #6: the button was disabled with no explanation of why —
            a prominent disabled action reads as a bug. Surface the actual
            precondition (select use cases / horizons) in title + aria. */}
        {(() => {
          const genDisabled = generating || selectedUCIds.size === 0 || selectedHorizons.size === 0;
          const genReason = generating
            ? 'Generating predictions…'
            : selectedUCIds.size === 0
              ? 'Select one or more use cases to generate predictions'
              : 'Select one or more prediction horizons to generate predictions';
          return (
            <>
              <ActionButton busy={generating} role="button"
                aria-label={genDisabled ? genReason : 'Generate AI predictions'}
                title={genDisabled ? genReason : 'Generate AI predictions from the selected use cases'}
                onClick={handleGenerate}
                disabled={genDisabled} style={{ marginTop: 14 }}
              >
                Generate AI Predictions
              </ActionButton>
            </>
          );
        })()}
        {predictionStatus && (
          <div role={predictionStatus.startsWith('Generation failed') ? 'alert' : 'status'} aria-live="polite"
            style={{ marginTop: '10px', fontSize: '0.85rem', color: predictionStatus.startsWith('Generation failed') ? 'var(--status-negative)' : 'var(--brand-500)' }}>
            {predictionStatus}
          </div>
        )}
      </div>

      <h3 style={{ fontSize: '1rem', color: 'var(--neutral-700)', margin: '0 0 12px 0' }}>Saved Predictions ({savedPredictions.length})</h3>
      {savedPredictions.length === 0 ? (
        <p style={{ color: 'var(--neutral-500)', margin: 0 }}>No saved predictions yet — generate some above.</p>
      ) : (
        <div style={{ display: 'grid', gap: '12px' }}>
          {savedPredictions.map((pred) => (
            <div key={pred.id} style={{ padding: '16px', background: 'var(--neutral-0)', borderRadius: 'var(--radius)', minWidth: 0, overflowWrap: 'anywhere' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '8px', flexWrap: 'wrap', gap: '8px' }}>
                <strong style={{ color: 'var(--ink)' }}>{pred.use_case_title || `Use case #${pred.use_case_id}`}</strong>
                <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                  <span style={{ fontSize: '0.8rem', color: 'var(--neutral-500)' }}>
                    {PREDICTION_HORIZONS.find(h => h.days === pred.horizon_days)?.label ?? `${pred.horizon_days} days`}
                  </span>
                  {canDelete(pred) && (
                    // per-row overflow menu instead
                    // of a repetitive Delete button; handleDeletePrediction
                    // keeps its confirmation flow.
                    <RowActions
                      ariaLabel={`Actions for prediction ${pred.use_case_title || pred.use_case_id}`}
                      items={[{
                        label: 'Delete prediction',
                        onClick: () => handleDeletePrediction(pred),
                        destructive: true,
                      }]}
                    />
                  )}
                </div>
              </div>
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(min(100px, 100%), 1fr))', gap: '12px' }}>
                <div>
                  <div style={{ fontSize: '0.8rem', color: 'var(--neutral-500)', marginBottom: '4px' }}>Predicted Score</div>
                  <div style={{ fontSize: '1.2rem', fontWeight: 'bold', color: 'var(--brand-700)' }}>{pred.predicted_score?.toFixed(1)}</div>
                </div>
                <div>
                  <div style={{ fontSize: '0.8rem', color: 'var(--neutral-500)', marginBottom: '4px' }}>Change</div>
                  <div style={{ fontSize: '1.2rem', fontWeight: 'bold', color: (pred.score_change || 0) > 0 ? 'var(--status-positive)' : (pred.score_change || 0) < 0 ? 'var(--status-negative)' : 'var(--neutral-500)' }}>
                    {pred.score_change != null ? `${pred.score_change > 0 ? '+' : ''}${pred.score_change.toFixed(1)}` : '—'}
                  </div>
                </div>
                <div>
                  <div style={{ fontSize: '0.8rem', color: 'var(--neutral-500)', marginBottom: '4px' }}>Trend / Confidence</div>
                  <div style={{ fontSize: '0.95rem', fontWeight: 600 }}>
                    {pred.trend === 'improving' ? '↑ Improving' : pred.trend === 'declining' ? '↓ Declining' : '→ Stable'}
                    {pred.confidence != null && <span style={{ color: 'var(--neutral-500)', fontWeight: 400 }}> ({Math.round(pred.confidence * 100)}%)</span>}
                  </div>
                </div>
              </div>
              {pred.reasoning && (
                <div style={{ marginTop: '10px', fontSize: '0.85rem', color: 'var(--neutral-500)', lineHeight: 1.5 }}>{pred.reasoning}</div>
              )}
              <div style={{ marginTop: '8px', fontSize: '0.75rem', color: 'var(--neutral-500)' }}>
                {pred.model} · {pred.created_at ? new Date(pred.created_at).toLocaleString() : '—'}{pred.created_by ? ` · by ${pred.created_by}` : ''}
              </div>
            </div>
          ))}
        </div>
      )}
    </>
  );

  const cardStyle: React.CSSProperties = {
    padding: '24px',
    minWidth: 0,
    background: 'var(--neutral-0)',
    borderRadius: 'var(--radius)',
    border: '1px solid var(--divider)',
    marginBottom: '24px',
  };

  if (loading) return <div role="status" aria-live="polite" style={{ padding: '40px', textAlign: 'center', color: 'var(--neutral-500)' }}>Loading dashboard...</div>;
  if (error) return <div role="alert" aria-live="assertive" style={{ padding: '16px', background: 'var(--status-negative-soft)', borderLeft: '4px solid var(--status-negative)', borderRadius: 'var(--radius-sm)', color: 'var(--status-negative)', marginBottom: '24px' }}>
    <span aria-hidden="true">⚠️ </span>{error}
    <button role="button" aria-label="Retry loading analytics" onClick={loadAnalytics} style={{ marginLeft: '12px', padding: '6px 12px', border: '1px solid var(--status-negative)', borderRadius: 'var(--radius-sm)', background: 'var(--neutral-0)', color: 'var(--status-negative)', cursor: 'pointer', fontWeight: 600 }}>Retry</button>
  </div>;

  // Single-section blocks (customer analytics vertical stack)
  if (section === 'trends') {
    return (
      <div style={cardStyle}>
        <h2 style={{ marginBottom: '16px', fontSize: '1.2rem', color: 'var(--neutral-700)' }}><SectionIcon name="📊" /> Analytics Dashboard</h2>
        {trendsContent}
      </div>
    );
  }
  if (section === 'correlation') {
    return (
      <div style={cardStyle}>
        <h2 style={{ marginBottom: '16px', fontSize: '1.2rem', color: 'var(--neutral-700)' }}><SectionIcon name="🧭" /> Readiness Insights</h2>
        {readinessContent}
      </div>
    );
  }
  if (section === 'predictions') {
    return (
      <div style={cardStyle}>
        <h2 style={{ marginBottom: '16px', fontSize: '1.2rem', color: 'var(--neutral-700)' }}><SectionIcon name="📊" /> Trend Predictions</h2>
        {predictionsContent}
      </div>
    );
  }

  // Standalone full dashboard (deep-link views)
  return (
    <div style={{ padding: embedded ? '0' : '24px', maxWidth: '1400px', margin: '0 auto' }}>
      {/* Header (global view only; the in-customer tab is scoped by its parent) */}
      {!embedded && (
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: '12px', justifyContent: 'space-between', alignItems: 'center', marginBottom: '24px' }}>
          <div>
            <h1 style={{ margin: '0 0 4px 0', fontSize: '1.8rem', color: 'var(--ink)' }}><SectionIcon name="📊" /> Analytics Dashboard</h1>
            <p style={{ margin: 0, color: 'var(--neutral-500)', fontSize: '0.95rem' }}>Department trends, readiness insights, and trend predictions</p>
          </div>
          <div style={{ display: 'flex', gap: '12px', alignItems: 'center' }}>
            <select aria-label="Analytics Dashboard selection"
              style={{ padding: '8px 12px', border: '1px solid var(--divider)', borderRadius: 'var(--radius)', fontSize: '0.9rem', background: 'var(--neutral-0)', color: 'var(--ink)', maxWidth: '100%' }}
              value={selectedCustomerIdState?.toString() ?? 'all'}
              onChange={(e) => setSelectedCustomerIdState(e.target.value === 'all' ? null : Number(e.target.value))}
            >
              <option value="all">My Customers</option>
              {allCustomers.map(c => (
                <option key={c.id} value={c.id}>{c.name}</option>
              ))}
            </select>
            {onBack && (
              <ActionButton variant="quiet" role="button" aria-label="Back to analytics"
                onClick={onBack}
              >
                ← Back
              </ActionButton>
            )}
          </div>
        </div>
      )}

      {/* Section 1: Department Trends */}
      <div style={cardStyle}>
        <h2 style={{ marginBottom: '16px', fontSize: '1.2rem', color: 'var(--neutral-700)' }}><SectionIcon name="📊" /> Department Trend Analysis</h2>
        {trendsContent}
      </div>

      {/* Section 2: Readiness Insights */}
      <div style={cardStyle}>
        <h2 style={{ marginBottom: '16px', fontSize: '1.2rem', color: 'var(--neutral-700)' }}><SectionIcon name="🧭" /> Readiness Insights</h2>
        {readinessContent}
      </div>

      {/* Section 3: Trend Predictions (multi-horizon) */}
      <div style={cardStyle}>
        <h2 style={{ marginBottom: '16px', fontSize: '1.2rem', color: 'var(--neutral-700)' }}><SectionIcon name="📊" /> Trend Predictions</h2>
        {predictionsContent}
      </div>
    </div>
  );
}
export default AnalyticsDashboard;
