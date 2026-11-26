/**
 * CustomerProjections.tsx - Business Impact Forecasting for a customer
 *
 * Shows:
 * - Speed and Value axes with current/projected scores over the chosen timeline
 * - Trajectory indicators (improving/stable/declining)
 * - Key factors driving the projection (always derived from the customer's
 *   own use case + business impact data)
 * - Actionable recommendations (model-refined when available)
 * - Confidence score
 *
 * Timeline is a single-select (30–60 days / 3–6 months / 6–12 months) —
 * one projection runs for one timeline, mirroring the analytics trend
 * prediction horizons.
 */

import React, { useState, useEffect } from 'react';
import { api } from '../lib/api';
import type { Projection } from '../types/use_case';

interface CustomerProjectionsProps {
  customerName: string;
  customerId: number;
  userRole: string; // 'owner' | 'member' | 'auditor'
}

// Selectable timelines (single-select). Mirrors the analytics
// trend-prediction horizon options; only one can be run at a time.
const TIMELINES = [
  { id: '30-60d', label: '30–60 days' },
  { id: '3-6m', label: '3–6 months' },
  { id: '6-12m', label: '6–12 months' },
] as const;

type TimelineId = (typeof TIMELINES)[number]['id'];

const cardStyle: React.CSSProperties = {
  background: 'var(--neutral-0)',
  borderRadius: 'var(--radius)',
  padding: '20px',
  boxShadow: 'var(--shadow-card)',
};

// Normalize an axis, tolerating legacy payloads that use projected_30d.
const normalizeAxis = (a: any) => ({
  current: Number(a?.current ?? 0),
  projected: Number(a?.projected ?? a?.projected_30d ?? a?.current ?? 0),
  trajectory: typeof a?.trajectory === 'string' ? a.trajectory : 'stable',
});

// Normalize a raw API payload (bare or wrapped in projection_data).
const normalizeProjection = (raw: any): Projection | null => {
  const data = raw?.projection_data ?? raw;
  if (!data || !data.speed || !data.value) {
    return null;
  }
  return {
    ...data,
    speed: normalizeAxis(data.speed),
    value: normalizeAxis(data.value),
    key_factors: Array.isArray(data.key_factors) ? data.key_factors : [],
    recommendations: Array.isArray(data.recommendations) ? data.recommendations : [],
  };
};

