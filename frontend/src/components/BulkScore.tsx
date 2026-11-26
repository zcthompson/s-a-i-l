import { useEffect, useRef, useState } from 'react';
import { api } from '../lib/api';
import { useWorkspaceActions } from '../lib/useWorkspaceActions';
import { UseCase } from '../types/use_case';

interface BulkScoreProps {
  onBack: () => void;
  selectedCustomerId?: number | null;
  selectedCustomerName?: string;
  /** Part 13 WS5 (R8): ids of the customer's GENERIC rounds — their use
   *  cases cannot be AI-scored, so they are not selectable here. */
  aiScoringBlockedRoundIds?: ReadonlySet<number>;
}

// Part 13 WS5 (R8): the shared label module (source of truth) — imported for
// this file's own use and re-exported for eager consumers (CustomerDashboard).
import { AI_SCORING_REQUIRES_AI_ASSESSMENT } from '../lib/assessmentLabels';
export { AI_SCORING_REQUIRES_AI_ASSESSMENT };

export function BulkScore({ onBack, selectedCustomerId, selectedCustomerName, aiScoringBlockedRoundIds }: BulkScoreProps) {
  const [customers, setCustomers] = useState<{ id: number; name: string }[]>([]);
  const [selectedCustomer, setSelectedCustomer] = useState<{ id: number; name: string } | null>(null);
  const { data: actions } = useWorkspaceActions(selectedCustomer?.id);
  const canScore = actions?.capabilities.use_case ?? false;
  const [useCases, setUseCases] = useState<UseCase[]>([]);
  const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set());
  const [loading, setLoading] = useState(true);
  const [scoring, setScoring] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [customerLoading, setCustomerLoading] = useState(true);

  // Auto-select the passed customer (from customer dashboard)
  const customerInitialized = useRef(false);
  useEffect(() => {
    if (customerInitialized.current) return;
    customerInitialized.current = true;
    (async () => {
      try {
        const data = await api.listCustomers();
        setCustomers(data);
        let match: { id: number; name: string } | undefined;
        if (selectedCustomerId != null) {
          match = data.find(c => c.id === selectedCustomerId);
        }
        if (!match && selectedCustomerName) {
          match = data.find(c => c.name === selectedCustomerName);
        }
        if (match) {
          setSelectedCustomer(match);
        }
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Failed to load customers');
      } finally {
        setCustomerLoading(false);
      }
    })();
  }, [selectedCustomerId, selectedCustomerName]);

  useEffect(() => {
    if (selectedCustomer) {
      loadCustomerUseCases();
    } else {
      setUseCases([]);
      setLoading(false);
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps -- pre-existing dependency list; change only with UI verification
  }, [selectedCustomer]);

  const loadCustomerUseCases = async () => {
    if (!selectedCustomer) return;
    try {
      setLoading(true);
      const useCases = await api.getCustomerUseCases(selectedCustomer.name);
      setUseCases(useCases);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load use cases');
    } finally {
      setLoading(false);
    }
  };

  const toggleSelect = (id: number) => setSelectedIds(prev => {
    const n = new Set(prev);
    if (n.has(id)) n.delete(id);
    else n.add(id);
    return n;
  });

  const isBlocked = (uc: UseCase) =>
    uc.assessment_id != null && !!aiScoringBlockedRoundIds?.has(uc.assessment_id);
  const scorable = useCases.filter(u => !isBlocked(u));

  const selectAll = () => setSelectedIds(new Set(scorable.map(u => u.id)));

  const selectAllUnscored = () => {
    const unscored = scorable.filter(u => u.overall_score == null);
    setSelectedIds(new Set(unscored.map(u => u.id)));
  };

  const deselectAll = () => setSelectedIds(new Set());

  const handleBulkScore = async () => {
    if (!canScore) return;
    if (selectedIds.size === 0) { setError('Select at least one use case to score.'); return; }
    setScoring(true);
    setError(null);
    try {
      await api.bulkScore(Array.from(selectedIds));
      await loadCustomerUseCases();
      setSelectedIds(new Set());
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Bulk scoring failed');
    } finally {
      setScoring(false);
    }
  };

  const unscored = scorable.filter(u => u.overall_score == null);

  // UX audit #4: when the panel is entered WITH a customer context (from the
  // in-page Assessments rail), the redundant customer dropdown was a second
  // source of truth for "which customer am I scoring" — changing it silently
  // re-scoped the working set mid-task. Lock it: the customer is fixed by the
  // page context and shown read-only. The dropdown stays only for the
  // context-free entry (global My Assessments → Bulk Score).
  const customerContextLocked = selectedCustomerId != null || !!selectedCustomerName;

  return (
    <div style={{ maxWidth: '1200px', margin: '0 auto', padding: '24px' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '20px' }}>
        <div>
          <button role="button" aria-label="Back to assessments" onClick={onBack} style={{ padding: '8px 16px', background: 'var(--neutral-500)', color: 'var(--neutral-0)', border: 'none', borderRadius: 'var(--radius)', cursor: 'pointer', fontWeight: 600, marginBottom: '8px' }}>
            {'←'} Back
          </button>
        </div>
      </div>

      {error && <div role="alert" aria-live="assertive" style={{ padding: '12px 16px', background: 'var(--status-negative-soft)', borderLeft: '4px solid var(--status-negative)', borderRadius: 'var(--radius-sm)', marginBottom: '16px', color: 'var(--status-negative)' }}><span aria-hidden="true">⚠️ </span>{error}</div>}

      {customerLoading ? (
        <div role="status" aria-live="polite" style={{ padding: '40px', textAlign: 'center', color: 'var(--neutral-500)' }}>Loading customers…</div>
      ) : !selectedCustomer || customers.length === 0 ? (
        <div style={{ textAlign: 'center', padding: '40px' }}>
          {selectedCustomerId != null && selectedCustomerName ? (
            <>
              <p style={{ color: 'var(--neutral-500)', marginBottom: '16px' }}>No customers found for bulk scoring.</p>
              <p style={{ color: 'var(--neutral-500)', fontSize: '0.9rem' }}>Please create a customer first.</p>
              <button onClick={onBack} style={{ marginTop: '16px', padding: '8px 20px', background: 'var(--brand-500)', color: 'var(--neutral-0)', border: 'none', borderRadius: 'var(--radius)', cursor: 'pointer' }}>
                Go to Customers
              </button>
            </>
          ) : (
            <>
              <p style={{ color: 'var(--neutral-500)', marginBottom: '16px' }}>No customers available for bulk scoring.</p>
              {customers.length === 0 && (
                <p style={{ color: 'var(--neutral-500)', fontSize: '0.9rem' }}>You need to create a customer first to start bulk scoring use cases.</p>
              )}
            </>
          )}
        </div>
      ) : (
        <>
          {/* Customer selector — UX audit #4: read-only when a customer
              context was passed in; a free dropdown otherwise. */}
          <div style={{ marginBottom: '20px' }}>
            {customerContextLocked ? (
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px', fontSize: '0.9rem', color: 'var(--neutral-700)' }}>
                <span style={{ fontWeight: 500 }}>Customer:</span>
                <span style={{ padding: '8px 12px', background: 'var(--neutral-100)', border: '1px solid var(--divider)', borderRadius: 'var(--radius)' }}>
                  {selectedCustomer?.name || selectedCustomerName}
                </span>
                <span style={{ fontSize: '0.78rem', color: 'var(--neutral-500)' }}>
                  (fixed by the customer workspace)
                </span>
              </div>
            ) : (
              <>
                <label style={{ display: 'block', marginBottom: '6px', fontSize: '0.9rem', fontWeight: 500, color: 'var(--neutral-700)' }}>
                  Customer:
                </label>
                <select
                  aria-label="Bulk Score customer selection"
                  value={selectedCustomer?.id ?? ''}
                  onChange={(e) => {
                    const selected = customers.find(c => String(c.id) === e.target.value);
                    if (selected) setSelectedCustomer(selected);
                  }}
                  style={{ padding: '8px 12px', border: '1px solid var(--divider)', borderRadius: 'var(--radius)', fontSize: '0.9rem', minWidth: '200px' }}
                >
                  <option value="">— Select a customer —</option>
                  {customers.map(c => (
                    <option key={c.id} value={c.id}>{c.name}</option>
                  ))}
                </select>
              </>
            )}
          </div>

          {selectedCustomer && (
            <>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '20px' }}>
                <div>
                  <h1 style={{ margin: '0 0 4px 0', fontSize: '1.5rem', color: 'var(--ink)' }}>Bulk Score: {selectedCustomer.name}</h1>
                  <p style={{ margin: 0, color: 'var(--neutral-500)', fontSize: '0.9rem' }}>Select use cases to score together.</p>
                </div>
              </div>

              {loading ? (
                <div role="status" aria-live="polite" style={{ padding: '40px', textAlign: 'center', color: 'var(--neutral-500)' }}>Loading use cases…</div>
              ) : (
                <>
                  <div style={{ display: 'flex', gap: '8px', marginBottom: '16px', flexWrap: 'wrap' }}>
                    <button role="button" aria-label="Select all use cases" onClick={selectAll} disabled={scorable.length === 0} style={{ padding: '6px 16px', background: 'var(--brand-50)', color: 'var(--brand-700)', border: '1px solid var(--brand-500)', borderRadius: 'var(--radius)', cursor: 'pointer', fontSize: '0.85rem' }}>
                      Select All
                    </button>
                    {unscored.length > 0 && (
                      <button role="button" aria-label="Select all unscored use cases" onClick={selectAllUnscored} style={{ padding: '6px 16px', background: 'var(--neutral-100)', color: 'var(--neutral-500)', border: '1px solid var(--divider)', borderRadius: 'var(--radius)', cursor: 'pointer', fontSize: '0.85rem' }}>
                        Select Unscored Only
                      </button>
                    )}
                    <button role="button" aria-label="Deselect all use cases" onClick={deselectAll} style={{ padding: '6px 16px', background: 'var(--neutral-100)', color: 'var(--neutral-500)', border: '1px solid var(--divider)', borderRadius: 'var(--radius)', cursor: 'pointer', fontSize: '0.85rem' }}>
                      Deselect All
                    </button>
                    <span style={{ padding: '6px 0', fontSize: '0.85rem', color: 'var(--neutral-500)' }}>{selectedIds.size} selected</span>
                  </div>

                  {useCases.length === 0 ? (
                    <div style={{ padding: '40px', textAlign: 'center', color: 'var(--neutral-500)' }}>
                      <p>No use cases found for this customer.</p>
                    </div>
                  ) : (
                    <div style={{ background: 'var(--neutral-0)', borderRadius: 'var(--radius)', boxShadow: 'var(--shadow-card)', overflow: 'hidden' }}>
                      <div style={{ overflowX: 'auto' }}>
                        <table style={{ width: '100%', borderCollapse: 'collapse' }}>
                          <thead>
                            <tr style={{ borderBottom: '2px solid var(--divider)' }}>
                              <th style={{ padding: '12px 16px', textAlign: 'left', fontSize: '0.85rem', fontWeight: 600, color: 'var(--neutral-500)', width: '40px' }}>
                                <input aria-label="Bulk Score field"
                                  type="checkbox"
                                  checked={scorable.length > 0 && selectedIds.size === scorable.length}
                                  disabled={scorable.length === 0}
                                  onChange={(e) => e.target.checked ? selectAll() : deselectAll()}
                                  style={{ cursor: 'pointer' }}
                                />
                              </th>
                              {['Title', 'Department', 'Status', 'Score', 'Created'].map(h => (
                                <th key={h} style={{ padding: '12px 16px', textAlign: 'left', fontSize: '0.85rem', fontWeight: 600, color: 'var(--neutral-500)' }}>{h}</th>
                              ))}
                            </tr>
                          </thead>
                          <tbody>
                            {useCases.map(uc => {
                              const blocked = isBlocked(uc);
                              return (
                                <tr
                                  key={uc.id}
                                  style={{ borderBottom: '1px solid var(--neutral-100)' }}
                                >
                                  <td style={{ padding: '12px 16px' }}>
                                    {blocked ? (
                                      <input aria-label={`Select ${uc.title} — ${AI_SCORING_REQUIRES_AI_ASSESSMENT}`}
                                        type="checkbox"
                                        checked={false}
                                        disabled
                                        title={AI_SCORING_REQUIRES_AI_ASSESSMENT}
                                        style={{ cursor: 'not-allowed' }}
                                      />
                                    ) : (
                                      <input aria-label={`Select ${uc.title}`}
                                        type="checkbox"
                                        checked={selectedIds.has(uc.id)}
                                        onChange={() => toggleSelect(uc.id)}
                                        style={{ cursor: 'pointer' }}
                                      />
                                    )}
                                  </td>
                                  <td style={{ padding: '12px 16px', fontWeight: 500, color: 'var(--ink)' }}>
                                    {uc.title}
                                    {blocked && (
                                      <div style={{ fontSize: '0.78rem', fontWeight: 400, color: 'var(--neutral-500)' }}>{AI_SCORING_REQUIRES_AI_ASSESSMENT}</div>
                                    )}
                                  </td>
                                  <td style={{ padding: '12px 16px', color: 'var(--neutral-500)' }}>{uc.department || '—'}</td>
                                  <td style={{ padding: '12px 16px' }}>
                                    <span style={{
                                      padding: '4px 10px',
                                      borderRadius: 'var(--radius)',
                                      background: uc.status === 'active' ? 'var(--status-positive-soft)' : uc.status === 'completed' ? 'var(--brand-100)' : 'var(--status-warning-soft)',
                                      color: uc.status === 'active' ? 'var(--status-positive)' : uc.status === 'completed' ? 'var(--brand-700)' : 'var(--status-warning)',
                                      fontSize: '0.8rem',
                                      fontWeight: 600,
                                      textTransform: 'capitalize',
                                    }}>{uc.status}</span>
                                  </td>
                                  <td style={{ padding: '12px 16px', fontWeight: 'bold', color: !uc.overall_score ? 'var(--score-unscored)' : uc.overall_score >= 70 ? 'var(--score-high)' : uc.overall_score >= 35 ? 'var(--score-mid)' : 'var(--score-low)' }}>
                                    {uc.overall_score != null ? `${uc.overall_score.toFixed(1)}/100` : '—'}
                                  </td>
                                  <td style={{ padding: '12px 16px', color: 'var(--neutral-500)', fontSize: '0.85rem' }}>
                                    {new Date(uc.created_at).toLocaleDateString()}
                                  </td>
                                </tr>
                              );
                            })}
                          </tbody>
                        </table>
                      </div>
                    </div>
                  )}

                  <button role="button" aria-label="Bulk score selected use cases"
                    onClick={handleBulkScore}
                    disabled={!canScore || selectedIds.size === 0 || scoring}
                    style={{
                      marginTop: '20px',
                      padding: '8px 20px',
                      background: (selectedIds.size > 0 && !scoring) ? 'var(--brand-500)' : 'var(--neutral-400)',
                      color: 'var(--neutral-0)',
                      border: 'none',
                      borderRadius: 'var(--radius)',
                      cursor: (selectedIds.size > 0 && !scoring) ? 'pointer' : 'not-allowed',
                      fontSize: '0.9rem',
                      fontWeight: 'bold',
                    }}
                  >
                    {scoring ? 'Scoring...' : `Score ${selectedIds.size} Selected`}
                  </button>
                </>
              )}
            </>
          )}
        </>
      )}
    </div>
  );
}
export default BulkScore;
