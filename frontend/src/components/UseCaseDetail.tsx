/**
 * UseCaseDetail — the shared use-case detail view.
 *
 * Before this extraction the detail view existed as two ~165-line inline
 * copies (Home.tsx `view === 'detail'` and CustomerDashboard.tsx's
 * `detail` tab) that were already drifting (button labels, navigation
 * targets) — no two authoritative representations of the same
 * thing.
 *
 * The component is presentation + action callbacks ONLY: every view
 * transition and mutation goes through a callback so each surface owns
 * its own state. The fix rides on this: the customer dashboard passes
 * callbacks that hand the use case UP to Home (setSelectedUseCase +
 * setView) instead of navigating to a selection-required view with no
 * selection (the pre-fix dead-end / wrong-use-case behavior).
 *
 * Both surfaces' button labels are preserved verbatim (the comments CTA
 * differs — `commentsLabel` — until the copy is unified).
 */
import { UseCase } from '../types/use_case';

interface UseCaseDetailProps {
  useCase: UseCase;
  /** 'auditor' disables the Edit control (read-only customer role).
   *  Undefined (Home surface): no role gating. */
  userRole?: string;
  allowWrite?: boolean;
  /** Scoring in flight (F4): disables the scoring buttons. */
  busy?: boolean;
  /** set when AI scoring is unavailable for this use case
   *  (it belongs to a generic round) — the scoring controls are replaced by
   *  this label instead of rendering enabled buttons that would 422. */
  scoringUnavailableReason?: string | null;
  onEdit: (uc: UseCase) => void;
  onDelete?: (uc: UseCase) => void;
  onScore: (uc: UseCase) => void;
  onOpenScoring: (uc: UseCase) => void;
  onOpenDrilldown: (uc: UseCase) => void;
  onOpenComments: (uc: UseCase) => void;
  onBack: () => void;
  /** The two surfaces label the comments CTA differently until
   * the copy is unified. */
  commentsLabel?: string;
}