export const CustomerProjections: React.FC<CustomerProjectionsProps> = ({
  customerName,
  customerId: _customerId,
  userRole,
}) => {
  const [projection, setProjection] = useState<Projection | null>(null);
  const [loading, setLoading] = useState(true);
  const [generating, setGenerating] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selectedTimeline, setSelectedTimeline] = useState<TimelineId>('30-60d');

  const isAdmin = userRole === 'owner';

  const timelineLabel =
    TIMELINES.find((t) => t.id === projection?.horizon)?.label ??
    TIMELINES.find((t) => t.id === selectedTimeline)?.label ??
    TIMELINES[0].label;

  const loadProjection = async () => {
    try {
      setLoading(true);
      setError(null);
      try {
        const raw: any = await api.getProjection(customerName);
        const data = normalizeProjection(raw);
        setProjection(data);
      } catch {
        // No projection exists yet
        setProjection(null);
      }
    } catch (err: any) {
      setError(err.message || 'Failed to load projections');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadProjection();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [customerName]);

  const handleGenerate = async () => {
    try {
      setGenerating(true);
      setError(null);
      // WP23a F4(c): 300s cap on the projection fetch (client-side — the
      // model may keep running on the server; the abort message says so).
      const controller = new AbortController();
      const timer = setTimeout(() => controller.abort(), 300_000);
      try {
        const raw: any = await api.generateProjection(customerName, selectedTimeline, controller.signal);
        const data = normalizeProjection(raw);
        setProjection(data);
      } finally {
        clearTimeout(timer);
      }
    } catch (err: any) {
      setError(err.message || 'Failed to generate projection');
    } finally {
      setGenerating(false);
    }
  };

  const handleClear = async () => {
    try {
      await api.clearProjection(customerName);
      setProjection(null);
    } catch (err: any) {
      setError(err.message || 'Failed to clear projection');
    }
  };

  const TrajectoryIcon = ({ trajectory }: { trajectory: string }) => {
    switch (trajectory) {
      case 'improving':
        return '↑';
      case 'declining':
        return '↓';
      case 'stable':
      default:
        return '→';
    }
  };

  const TrajectoryColor = ({ trajectory }: { trajectory: string }) => {
    switch (trajectory) {
      case 'improving':
        return 'var(--status-positive)';
      case 'declining':
        return 'var(--status-negative)';
      case 'stable':
      default:
        return 'var(--status-warning)';
    }
  };

  const AxisCard: React.FC<{ title: string; emoji: string; axis: Projection['speed'] }> = ({
    title,
    emoji,
    axis,
  }) => (
    <div style={cardStyle}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '16px' }}>
        <h3 style={{ margin: 0, fontSize: '1.1rem', color: 'var(--neutral-700)' }}>{emoji} {title}</h3>
        <span style={{ fontSize: '1.5rem', color: TrajectoryColor({ trajectory: axis.trajectory }), fontWeight: 'bold' }}>
          <TrajectoryIcon trajectory={axis.trajectory} />
        </span>
      </div>

      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-end', marginBottom: '8px' }}>
        <div>
          <div style={{ fontSize: '0.75rem', color: 'var(--neutral-500)', marginBottom: '2px' }}>Current</div>
          <div style={{ fontSize: '2rem', fontWeight: 'bold', color: 'var(--ink)' }}>{axis.current}</div>
        </div>
        <div style={{ fontSize: '1.5rem', color: 'var(--neutral-500)' }}>→</div>
        <div>
          <div style={{ fontSize: '0.75rem', color: 'var(--neutral-500)', marginBottom: '2px' }}>{timelineLabel}</div>
          <div style={{ fontSize: '2rem', fontWeight: 'bold', color: 'var(--brand-700)' }}>{axis.projected}</div>
        </div>
      </div>

      <div style={{ marginTop: '12px' }}>
        <div
          style={{
            height: '8px',
            background: 'var(--neutral-100)',
            borderRadius: 'var(--radius-sm)',
            overflow: 'hidden',
            position: 'relative',
          }}
        >
          <div
            style={{
              width: `${axis.current}%`,
              height: '100%',
              background: 'var(--neutral-400)',
              borderRadius: 'var(--radius-sm)',
              transition: 'width 0.3s',
            }}
          />
          <div
            style={{
              width: `${Math.max(0, axis.projected - axis.current) || 0}%`,
              height: '100%',
              background: 'var(--brand-500)',
              borderRadius: 'var(--radius-sm)',
              marginLeft: `${axis.current}%`,
              transition: 'all 0.3s',
            }}
          />
        </div>
      </div>

      <div
        style={{
          marginTop: '8px',
          fontSize: '0.85rem',
          color: TrajectoryColor({ trajectory: axis.trajectory }),
          fontWeight: 600,
        }}
      >
        Trajectory: {axis.trajectory.charAt(0).toUpperCase() + axis.trajectory.slice(1)}
      </div>
    </div>
  );

  if (loading) {
    return (
      <div style={{ padding: '40px', textAlign: 'center', color: 'var(--neutral-500)' }}>
        Loading projections...
      </div>
    );
  }

  if (error) {
    return (
      <div style={{ padding: '20px', background: 'var(--status-negative-soft)', borderRadius: 'var(--radius)', color: 'var(--status-negative)' }}>
        <strong>Error:</strong> {error}
        <br />
        <button
          role="button"
          aria-label="Retry loading projections"
          onClick={loadProjection}
          style={{ marginTop: '10px', padding: '6px 12px', background: 'var(--status-negative)', color: 'var(--neutral-0)', border: 'none', borderRadius: 'var(--radius-sm)', cursor: 'pointer' }}
        >
          Retry
        </button>
      </div>
    );
  }

  return (
    <div>
      {/* Header */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '16px', flexWrap: 'wrap', gap: '12px' }}>
        <div>
          <h2 style={{ margin: 0, fontSize: '1.3rem', color: 'var(--ink)' }}>🔮 Business Impact Forecasting</h2>
          <p style={{ margin: '4px 0 0', color: 'var(--neutral-500)', fontSize: '0.9rem' }}>
            {timelineLabel} forecasts based on current use cases and business impact
          </p>
        </div>
        {isAdmin && (
          <div style={{ display: 'flex', gap: '8px' }}>
            {projection && (
              <button
                role="button"
                aria-label="Clear projection"
                onClick={handleClear}
                style={{ padding: '8px 16px', background: 'var(--status-negative)', color: 'var(--neutral-0)', border: 'none', borderRadius: 'var(--radius)', cursor: 'pointer', fontSize: '0.85rem' }}
              >
                Clear
              </button>
            )}
            <button
              role="button"
              aria-label="Generate business impact projection"
              onClick={handleGenerate}
              disabled={generating}
              style={{
                padding: '8px 16px',
                background: generating ? 'var(--neutral-400)' : 'var(--brand-500)',
                color: 'var(--neutral-0)',
                border: 'none',
                borderRadius: 'var(--radius)',
                cursor: generating ? 'not-allowed' : 'pointer',
                fontSize: '0.85rem',
                fontWeight: 600,
                opacity: generating ? 0.7 : 1,
              }}
            >
              {generating ? 'Generating...' : 'Generate Projection'}
            </button>
          </div>
        )}
      </div>

      {/* Timeline selector — single-select, one timeline per projection */}
      {isAdmin && (
        <div style={{ display: 'flex', gap: '8px', marginBottom: '20px', flexWrap: 'wrap', alignItems: 'center' }}>
          <span style={{ fontSize: '0.8rem', color: 'var(--neutral-500)', fontWeight: 600 }}>Timeline:</span>
          {TIMELINES.map((t) => {
            const selected = selectedTimeline === t.id;
            return (
              <button
                key={t.id}
                role="radio"
                aria-checked={selected}
                onClick={() => setSelectedTimeline(t.id)}
                style={{
                  padding: '6px 14px',
                  borderRadius: 'var(--radius)',
                  border: selected ? '2px solid var(--brand-500)' : '1px solid var(--divider)',
                  background: selected ? 'var(--brand-100)' : 'var(--neutral-0)',
                  color: selected ? 'var(--brand-700)' : 'var(--neutral-500)',
                  cursor: 'pointer',
                  fontSize: '0.85rem',
                  fontWeight: selected ? 600 : 400,
                }}
              >
                {t.label}
              </button>
            );
          })}
          <span style={{ fontSize: '0.75rem', color: 'var(--neutral-500)' }}>
            Select one timeline per projection
          </span>
        </div>
      )}

      {!projection ? (
        <div style={{ padding: '40px', textAlign: 'center', ...cardStyle }}>
          <p style={{ color: 'var(--neutral-500)', fontSize: '1rem', marginBottom: '16px' }}>
            No projections generated yet for this customer.
          </p>
          <p style={{ color: 'var(--neutral-500)', fontSize: '0.9rem' }}>
            Click "Generate Projection" to create forecasts for {customerName}.
          </p>
        </div>
      ) : (
        <div>
          {/* Axes Cards */}
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(300px, 1fr))', gap: '16px', marginBottom: '24px' }}>
            <AxisCard title="Speed" emoji="🚀" axis={projection.speed} />
            <AxisCard title="Value" emoji="💰" axis={projection.value} />
          </div>

          {/* Confidence, Key Factors & Recommendations — one card */}
          <div style={{ ...cardStyle, marginBottom: '24px' }}>
            <h3 style={{ margin: '0 0 16px 0', fontSize: '1.1rem', color: 'var(--neutral-700)' }}>
              📊 Confidence: {Math.round(projection.confidence * 100)}%
            </h3>
            <div style={{ marginBottom: '16px' }}>
              <div style={{ fontSize: '0.85rem', color: 'var(--neutral-500)', marginBottom: '8px', fontWeight: 600 }}>Key Factors:</div>
              <ul style={{ margin: 0, paddingLeft: '20px', color: 'var(--neutral-700)' }}>
                {projection.key_factors.map((factor, idx) => (
                  <li key={idx} style={{ marginBottom: '4px' }}>{factor}</li>
                ))}
              </ul>
            </div>
            {projection.recommendations.length > 0 && (
              <div style={{ borderTop: '1px solid var(--divider)', paddingTop: '12px' }}>
                <div style={{ fontSize: '0.85rem', color: 'var(--neutral-500)', marginBottom: '8px', fontWeight: 600 }}>💡 Recommendations:</div>
                <ul style={{ margin: 0, paddingLeft: '20px', color: 'var(--neutral-700)' }}>
                  {projection.recommendations.map((rec, idx) => (
                    <li key={idx} style={{ marginBottom: '8px' }}>{rec}</li>
                  ))}
                </ul>
              </div>
            )}
          </div>

          {/* Generated At */}
          <div style={{ marginTop: '16px', textAlign: 'center', fontSize: '0.8rem', color: 'var(--neutral-500)' }}>
            Generated: {new Date(projection.generated_at).toLocaleString()} · Timeline: {timelineLabel}
            {projection.model_used === false ? ' · rule-based (model unavailable)' : ''}
          </div>
        </div>
      )}
    </div>
  );
};
