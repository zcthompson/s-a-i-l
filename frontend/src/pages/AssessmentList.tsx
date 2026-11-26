import React, { useCallback, useEffect, useRef, useState } from 'react';
import { api } from '../lib/api';
import { UseCase, Customer } from '../types/use_case';
import { useAssessmentListNav } from '../lib/useAssessmentListNav';
import type { AssessmentSort } from '../lib/useAssessmentListNav';

interface AssessmentListProps {
  onSelect: (useCase: UseCase) => void;
  onScore: (useCase: UseCase) => void;
  onEdit: (useCase: UseCase) => void;
}

const PAGE_SIZE = 50;

const SORT_TO_API: Record<AssessmentSort, string> = { date: 'updated', score: 'score', title: 'title' };

// FE-10: hex-alpha suffixes appended to a CSS variable expression are
// invalid (`var(--status-positive)20` is not a color). Compose a valid
// translucent color with color-mix() so badges/buttons render correct
// backgrounds and borders in light and dark themes.
const mix = (c: string, pct: number = 20) => `color-mix(in srgb, ${c} ${pct}%, transparent)`;

export function AssessmentList({ onSelect, onScore, onEdit }: AssessmentListProps) {
  const [useCases, setUseCases] = useState<UseCase[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [nav, updateNav] = useAssessmentListNav();
  const { search: activeSearch, status: statusFilter, sort: sortBy, customerId: selectedCustomerId, page } = nav;
  const [searchTerm, setSearchTerm] = useState(activeSearch);
  const [lastPageFull, setLastPageFull] = useState(false);
  const [allCustomers, setAllCustomers] = useState<Customer[]>([]);
  const [customerMap, setCustomerMap] = useState<Record<number, string>>({});

  // FE-05: identity guard — results/errors/loading only commit when the
  // response still belongs to the CURRENT request. A late response for a
  // superseded customer/filter must never clobber fresh state.
  const requestSeq = useRef(0);

  useEffect(() => {
    loadCustomersForMapping();
  }, []);

  // History/direct links update the field; a pending draft is never serialized
  // until its debounce completes. Navigating back cancels the pending timer.
  useEffect(() => { setSearchTerm(activeSearch); }, [activeSearch, statusFilter, sortBy, selectedCustomerId, page]);
  useEffect(() => {
    if (searchTerm.trim() === activeSearch) return;
    const t = setTimeout(() => updateNav({ search: searchTerm.trim(), page: 1 }), 300);
    return () => clearTimeout(t);
    // updateNav intentionally reads the latest router parameters at write time.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [searchTerm, activeSearch]);

  // FE-03: filters and sort reset pagination; the list refetches whenever
  // any server-side input changes.
  useEffect(() => {
    loadUseCases();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedCustomerId, statusFilter, sortBy, activeSearch, page]);

  const loadCustomersForMapping = async () => {
    try {
      const customers = await api.listCustomers();
      setAllCustomers(customers);
      const map: Record<number, string> = {};
      customers.forEach((c) => { map[c.id] = c.name; });
      setCustomerMap(map);
    } catch {
      // Ignore — the customer column degrades to '-'.
    }
  };

  const getCustomerName = (id?: number | string | null): string => {
    if (!id) return '-';
    const numId = typeof id === 'number' ? id : parseInt(String(id), 10);
    return customerMap[numId] || '-';
  };

  // FE-03: authoritative filtering/sorting lives on the BACKEND over the
  // complete authorized dataset; the UI pages through it (skip/limit).
  // Previously the whole list was truncated at the first 100 rows and
  // search/sort/counts ran client-side over that partial page.
  const loadUseCases = useCallback(async () => {
    const seq = ++requestSeq.current;
    try {
      setLoading(true);
      // FE-05: a successful fetch clears any earlier error banner; the banner
      // is only shown while there is no data, with an explicit Retry action.
      const data = await api.list({
        skip: (page - 1) * PAGE_SIZE,
        limit: PAGE_SIZE,
        sort: SORT_TO_API[sortBy],
        ...(statusFilter ? { status: statusFilter } : {}),
        ...(activeSearch ? { search: activeSearch } : {}),
        ...(selectedCustomerId !== null ? { customer_id: String(selectedCustomerId) } : {}),
      });
      if (seq !== requestSeq.current) return; // stale — a newer request owns the state
      if (data.length === 0 && page > 1) {
        updateNav({ page: 1 }, true);
        return;
      }
      setUseCases(data);
      setLastPageFull(data.length === PAGE_SIZE);
      setError(null);
    } catch (err) {
      if (seq !== requestSeq.current) return; // stale failure — ignore
      setError(err instanceof Error ? err.message : 'Failed to load use cases');
      setUseCases([]);
      setLastPageFull(false);
    } finally {
      if (seq === requestSeq.current) setLoading(false);
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps -- pre-existing dependency list; change only with UI verification
  }, [page, sortBy, statusFilter, activeSearch, selectedCustomerId]);

  const resetFilters = () => {
    setSearchTerm('');
    updateNav({ search: '', status: '', sort: 'date', customerId: null, page: 1 });
  };

  const hasFilters = searchTerm !== '' || selectedCustomerId !== null || statusFilter !== '';

  const getScoreColor = (score?: number | null) => {
    // FE-10: a real ZERO score is a low score (negative styling) — only a
    // null/undefined score is the missing state.
    if (score === null || score === undefined) return 'var(--neutral-400)';
    if (score >= 70) return 'var(--status-positive)';
    if (score >= 35) return 'var(--status-warning)';
    return 'var(--status-negative)';
  };

  const getStatusColor = (status: string) => {
    switch (status) {
      case 'active': return 'var(--status-positive)';
      case 'completed': return 'var(--brand-500)';
      case 'draft': return 'var(--status-warning)';
      case 'archived': return 'var(--neutral-400)';
      default: return 'var(--neutral-500)';
    }
  };

  // FE-03: honest counts. The default contract returns one page without a
  // total, so the label describes what was loaded + the page position —
  // never a partial page presented as the complete dataset.
  const pageLabel = `Page ${page}` + (lastPageFull ? ` of ${page}+` : ` of ${page}`);

  return (
    <div style={{ maxWidth: '1200px', margin: '0 auto', padding: '24px' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '24px' }}>
        <div>
          <h1 style={{ margin: '0 0 4px 0', fontSize: '1.5rem', color: 'var(--ink)' }}>My Assessments</h1>
          <p style={{ margin: 0, color: 'var(--neutral-500)', fontSize: '0.9rem' }}>
            {useCases.length} use cases · {pageLabel}
          </p>
        </div>
      </div>

      {/* Filters */}
      <div style={{ display: 'flex', gap: '12px', marginBottom: '20px', flexWrap: 'wrap', alignItems: 'flex-start' }}>
        <input aria-label="Search assessments by title or description"
          style={{ ...inputStyle, flex: '1 1 250px' }}
          placeholder="🔍 Search by title or description..."
          value={searchTerm}
          onChange={(e) => setSearchTerm(e.target.value)}
        />
        {/* FE-09: distinct accessible names for the three filter controls. */}
        <select aria-label="Filter by customer"
          style={{ ...inputStyle, width: '200px', borderColor: selectedCustomerId !== null ? 'var(--brand-500)' : 'var(--divider)' }}
          value={selectedCustomerId?.toString() ?? 'all'}
          onChange={(e) => updateNav({ customerId: e.target.value === 'all' ? null : Number(e.target.value), page: 1 })}
        >
          <option value="all">My Customers</option>
          {selectedCustomerId !== null && !allCustomers.some((customer) => customer.id === selectedCustomerId) && (
            <option value={selectedCustomerId}>Selected customer unavailable</option>
          )}
          {allCustomers.map((customer) => (
            <option key={customer.id} value={customer.id}>{customer.name}</option>
          ))}
        </select>
        <select aria-label="Filter by status"
          style={{ ...inputStyle, width: '180px', borderColor: statusFilter ? 'var(--brand-500)' : 'var(--divider)' }}
          value={statusFilter}
          onChange={(e) => updateNav({ status: e.target.value, page: 1 })}
        >
          <option value="">All Status</option>
          <option value="draft">Draft</option>
          <option value="active">Active</option>
          <option value="completed">Completed</option>
          <option value="archived">Archived</option>
        </select>
        <select aria-label="Sort assessments"
          style={{ ...inputStyle, width: '180px' }}
          value={sortBy}
          onChange={(e) => updateNav({ sort: e.target.value as AssessmentSort, page: 1 })}
        >
          <option value="date">Sort by Date</option>
          <option value="score">Sort by Score</option>
          <option value="title">Sort by Title</option>
        </select>
        {hasFilters && (
          <button role="button" aria-label="Clear assessment filters"
            onClick={resetFilters}
            style={{
              ...inputStyle,
              width: 'auto',
              background: 'var(--brand-50)',
              border: '1px solid var(--brand-500)',
              color: 'var(--brand-700)',
              fontWeight: 600,
              cursor: 'pointer',
            }}
          >
            ✕ Clear Filters
          </button>
        )}
      </div>

      {/* Table */}
      <div style={{ background: 'var(--neutral-0)', borderRadius: 'var(--radius)', boxShadow: 'var(--shadow-card)', overflow: 'hidden' }}>
        {loading ? (
          <div role="status" aria-live="polite" style={{ padding: '40px', textAlign: 'center', color: 'var(--neutral-500)' }}>Loading assessments…</div>
        ) : error && useCases.length === 0 ? (
          // FE-05: explicit failure state with a Retry action — shown only
          // while there is no data, so a successful retry replaces the
          // banner with the records.
          <div role="alert" aria-live="assertive" style={{ padding: '16px', margin: '24px', background: 'var(--status-negative-soft)', borderLeft: '4px solid var(--status-negative)', color: 'var(--status-negative)', display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: '12px', flexWrap: 'wrap' }}>
            <span><span aria-hidden="true">⚠️ </span>{error}</span>
            <button role="button" aria-label="Retry loading assessments"
              onClick={() => { void loadUseCases(); }}
              style={{ ...inputStyle, width: 'auto', background: 'var(--status-negative-soft)', border: '1px solid var(--status-negative)', color: 'var(--status-negative)', fontWeight: 600, cursor: 'pointer' }}
            >
              ↻ Retry
            </button>
          </div>
        ) : useCases.length === 0 ? (
          <div style={{ padding: '40px', textAlign: 'center', color: 'var(--neutral-500)' }}>
            No assessments match the current filters
          </div>
        ) : (
          <>
            <div style={{ overflowX: 'auto' }}>
              <table style={{ width: '100%', borderCollapse: 'collapse' }}>
                <thead>
                  <tr style={{ borderBottom: '2px solid var(--divider)' }}>
                    {['Title', 'Customer', 'Department', 'Status', 'Score', 'Created', 'Actions'].map(h => (
                      <th key={h} style={thStyle}>{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {useCases.map(uc => (
                    <tr key={uc.id} style={{ borderBottom: '1px solid var(--neutral-100)' }}>
                      <td style={tdStyle}>
                        <div style={{ fontWeight: 500, color: 'var(--ink)' }}>{uc.title}</div>
                        <div style={{ fontSize: '0.8rem', color: 'var(--neutral-500)', maxWidth: '300px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                          {uc.description || 'No description'}
                        </div>
                      </td>
                      <td style={{ ...tdStyle, color: 'var(--neutral-500)' }}>{getCustomerName(uc.customer_id)}</td>
                      <td style={{ ...tdStyle, color: 'var(--neutral-500)' }}>{uc.department || '-'}</td>
                      <td style={tdStyle}>
                        <span style={{
                          padding: '4px 10px',
                          borderRadius: 'var(--radius)',
                          background: mix(getStatusColor(uc.status)),
                          color: getStatusColor(uc.status),
                          fontSize: '0.8rem',
                          fontWeight: 600,
                          textTransform: 'capitalize',
                        }}>
                          {uc.status}
                        </span>
                      </td>
                      <td style={tdStyle}>
                        {uc.overall_score != null ? (
                          <span style={{
                            fontWeight: 'bold',
                            color: getScoreColor(uc.overall_score),
                          }}>
                            {uc.overall_score.toFixed(1)}
                          </span>
                        ) : (
                          <span style={{ color: 'var(--neutral-500)' }}>—</span>
                        )}
                      </td>
                      <td style={{ ...tdStyle, color: 'var(--neutral-500)', fontSize: '0.85rem' }}>
                        {new Date(uc.created_at).toLocaleDateString()}
                      </td>
                      <td style={tdStyle}>
                        <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap' }}>
                          <button role="button" aria-label={`View ${uc.title}`}
                            style={actionBtnStyle('var(--brand-500)')}
                            onClick={() => onSelect(uc)}
                          >
                            📊 View
                          </button>
                          <button role="button" aria-label={`Edit ${uc.title}`}
                            style={actionBtnStyle('var(--status-positive)')}
                            onClick={() => onEdit(uc)}
                          >
                            ✏️ Edit
                          </button>
                          {uc.overall_score == null && (
                            <button role="button" aria-label={`Score ${uc.title}`}
                              style={actionBtnStyle('var(--status-warning)')}
                              onClick={() => onScore(uc)}
                            >
                              ⚡ Score
                            </button>
                          )}
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            {/* FE-03: visible pagination. */}
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '12px 16px', borderTop: '1px solid var(--divider)' }}>
              <span style={{ fontSize: '0.85rem', color: 'var(--neutral-500)' }}>{pageLabel}</span>
              <div style={{ display: 'flex', gap: '8px' }}>
                <button role="button" aria-label="Previous page"
                  disabled={page <= 1}
                  onClick={() => updateNav({ page: Math.max(1, page - 1) })}
                  style={pageBtnStyle(page <= 1)}
                >
                  ← Previous
                </button>
                <button role="button" aria-label="Next page"
                  disabled={!lastPageFull}
                  onClick={() => updateNav({ page: page + 1 })}
                  style={pageBtnStyle(!lastPageFull)}
                >
                  Next →
                </button>
              </div>
            </div>
          </>
        )}
      </div>
    </div>
  );
}

function actionBtnStyle(color: string): React.CSSProperties {
  return {
    padding: '6px 12px',
    background: mix(color),
    border: `1px solid ${mix(color, 40)}`,
    borderRadius: 'var(--radius)',
    cursor: 'pointer',
    fontSize: '0.8rem',
    color,
    fontWeight: 600,
  };
}

function pageBtnStyle(disabled: boolean): React.CSSProperties {
  return {
    padding: '6px 12px',
    background: disabled ? 'var(--neutral-100)' : 'var(--brand-50)',
    border: `1px solid ${disabled ? 'var(--divider)' : 'var(--brand-500)'}`,
    borderRadius: 'var(--radius)',
    cursor: disabled ? 'not-allowed' : 'pointer',
    fontSize: '0.85rem',
    color: disabled ? 'var(--neutral-500)' : 'var(--brand-500)',
    fontWeight: 600,
    opacity: disabled ? 0.6 : 1,
  };
}

const thStyle: React.CSSProperties = {
  padding: '14px 16px',
  textAlign: 'left',
  fontSize: '0.85rem',
  fontWeight: 600,
  color: 'var(--neutral-500)',
};

const tdStyle: React.CSSProperties = {
  padding: '14px 16px',
  fontSize: '0.9rem',
};

const inputStyle: React.CSSProperties = {
  padding: '8px 12px',
  border: '1px solid var(--divider)',
  borderRadius: 'var(--radius)',
  fontSize: '0.9rem',
};
export default AssessmentList;