export function UseCaseDetail({
  useCase,
  userRole,
  busy = false,
  allowWrite,
  scoringUnavailableReason = null,
  onEdit,
  onDelete,
  onScore,
  onOpenScoring,
  onOpenDrilldown,
  onOpenComments,
  onBack,
  commentsLabel = '💬 Open Comments & Collaboration',
}: UseCaseDetailProps) {
  const editDisabled = allowWrite === false || userRole === 'auditor' || userRole === 'none';
  const scoreColor =
    useCase.overall_score != null
      ? useCase.overall_score >= 70 ? 'var(--score-high)' : useCase.overall_score >= 35 ? 'var(--score-mid)' : 'var(--score-low)'
      : 'var(--score-unscored)';

  return (
    <div style={{ maxWidth: '900px', margin: '0 auto', padding: '24px' }}>
      {/* Header */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '24px' }}>
        <div>
          <h1 style={{ margin: 0, fontSize: '1.5rem', color: 'var(--ink)' }}>{useCase.title}</h1>
          <p style={{ margin: '4px 0 0', color: 'var(--neutral-500)', fontSize: '0.9rem' }}>
            {useCase.department || 'No department'} · <span style={{
              padding: '2px 10px', borderRadius: 'var(--radius)', fontSize: '0.8rem', fontWeight: 600, textTransform: 'capitalize',
              background: (useCase.status === 'active' ? 'var(--status-positive-soft)' : useCase.status === 'completed' ? 'var(--brand-100)' : useCase.status === 'draft' ? 'var(--status-warning-soft)' : 'var(--neutral-100)'),
              color: useCase.status === 'active' ? 'var(--status-positive)' : useCase.status === 'completed' ? 'var(--brand-700)' : useCase.status === 'draft' ? 'var(--status-warning)' : 'var(--neutral-500)',
            }}>{useCase.status}</span>
          </p>
        </div>
        <div style={{ display: 'flex', gap: '8px' }}>
          <button role="button" aria-label="Edit use case"
            disabled={editDisabled}
            title={editDisabled ? 'Read-only access: editing requires member or owner role' : undefined}
            onClick={() => onEdit(useCase)}
            style={{ padding: '8px 16px', background: editDisabled ? 'var(--neutral-100)' : 'var(--brand-500)', color: editDisabled ? 'var(--neutral-500)' : 'white', border: editDisabled ? '1px solid var(--divider)' : 'none', borderRadius: 'var(--radius)', cursor: editDisabled ? 'not-allowed' : 'pointer', fontSize: '0.85rem', fontWeight: 600 }}>
            ✏️ Edit
          </button>
          {onDelete && (
            <button role="button" aria-label="Delete use case"
              onClick={() => onDelete(useCase)}
              style={{ padding: '8px 16px', background: 'var(--neutral-0)', color: 'var(--status-negative)', border: '1px solid var(--status-negative)', borderRadius: 'var(--radius)', cursor: 'pointer', fontSize: '0.85rem', fontWeight: 600 }}
            >
              🗑️ Delete
            </button>
          )}
          <button role="button" aria-label="Back" onClick={onBack} style={{ padding: '8px 16px', background: 'var(--neutral-500)', color: 'var(--neutral-0)', border: 'none', borderRadius: 'var(--radius)', cursor: 'pointer', fontSize: '0.85rem' }}>
            ← Back
          </button>
        </div>
      </div>

      {/* KPI Row */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: '12px', marginBottom: '24px' }}>
        <div style={{ background: 'var(--neutral-0)', borderRadius: 'var(--radius)', padding: '16px', textAlign: 'center', boxShadow: 'var(--shadow-card)' }}>
          <div style={{ fontSize: '0.75rem', color: 'var(--neutral-500)', marginBottom: '4px' }}>Overall Score</div>
          <div style={{ fontSize: '1.8rem', fontWeight: 'bold', color: scoreColor }}>
            {useCase.overall_score != null ? useCase.overall_score.toFixed(1) : '—'}
          </div>
        </div>
        <div style={{ background: 'var(--neutral-0)', borderRadius: 'var(--radius)', padding: '16px', textAlign: 'center', boxShadow: 'var(--shadow-card)' }}>
          <div style={{ fontSize: '0.75rem', color: 'var(--neutral-500)', marginBottom: '4px' }}>Customer</div>
          <div style={{ fontSize: '1.2rem', fontWeight: 600, color: 'var(--ink)' }}>{useCase.customer_name || useCase.customer_id || '—'}</div>
        </div>
        <div style={{ background: 'var(--neutral-0)', borderRadius: 'var(--radius)', padding: '16px', textAlign: 'center', boxShadow: 'var(--shadow-card)' }}>
          <div style={{ fontSize: '0.75rem', color: 'var(--neutral-500)', marginBottom: '4px' }}>Savings</div>
          <div style={{ fontSize: '1.2rem', fontWeight: 600, color: 'var(--status-positive)' }}>
            {useCase.estimated_savings ? `$${useCase.estimated_savings.toLocaleString()}` : '—'}
          </div>
        </div>
        <div style={{ background: 'var(--neutral-0)', borderRadius: 'var(--radius)', padding: '16px', textAlign: 'center', boxShadow: 'var(--shadow-card)' }}>
          <div style={{ fontSize: '0.75rem', color: 'var(--neutral-500)', marginBottom: '4px' }}>Revenue</div>
          <div style={{ fontSize: '1.2rem', fontWeight: 600, color: 'var(--brand-700)' }}>
            {useCase.estimated_revenue ? `$${useCase.estimated_revenue.toLocaleString()}` : '—'}
          </div>
        </div>
      </div>

      {/* Description */}
      {useCase.description && (
        <div style={{ background: 'var(--neutral-0)', borderRadius: 'var(--radius)', padding: '20px', boxShadow: 'var(--shadow-card)', marginBottom: '16px' }}>
          <h3 style={{ margin: '0 0 8px 0', fontSize: '1rem', color: 'var(--neutral-700)' }}>Description</h3>
          <p style={{ margin: 0, color: 'var(--neutral-500)', lineHeight: 1.6 }}>{useCase.description}</p>
        </div>
      )}

      {/* Goals */}
      {useCase.goals && useCase.goals.length > 0 && (
        <div style={{ background: 'var(--neutral-0)', borderRadius: 'var(--radius)', padding: '20px', boxShadow: 'var(--shadow-card)', marginBottom: '16px' }}>
          <h3 style={{ margin: '0 0 8px 0', fontSize: '1rem', color: 'var(--neutral-700)' }}>Goals</h3>
          <ul style={{ margin: 0, paddingLeft: '20px', color: 'var(--neutral-500)', lineHeight: 1.6 }}>
            {useCase.goals.map((g, i) => <li key={i}>{g}</li>)}
          </ul>
        </div>
      )}

      {/* Challenges */}
      {useCase.challenges && useCase.challenges.length > 0 && (
        <div style={{ background: 'var(--neutral-0)', borderRadius: 'var(--radius)', padding: '20px', boxShadow: 'var(--shadow-card)', marginBottom: '16px' }}>
          <h3 style={{ margin: '0 0 8px 0', fontSize: '1rem', color: 'var(--neutral-700)' }}>Challenges</h3>
          <ul style={{ margin: 0, paddingLeft: '20px', color: 'var(--neutral-500)', lineHeight: 1.6 }}>
            {useCase.challenges.map((c, i) => <li key={i}>{c}</li>)}
          </ul>
        </div>
      )}

      {/* Pain Points */}
      {useCase.pain_points && useCase.pain_points.length > 0 && (
        <div style={{ background: 'var(--neutral-0)', borderRadius: 'var(--radius)', padding: '20px', boxShadow: 'var(--shadow-card)', marginBottom: '16px' }}>
          <h3 style={{ margin: '0 0 8px 0', fontSize: '1rem', color: 'var(--neutral-700)' }}>Pain Points</h3>
          <ul style={{ margin: 0, paddingLeft: '20px', color: 'var(--neutral-500)', lineHeight: 1.6 }}>
            {useCase.pain_points.map((p, i) => <li key={i}>{p}</li>)}
          </ul>
        </div>
      )}

      {/* Business Impact */}
      {(useCase.impact_category || useCase.impact_description || useCase.estimated_savings || useCase.estimated_revenue || useCase.timeline_estimate) && (
        <div style={{ background: 'var(--neutral-0)', borderRadius: 'var(--radius)', padding: '20px', boxShadow: 'var(--shadow-card)', marginBottom: '16px' }}>
          <h3 style={{ margin: '0 0 8px 0', fontSize: '1rem', color: 'var(--neutral-700)' }}>Business Impact</h3>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: '12px', marginTop: '12px' }}>
            <div><strong style={{ color: 'var(--neutral-500)', fontSize: '0.85rem' }}>Category:</strong><br/><span style={{ color: 'var(--ink)' }}>{useCase.impact_category || '—'}</span></div>
            <div><strong style={{ color: 'var(--neutral-500)', fontSize: '0.85rem' }}>Timeline:</strong><br/><span style={{ color: 'var(--ink)' }}>{useCase.timeline_estimate || '—'}</span></div>
            {useCase.impact_description && (
              <div style={{ gridColumn: '1 / -1' }}><strong style={{ color: 'var(--neutral-500)', fontSize: '0.85rem' }}>Description:</strong><br/><span style={{ color: 'var(--ink)' }}>{useCase.impact_description}</span></div>
            )}
          </div>
        </div>
      )}

      {/* Technology Tracking */}
      {(useCase.tech_stack || useCase.devices || useCase.software || useCase.vendor) && (
        <div style={{ background: 'var(--neutral-0)', borderRadius: 'var(--radius)', padding: '20px', boxShadow: 'var(--shadow-card)', marginBottom: '16px' }}>
          <h3 style={{ margin: '0 0 8px 0', fontSize: '1rem', color: 'var(--neutral-700)' }}>Technology Tracking</h3>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: '12px', marginTop: '12px' }}>
            {useCase.vendor && (
              <div><strong style={{ color: 'var(--neutral-500)', fontSize: '0.85rem' }}>Vendor:</strong><br/><span style={{ color: 'var(--ink)' }}>{useCase.vendor}</span></div>
            )}
            {useCase.tech_stack && (
              <div><strong style={{ color: 'var(--neutral-500)', fontSize: '0.85rem' }}>Tech Stack:</strong><br/><span style={{ color: 'var(--ink)' }}>{JSON.stringify(useCase.tech_stack).substring(0, 100)}{JSON.stringify(useCase.tech_stack).length > 100 ? '...' : ''}</span></div>
            )}
            {useCase.devices && (
              <div><strong style={{ color: 'var(--neutral-500)', fontSize: '0.85rem' }}>Devices:</strong><br/><span style={{ color: 'var(--ink)' }}>{JSON.stringify(useCase.devices).substring(0, 100)}{JSON.stringify(useCase.devices).length > 100 ? '...' : ''}</span></div>
            )}
            {useCase.software && (
              <div><strong style={{ color: 'var(--neutral-500)', fontSize: '0.85rem' }}>Software:</strong><br/><span style={{ color: 'var(--ink)' }}>{JSON.stringify(useCase.software).substring(0, 100)}{JSON.stringify(useCase.software).length > 100 ? '...' : ''}</span></div>
            )}
          </div>
        </div>
      )}

      {/* Scoring Actions */}
      <div style={{ background: 'var(--neutral-0)', borderRadius: 'var(--radius)', padding: '20px', marginBottom: '16px' }}>
        <h3 style={{ margin: '0 0 12px 0', fontSize: '1rem', color: 'var(--neutral-700)' }}>Scoring</h3>
        {scoringUnavailableReason ? (
          <p role="note" style={{ margin: 0, color: 'var(--neutral-500)', fontSize: '0.9rem' }}>{scoringUnavailableReason}</p>
        ) : useCase.overall_score == null ? (
          <button role="button" aria-label="Run scoring assessment"
            disabled={busy || editDisabled}
            onClick={() => onScore(useCase)}
            style={{ padding: '10px 20px', background: 'var(--status-warning)', color: 'var(--neutral-0)', border: 'none', borderRadius: 'var(--radius)', cursor: busy ? 'not-allowed' : 'pointer', fontSize: '0.9rem', fontWeight: 600 }}
          >
            {busy ? 'Scoring…' : '⚡ Run Scoring'}
          </button>
        ) : (
          <>
            <p style={{ margin: '0 0 12px 0', color: 'var(--neutral-500)' }}>Overall Score: <strong style={{ color: useCase.overall_score >= 70 ? 'var(--score-high)' : useCase.overall_score >= 35 ? 'var(--score-mid)' : 'var(--score-low)' }}>{useCase.overall_score.toFixed(1)}/100</strong></p>
            <div style={{ display: 'flex', gap: '8px' }}>
              <button role="button" aria-label="View scoring breakdown"
                onClick={() => onOpenScoring(useCase)}
                style={{ padding: '10px 20px', background: 'var(--brand-500)', color: 'var(--neutral-0)', border: 'none', borderRadius: 'var(--radius)', cursor: 'pointer', fontSize: '0.85rem', fontWeight: 600 }}
              >
                📊 View Scoring Breakdown
              </button>
              <button role="button" aria-label="Re-score use case"
                disabled={busy || editDisabled}
                onClick={() => onScore(useCase)}
                style={{ padding: '10px 20px', background: 'var(--status-warning)', color: 'var(--neutral-0)', border: 'none', borderRadius: 'var(--radius)', cursor: busy ? 'not-allowed' : 'pointer', fontSize: '0.85rem' }}
              >
                {busy ? 'Scoring…' : 'Re-Score'}
              </button>
              <button role="button" aria-label="View score breakdown"
                onClick={() => onOpenDrilldown(useCase)}
                style={{ padding: '10px 20px', background: 'var(--brand-500)', color: 'var(--neutral-0)', border: 'none', borderRadius: 'var(--radius)', cursor: 'pointer', fontSize: '0.85rem', fontWeight: 600 }}
              >
                🔍 Score Drill-Down
              </button>
            </div>
          </>
        )}
      </div>

      {/* Comments */}
      {useCase.id !== undefined && (
        <div style={{ marginBottom: '16px' }}>
          <button role="button" aria-label="Open comments and collaboration"
            onClick={() => onOpenComments(useCase)}
            style={{ padding: '10px 20px', background: 'var(--neutral-0)', border: '1px solid var(--divider)', borderRadius: 'var(--radius)', cursor: 'pointer', fontSize: '0.85rem', color: 'var(--neutral-700)' }}
          >
            {commentsLabel}
          </button>
        </div>
      )}

      {/* Metadata */}
      <div style={{ background: 'var(--neutral-0)', borderRadius: 'var(--radius)', padding: '20px', boxShadow: 'var(--shadow-card)' }}>
        <h3 style={{ margin: '0 0 8px 0', fontSize: '1rem', color: 'var(--neutral-700)' }}>Metadata</h3>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: '8px', fontSize: '0.85rem', color: 'var(--neutral-500)' }}>
          <div>ID: <span style={{ color: 'var(--ink)' }}>{useCase.id}</span></div>
          <div>Created: <span style={{ color: 'var(--ink)' }}>{new Date(useCase.created_at).toLocaleString()}</span></div>
          <div>Updated: <span style={{ color: 'var(--ink)' }}>{new Date(useCase.updated_at).toLocaleString()}</span></div>
          {useCase.created_by && <div>Created By: <span style={{ color: 'var(--ink)' }}>{useCase.created_by}</span></div>}
          {useCase.updated_by && <div>Updated By: <span style={{ color: 'var(--ink)' }}>{useCase.updated_by}</span></div>}
          {useCase.scored_at && <div>Scored At: <span style={{ color: 'var(--ink)' }}>{new Date(useCase.scored_at).toLocaleString()}</span></div>}
        </div>
      </div>
    </div>
  );
}
