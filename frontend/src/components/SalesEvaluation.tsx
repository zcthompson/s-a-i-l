import { useState, useEffect, type ReactNode } from 'react';
import { api } from '../lib/api';
import { GapAnalysis } from './GapAnalysis';
import { SalesPersona, SalesEvaluationPreview, AccountWorkspace } from '../types/sail';

interface SalesEvaluationResponse {
  id: number;
  customer_id: number;
  evaluation_name: string;
  status: string;
  readiness_overall?: number;
  readiness_dimensions?: Record<string, number>;
  environment_score?: number;
  environment_factors?: {
    software_completeness?: number;
    hardware_currency?: number;
    process_documentation?: number;
    vendor_diversity?: number;
    details?: Record<string, any>;
  };
  growth_opportunities?: Array<{ category: string; description: string }>;
  risk_factors?: Array<{ category: string; description: string; mitigation?: string }>;
  sales_approach?: {
    approach?: string;
    urgency?: string;
    focus?: string;
    talking_points?: string[];
    timing?: string;
    next_steps?: string[];
  };
  gaps?: Array<{ category: string; severity: 'high' | 'medium' | 'low'; description: string; readiness_dimension?: string; environment_factor?: string }>;
  // S-A-I-L P5 — persona-driven evaluations (nullable: legacy rows are null).
  persona?: string | null;
  persona_sections?: {
    persona: string | null;
    persona_label?: string;
    technical_depth?: string;
    business_framing?: string;
    risk_framing?: string;
    sections: Record<string, { label: string; content: unknown; [k: string]: unknown }>;
    discovery_gaps: Array<{ area: string; gap: string; action: string }>;
  } | null;
  source_context?: Record<string, unknown> | null;
  created_at: string;
  updated_at: string;
}

interface SalesEvaluationProps {
  customerId: number;
  /** The customer's display name — the generation panel makes the
   *  selected customer explicit (CHANGELOG 0.1.0 U6, directive 57). */
  customerName?: string;
}

const DIMENSIONS = [
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

// Color rule documented: 
// Green when env factor score >= 70 OR env factor >= dimension score
// Amber when env factor is within 15 points below dimension score
// Red otherwise
const SCORE_THRESHOLD_GREEN = 70;

function cellColor(envScore: number | undefined, dimScore: number | undefined): string {
  if (envScore === undefined || dimScore === undefined) return 'var(--neutral-400)';
  // Green: environment factor score is 70+ OR at/above the dimension score
  if (envScore >= SCORE_THRESHOLD_GREEN || envScore >= dimScore) return 'var(--status-positive)';
  // Amber: within 15 points below dimension score
  if (dimScore - envScore <= 15 && dimScore >= envScore) return 'var(--status-warning)';
  // Red: otherwise
  return 'var(--status-negative)';
}

// Render a JSON-ish value (string/number/bool/array/object) as readable text.
function renderValue(v: unknown): string {
  if (v === null || v === undefined) return '—';
  if (Array.isArray(v)) return v.map(renderValue).join(', ');
  if (typeof v === 'object') {
    return Object.entries(v as Record<string, unknown>)
      .map(([k, val]) => `${k.replace(/_/g, ' ')}: ${renderValue(val)}`)
      .join(', ');
  }
  return String(v);
}

// Render a persona section's content (string | array | object) readably.
function renderSectionContent(content: unknown): ReactNode {
  if (content === null || content === undefined) return <span style={{ color: 'var(--neutral-500)' }}>—</span>;
  if (typeof content === 'string') return content;
  if (Array.isArray(content)) {
    return (
      <ul style={{ margin: 0, paddingLeft: '18px' }}>
        {content.map((item, i) => (
          <li key={i}>
            {typeof item === 'object' && item !== null
              ? Object.entries(item as Record<string, unknown>)
                  .map(([k, v]) => `${k.replace(/_/g, ' ')}: ${renderValue(v)}`)
                  .join(' · ')
              : renderValue(item)}
          </li>
        ))}
      </ul>
    );
  }
  if (typeof content === 'object') {
    return (
      <div>
        {Object.entries(content as Record<string, unknown>).map(([k, v]) => (
          <div key={k} style={{ marginBottom: '4px' }}>
            <span style={{ color: 'var(--neutral-500)' }}>{k.replace(/_/g, ' ')}: </span>
            <span>{renderValue(v)}</span>
          </div>
        ))}
      </div>
    );
  }
  return String(content);
}

export function SalesEvaluation({ customerId, customerName }: SalesEvaluationProps) {
  const [evaluations, setEvaluations] = useState<SalesEvaluationResponse[]>([]);
  const [selectedEvaluation, setSelectedEvaluation] = useState<SalesEvaluationResponse | null>(null);
  const [evaluationName, setEvaluationName] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false);
  const [deletingId, setDeletingId] = useState<number | null>(null);
  // S-A-I-L P6c — persona selection + pre-generation preview (v2 items 31-33)
  const [personas, setPersonas] = useState<SalesPersona[]>([]);
  const [selectedPersona, setSelectedPersona] = useState<string>('');
  const [preview, setPreview] = useState<SalesEvaluationPreview | null>(null);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [previewError, setPreviewError] = useState<string | null>(null);
  // CHANGELOG 0.1.0 U6 (directives 31, 60, 66-67): the available customer
  // intelligence is made visible in the generation panel (not only behind
  // the Preview button) via the deterministic account-workspace endpoint —
  // the same source the evaluation engine feeds from.
  const [workspace, setWorkspace] = useState<AccountWorkspace | null>(null);

  const selectedPersonaObj = personas.find((p) => p.id === selectedPersona) || null;

  // Load the centralized persona registry once (S-A-I-L P5).
  useEffect(() => {
    api.listSalesPersonas().then(setPersonas).catch(() => setPersonas([]));
  }, []);

  // Load the customer's available intelligence for the generation panel.
  // Advisory — a failure just hides the context block (the preview still
  // reports the authoritative counts once it runs).
  useEffect(() => {
    let alive = true;
    setWorkspace(null);
    api.getAccountWorkspace(customerId)
      .then((w) => { if (alive) setWorkspace(w); })
      .catch(() => { if (alive) setWorkspace(null); });
    return () => { alive = false; };
  }, [customerId]);

  // Compute the pre-generation preview (CHANGELOG 0.1.0 U6, directive 66): it
  // refreshes automatically when the persona changes and on first load, so
  // the selected persona + customer intelligence are always visibly feeding
  // the generation experience — no manual "Preview" click required (the
  // button remains as an explicit refresh).
  useEffect(() => {
    let alive = true;
    setPreviewLoading(true);
    setPreviewError(null);
    api.previewSalesEvaluation(customerId, selectedPersona || null)
      .then((p) => { if (alive) setPreview(p); })
      .catch((err: any) => { if (alive) { setPreviewError(err?.message || 'Failed to preview'); setPreview(null); } })
      .finally(() => { if (alive) setPreviewLoading(false); });
    return () => { alive = false; };
  }, [customerId, selectedPersona]);

  // Load evaluations for this customer
  useEffect(() => {
    setLoading(true);
    api.listSalesEvaluations(customerId).then((data) => {
      setEvaluations(Array.isArray(data) ? data : []);
      if (selectedEvaluation === null && evaluations.length > 0) {
        setSelectedEvaluation(evaluations[0]!);
      }
    }).catch((err) => {
      setError(err.message || 'Failed to load evaluations');
      setEvaluations([]);
    }).finally(() => setLoading(false));
  // eslint-disable-next-line react-hooks/exhaustive-deps -- pre-existing dependency list; change only with UI verification
  }, [customerId]);

  // Generate a new evaluation (S-A-I-L P5: pass the selected persona context)
  const handleGenerate = async () => {
    if (!evaluationName.trim()) return;
    setLoading(true);
    setError(null);
    try {
      await api.createSalesEvaluationWithPersona(customerId, evaluationName.trim(), selectedPersona || null);
      setEvaluationName('');
      // Reload evaluations
      await api.listSalesEvaluations(customerId).then((data) => {
        setEvaluations(Array.isArray(data) ? data : []);
        if (selectedEvaluation === null && evaluations.length > 0) {
          setSelectedEvaluation(evaluations[0]!);
        }
      });
    } catch (err: any) {
      setError(err.message || 'Failed to generate evaluation');
    } finally {
      setLoading(false);
    }
  };

  // S-A-I-L P6c — pre-generation preview (v2 item 32): compute, don't persist.
  const handlePreview = async () => {
    setPreviewLoading(true);
    setPreviewError(null);
    try {
      const p = await api.previewSalesEvaluation(customerId, selectedPersona || null);
      setPreview(p);
    } catch (err: any) {
      setPreviewError(err.message || 'Failed to preview');
      setPreview(null);
    } finally {
      setPreviewLoading(false);
    }
  };

  // Delete evaluation
  const handleDelete = async () => {
    if (deletingId === null) return;
    setLoading(true);
    try {
      await api.deleteSalesEvaluation(deletingId);
      setShowDeleteConfirm(false);
      setDeletingId(null);
      // Reload evaluations
      await api.listSalesEvaluations(customerId).then((data) => {
        setEvaluations(Array.isArray(data) ? data : []);
        if (selectedEvaluation === null && evaluations.length > 0) {
          setSelectedEvaluation(evaluations[0]!);
        } else if (selectedEvaluation?.id === deletingId) {
          setSelectedEvaluation(evaluations[0] ?? null);
        }
      });
    } catch (err: any) {
      setError(err.message || 'Failed to delete evaluation');
    } finally {
      setLoading(false);
    }
  };

  if (loading) {
    return (
      <div style={{ padding: '40px', textAlign: 'center', color: 'var(--neutral-500)' }}>
        Loading evaluations...
      </div>
    );
  }

  if (error) {
    return (
      <div style={{
        padding: '20px', background: 'var(--status-negative-soft)', borderRadius: 'var(--radius)', marginBottom: '16px', color: 'var(--status-negative)'
      }}>
        <strong>Error:</strong> {error}
      </div>
    );
  }

  return (
    <div style={{ padding: '20px' }}>
      <h2 style={{ margin: '0 0 20px', color: 'var(--ink)' }}>Sales Evaluation</h2>

      {/* ── Generation panel (CHANGELOG 0.1.0 U6, directives 30-31, 57, 60-67) ──
          The selected customer, the selected persona (audience lens), and
          the available customer intelligence are all visible TOGETHER
          before invoking generation — the persona never stands in for the
          customer context, and the data domains are summarized without
          forcing manual fact selection. */}
      <div style={{ background: 'var(--neutral-0)', borderRadius: 'var(--radius)', boxShadow: 'var(--shadow-card)', padding: '20px', marginBottom: '24px' }}>
        <h3 style={{ margin: '0 0 4px 0', fontSize: '1.1rem', color: 'var(--ink)' }}>Prepare a Sales Evaluation</h3>
        <p style={{ margin: '0 0 16px 0', color: 'var(--neutral-500)', fontSize: '0.85rem' }}>
          {customerName ? <>For <strong style={{ color: 'var(--neutral-700)' }}>{customerName}</strong> — the selected persona is an audience lens over the customer intelligence below; both feed the generation together.</> : 'The selected persona is an audience lens over the customer intelligence below; both feed the generation together.'}
        </p>

        {/* Persona selection (directive 31) + the persona's visible context. */}
        <div style={{ marginBottom: '16px' }}>
          <label htmlFor="persona-select" style={{ display: 'block', fontSize: '0.8rem', fontWeight: 600, color: 'var(--neutral-700)', marginBottom: '6px' }}>
            Audience persona
          </label>
          <select
            id="persona-select"
            aria-label="Select persona"
            value={selectedPersona}
            onChange={(e) => setSelectedPersona(e.target.value)}
            style={{ width: '100%', padding: '8px 12px', background: 'var(--neutral-100)', border: '1px solid var(--divider)', borderRadius: 'var(--radius)', color: 'var(--ink)', fontSize: '0.9rem' }}
          >
            <option value="">— No persona (generic) —</option>
            {personas.map((p) => (
              <option key={p.id} value={p.id}>{p.label}</option>
            ))}
          </select>
          {selectedPersonaObj && (
            <div style={{ marginTop: '8px', padding: '10px 12px', background: 'var(--brand-50)', border: '1px solid var(--divider)', borderRadius: 'var(--radius)', fontSize: '0.82rem', color: 'var(--neutral-700)' }}>
              <div style={{ fontWeight: 600, color: 'var(--brand-700)', marginBottom: '4px' }}>{selectedPersonaObj.label}</div>
              {selectedPersonaObj.description && <div style={{ marginBottom: '4px' }}>{selectedPersonaObj.description}</div>}
              {selectedPersonaObj.technical_depth && (
                <div style={{ color: 'var(--neutral-600)' }}>Technical depth: {selectedPersonaObj.technical_depth}{selectedPersonaObj.business_framing ? ` · Framing: ${selectedPersonaObj.business_framing}` : ''}</div>
              )}
              {selectedPersonaObj.concerns && selectedPersonaObj.concerns.length > 0 && (
                <div style={{ color: 'var(--neutral-600)' }}>Concerns: {selectedPersonaObj.concerns.slice(0, 3).join(', ')}</div>
              )}
            </div>
          )}
        </div>

        {/* Available customer intelligence (directives 66-67): a concise
            pre-generation summary of the data domains, from the same
            deterministic account-workspace source the engine feeds from. */}
        {workspace && workspace.technology_landscape && (
          <div style={{ marginBottom: '16px' }}>
            <div style={{ fontSize: '0.8rem', fontWeight: 600, color: 'var(--neutral-700)', marginBottom: '6px' }}>
              Customer intelligence feeding this evaluation
            </div>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(130px, 1fr))', gap: '8px' }}>
              {([
                ['Technologies known', workspace.technology_landscape.total],
                ['Sales notes', workspace.sales_activity.total_notes],
                ['Knowledge sources', workspace.knowledge.total],
                ['Use cases (scored/total)', `${workspace.assessment.scored_count}/${workspace.assessment.total_count}`],
                ['EOL technology', workspace.technology_landscape.eol_count],
              ] as Array<[string, string | number]>).map(([k, v]) => (
                <div key={k} style={{ padding: '8px 10px', background: 'var(--neutral-50)', border: '1px solid var(--divider)', borderRadius: 'var(--radius)', fontSize: '0.8rem' }}>
                  <div style={{ color: 'var(--neutral-500)' }}>{k}</div>
                  <div style={{ fontWeight: 600, color: 'var(--ink)' }}>{v}</div>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Name + actions (the preview auto-refreshes on persona change;
            the button remains as an explicit re-run). */}
        <input
          value={evaluationName}
          onChange={(e) => setEvaluationName(e.target.value)}
          placeholder="Evaluation name"
          style={{
            width: '100%', padding: '8px 12px', background: 'var(--neutral-100)', border: '1px solid var(--divider)', borderRadius: 'var(--radius)', color: 'var(--ink)', fontSize: '0.9rem'
          }}
        />
        <div style={{ display: 'flex', gap: '8px', marginTop: '8px' }}>
          <button
            onClick={handleGenerate}
            disabled={loading || !evaluationName.trim()}
            style={{
              padding: '8px 16px', background: loading ? 'var(--neutral-400)' : 'var(--brand-500)', color: 'var(--neutral-0)', border: 'none', borderRadius: 'var(--radius)', cursor: 'pointer', fontSize: '0.85rem'
            }}
          >
            {loading ? 'Generating...' : 'Generate Evaluation'}
          </button>
          <button
            onClick={handlePreview}
            disabled={previewLoading}
            style={{
              padding: '8px 16px', background: previewLoading ? 'var(--neutral-400)' : 'var(--neutral-500)', color: 'var(--neutral-0)', border: 'none', borderRadius: 'var(--radius)', cursor: previewLoading ? 'not-allowed' : 'pointer', fontSize: '0.85rem'
            }}
          >
            {previewLoading ? 'Refreshing...' : 'Refresh Preview'}
          </button>
        </div>
        {error && (
          <div style={{ marginTop: '8px', padding: '8px 12px', background: 'var(--status-negative-soft)', borderRadius: 'var(--radius)', color: 'var(--status-negative)', fontSize: '0.85rem' }}>
            {error}
          </div>
        )}
        {previewError && (
          <div style={{ marginTop: '8px', padding: '8px 12px', background: 'var(--status-negative-soft)', borderRadius: 'var(--radius)', color: 'var(--status-negative)', fontSize: '0.85rem' }}>
            {previewError}
          </div>
        )}
      </div>

      {/* ── Historical evaluations ── */}
      <div style={{ marginBottom: '24px' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '12px' }}>
          <h3 style={{ margin: 0, fontSize: '1.1rem', color: 'var(--neutral-700)' }}>Evaluations</h3>
          <span style={{ fontSize: '0.85rem', color: 'var(--neutral-500)' }}>
            {evaluations.length} found
          </span>
        </div>
        <select
          aria-label="Select evaluation"
          style={{
            padding: '6px 12px', background: 'var(--neutral-100)', border: '1px solid var(--divider)', borderRadius: 'var(--radius)', color: 'var(--ink)', fontSize: '0.9rem'
          }}
          onChange={(e) => {
            const idx = parseInt(e.target.value, 10);
            const chosen = evaluations[idx];
            if (chosen) {
              setSelectedEvaluation(chosen);
              setEvaluationName(chosen.evaluation_name);
            }
          }}
        >
          <option value="-1">— Select an evaluation —</option>
          {evaluations.map((ev, idx) => (
            <option key={ev.id} value={idx}>
              {ev.evaluation_name}
            </option>
          ))}
        </select>
      </div>

      {/* Pre-generation preview (S-A-I-L P6c; CHANGELOG 0.1.0 U6 directive 66 —
          auto-computed on load and on persona change: the report the
          engine WOULD produce, from persona + full authorized context). */}
      {preview && (
        <div style={{ marginTop: '24px', padding: '16px', background: 'var(--neutral-50)', border: '1px solid var(--divider)', borderRadius: 'var(--radius)' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '12px' }}>
            <h4 style={{ margin: 0, color: 'var(--ink)' }}>Pre-generation preview — {preview.customer.name}</h4>
            <button role="button" aria-label="Close preview" onClick={() => setPreview(null)} style={{ background: 'none', border: 'none', cursor: 'pointer', fontSize: '1rem' }}>✕</button>
          </div>
          <p style={{ margin: '0 0 12px', color: 'var(--neutral-600)', fontSize: '0.85rem' }}>{preview.generation_intent}</p>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(140px, 1fr))', gap: '8px', marginBottom: '12px' }}>
            {([
              ['Technology items', preview.available_intelligence.technology_items],
              ['Sales notes', preview.available_intelligence.sales_notes],
              ['Knowledge entries', preview.available_intelligence.knowledge_entries],
              ['Use cases (scored/total)', `${preview.available_intelligence.use_cases.scored}/${preview.available_intelligence.use_cases.total}`],
              ['EOL technology', preview.available_intelligence.eol_tech_count],
            ] as Array<[string, string | number]>).map(([k, v]) => (
              <div key={k} style={{ padding: '8px 10px', background: 'var(--neutral-0)', borderRadius: 'var(--radius)', boxShadow: 'var(--shadow-card)', fontSize: '0.8rem' }}>
                <div style={{ color: 'var(--neutral-500)' }}>{k}</div>
                <div style={{ fontWeight: 600, color: 'var(--ink)' }}>{v}</div>
              </div>
            ))}
          </div>
          {preview.discovery_gaps.length > 0 && (
            <div>
              <div style={{ fontSize: '0.8rem', color: 'var(--neutral-600)', marginBottom: '6px' }}>Discovery gaps (missing knowledge):</div>
              <ul style={{ margin: 0, paddingLeft: '18px', color: 'var(--neutral-700)', fontSize: '0.82rem' }}>
                {preview.discovery_gaps.map((g, i) => (
                  <li key={i}>{g.gap} — <em>{g.action}</em></li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}

      {selectedEvaluation && selectedEvaluation.id > 0 && (
        <div style={{ marginTop: '32px', borderTop: '1px solid var(--divider)', paddingTop: '24px' }}>
          <h3 style={{ margin: '0 0 20px', color: 'var(--ink)' }}>Evaluation: {selectedEvaluation.evaluation_name}</h3>

          {/* Organizational Readiness */}
          <div style={{ marginBottom: '24px' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '12px' }}>
              <span style={{ color: 'var(--neutral-700)', fontSize: '0.9rem' }}>Organizational Readiness Overall</span>
              <span style={{ fontSize: '2rem', fontWeight: 'bold', color: 'var(--status-positive)' }}>
                {selectedEvaluation.readiness_overall?.toFixed(1) ?? 'N/A'}
              </span>
            </div>
            <div style={{ height: '8px', background: 'var(--neutral-100)', borderRadius: 'var(--radius-sm)', overflow: 'hidden', position: 'relative' }}>
              <div
                style={{
                  width: `${selectedEvaluation.readiness_overall ?? 0}%`,
                  height: '100%',
                  background: 'var(--neutral-400)',
                  borderRadius: 'var(--radius-sm)',
                  transition: 'width 0.3s',
                  position: 'relative'
                }}
              />
            </div>
          </div>

          {/* Per-dimension bars */}
          {selectedEvaluation.readiness_dimensions && Object.keys(selectedEvaluation.readiness_dimensions).length > 0 && (
            <div style={{ marginBottom: '24px' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '8px', color: 'var(--neutral-500)', fontSize: '0.85rem' }}>
                <span>Dimension</span>
                <span>Score</span>
              </div>
              {DIMENSIONS.map((dim) => {
                const score = selectedEvaluation.readiness_dimensions![dim];
                if (score !== undefined) {
                  return (
                    <div key={dim} style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '4px' }}>
                      <span style={{ color: 'var(--neutral-600)' }}>{dim}</span>
                      <span style={{ fontWeight: 'bold', color: 'var(--ink)' }}>{score.toFixed(1)}/100</span>
                    </div>
                  );
                }
                return null;
              })}
            </div>
          )}

          {/* Customer Environment */}
          {selectedEvaluation.environment_score !== undefined && (
            <div style={{ marginBottom: '24px' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '12px' }}>
                <span style={{ color: 'var(--neutral-700)', fontSize: '0.9rem' }}>Customer Environment Score</span>
                <span style={{ fontSize: '2rem', fontWeight: 'bold', color: 'var(--status-positive)' }}>
                  {selectedEvaluation.environment_score?.toFixed(1) ?? 'N/A'}
                </span>
              </div>
              <div style={{ height: '8px', background: 'var(--neutral-100)', borderRadius: 'var(--radius-sm)', overflow: 'hidden', position: 'relative' }}>
                <div
                  style={{
                    width: `${selectedEvaluation.environment_score ?? 0}%`,
                    height: '100%',
                    background: 'var(--neutral-400)',
                    borderRadius: 'var(--radius-sm)',
                    transition: 'width 0.3s',
                    position: 'relative'
                  }}
                />
              </div>
            </div>
          )}

          {/* Environment Factors with cell coloring */}
          {selectedEvaluation.environment_factors && Object.keys(selectedEvaluation.environment_factors).length > 0 && (
            <div style={{ marginBottom: '24px' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '8px', color: 'var(--neutral-500)', fontSize: '0.85rem' }}>
                <span>Factor</span>
                <span>Score</span>
              </div>
              {ENVIRONMENT_FACTORS.map((factor) => {
                const score = selectedEvaluation.environment_factors![factor];
                if (score !== undefined) {
                  const color = cellColor(score, selectedEvaluation.readiness_overall ?? 0);
                  return (
                    <div key={factor} style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '4px' }}>
                      <span style={{ color: 'var(--neutral-600)' }}>{factor}</span>
                      <span style={{ fontWeight: 'bold', color: 'var(--ink)' }}>{score.toFixed(1)}/100</span>
                      <span style={{ color: color }}>&nbsp;●</span>
                    </div>
                  );
                }
                return null;
              })}
            </div>
          )}

          {/* Gap Analysis — readiness dimensions × environment factors matrix */}
          {(selectedEvaluation.gaps || selectedEvaluation.readiness_dimensions || selectedEvaluation.environment_factors) && (
            <div style={{ marginBottom: '24px' }}>
              <h4 style={{ margin: '0 0 8px', color: 'var(--ink)' }}>Gap Analysis</h4>
              <GapAnalysis
                readiness_dimensions={selectedEvaluation.readiness_dimensions}
                environment_factors={selectedEvaluation.environment_factors}
                gaps={selectedEvaluation.gaps}
              />
              {selectedEvaluation.gaps && selectedEvaluation.gaps.length > 0 && (
                <p style={{ margin: '8px 0 4px', color: 'var(--neutral-500)', fontSize: '0.85rem' }}>
                  {selectedEvaluation.gaps.length} gap(s) identified
                </p>
              )}
            </div>
          )}

          {/* Risk Factors */}
          {selectedEvaluation.risk_factors && selectedEvaluation.risk_factors.length > 0 && (
            <div style={{ marginBottom: '24px' }}>
              <h4 style={{ margin: '0 0 8px', color: 'var(--ink)' }}>Risk Factors</h4>
              <ul style={{ margin: 0, paddingLeft: '20px', color: 'var(--neutral-700)' }}>
                {selectedEvaluation.risk_factors.map((risk, idx) => (
                  <li key={idx} style={{ marginBottom: '6px', fontSize: '0.85rem' }}>
                    {risk.description}
                    {risk.mitigation && (
                      <span style={{ marginLeft: '12px', color: 'var(--neutral-500)', fontSize: '0.8rem' }}>(mitigation: {risk.mitigation})</span>
                    )}
                  </li>
                ))}
              </ul>
            </div>
          )}

          {/* Growth Opportunities */}
          {selectedEvaluation.growth_opportunities && selectedEvaluation.growth_opportunities.length > 0 && (
            <div style={{ marginBottom: '24px' }}>
              <h4 style={{ margin: '0 0 8px', color: 'var(--ink)' }}>Growth Opportunities</h4>
              <ul style={{ margin: 0, paddingLeft: '20px', color: 'var(--neutral-700)' }}>
                {selectedEvaluation.growth_opportunities.map((g, idx) => (
                  <li key={idx} style={{ marginBottom: '6px', fontSize: '0.85rem' }}>
                    {g.category}: {g.description}
                  </li>
                ))}
              </ul>
            </div>
          )}

          {/* Sales Approach - render object keys readably */}
          {selectedEvaluation.sales_approach && Object.keys(selectedEvaluation.sales_approach).length > 0 && (
            <div style={{ marginBottom: '24px' }}>
              <h4 style={{ margin: '0 0 8px', color: 'var(--ink)' }}>Sales Approach</h4>
              <p style={{ margin: '4px 0', color: 'var(--neutral-500)', fontSize: '0.85rem' }}>
                Approach: {selectedEvaluation.sales_approach.approach || 'N/A'}
              </p>
              <p style={{ margin: '4px 0', color: 'var(--neutral-500)', fontSize: '0.85rem' }}>
                Urgency: {selectedEvaluation.sales_approach.urgency || 'N/A'}
              </p>
              <p style={{ margin: '4px 0', color: 'var(--neutral-500)', fontSize: '0.85rem' }}>
                Focus: {selectedEvaluation.sales_approach.focus || 'N/A'}
              </p>
              <p style={{ margin: '4px 0', color: 'var(--neutral-500)', fontSize: '0.85rem' }}>
                Talking points: {(
                  selectedEvaluation.sales_approach.talking_points || []
                ).map((pt: string, i: number) => `${i + 1}. ${pt}`).join('; ')}
              </p>
              <p style={{ margin: '4px 0', color: 'var(--neutral-500)', fontSize: '0.85rem' }}>
                Timing: {selectedEvaluation.sales_approach.timing || 'N/A'}
              </p>
              <p style={{ margin: '4px 0', color: 'var(--neutral-500)', fontSize: '0.85rem' }}>
                Next steps: {(
                  selectedEvaluation.sales_approach.next_steps || []
                ).map((s: string, i: number) => `${i + 1}. ${s}`).join('; ')}
              </p>
            </div>
          )}

          {/* S-A-I-L P6c — persona-tailored sections (v2 item 33) */}
          {selectedEvaluation.persona_sections && (
            <div style={{ marginBottom: '24px' }}>
              <h4 style={{ margin: '0 0 4px', color: 'var(--ink)' }}>
                Persona Sections{selectedEvaluation.persona ? ` — for ${selectedEvaluation.persona}` : ''}
              </h4>
              <p style={{ margin: '0 0 12px', color: 'var(--neutral-500)', fontSize: '0.8rem' }}>
                Deterministic, rule-based. Each section is labeled by epistemic status; recommendations cite evidence or are marked as hypotheses.
              </p>
              {Object.entries(selectedEvaluation.persona_sections.sections).map(([key, section]) => (
                <div key={key} style={{ marginBottom: '14px' }}>
                  <div style={{ fontSize: '0.9rem', fontWeight: 600, color: 'var(--neutral-700)', textTransform: 'capitalize' }}>{key.replace(/_/g, ' ')}</div>
                  <div style={{ fontSize: '0.72rem', color: 'var(--brand-700)', marginBottom: '6px' }}>{section.label}</div>
                  <div style={{ fontSize: '0.85rem', color: 'var(--neutral-700)' }}>{renderSectionContent(section.content)}</div>
                </div>
              ))}
              {selectedEvaluation.persona_sections.discovery_gaps && selectedEvaluation.persona_sections.discovery_gaps.length > 0 && (
                <div style={{ marginTop: '8px' }}>
                  <div style={{ fontSize: '0.8rem', color: 'var(--neutral-600)', marginBottom: '6px' }}>Discovery gaps:</div>
                  <ul style={{ margin: 0, paddingLeft: '18px', color: 'var(--neutral-700)', fontSize: '0.82rem' }}>
                    {selectedEvaluation.persona_sections.discovery_gaps.map((g, i) => (
                      <li key={i}>{g.gap} — <em>{g.action}</em></li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
          )}

          {/* Regenerate and Delete buttons */}
          <div style={{ display: 'flex', gap: '12px', marginTop: '24px' }}>
            <button
              onClick={handleGenerate}
              disabled={loading}
              style={{
                padding: '8px 16px', background: loading ? 'var(--neutral-400)' : 'var(--brand-500)', color: 'var(--neutral-0)', border: 'none', borderRadius: 'var(--radius)', cursor: loading ? 'not-allowed' : 'pointer', fontSize: '0.85rem'
              }}
            >
              {loading ? 'Generating...' : 'Regenerate'}
            </button>
            <button
              onClick={() => setShowDeleteConfirm(true)}
              disabled={loading}
              style={{
                padding: '8px 16px', background: 'var(--status-negative)', color: 'var(--neutral-0)', border: 'none', borderRadius: 'var(--radius)', cursor: loading ? 'not-allowed' : 'pointer', fontSize: '0.85rem'
              }}
            >
              Delete
            </button>
          </div>
        </div>
      )}

      {showDeleteConfirm && deletingId !== null && deletingId > 0 && (
        <div style={{
          padding: '16px', background: 'var(--status-negative-soft)', borderRadius: 'var(--radius)', marginBottom: '16px', color: 'var(--status-negative)'
        }}>
          <strong>Delete evaluation</strong> "{selectedEvaluation?.evaluation_name}"?
          <br />This action cannot be undone.
          <div style={{ marginTop: '12px', display: 'flex', gap: '8px' }}>
            <button onClick={handleDelete} style={{ padding: '6px 12px', background: 'var(--status-negative)', color: 'var(--neutral-0)', border: 'none', borderRadius: 'var(--radius-sm)', cursor: 'pointer' }}>Delete</button>
            <button onClick={() => setShowDeleteConfirm(false)} style={{ padding: '6px 12px', background: 'var(--neutral-500)', color: 'var(--neutral-0)', border: 'none', borderRadius: 'var(--radius-sm)', cursor: 'pointer' }}>Cancel</button>
          </div>
        </div>
      )}
    </div>
  );
}
