/**
 * Red Hat — Partner Pipeline (CSV) pane of the Intelligence Import surface:
 * upload a partner pipeline report CSV, review import history, inspect an
 * import's matched/unmatched accounts, and delete an import. Behavior and
 * data-testids are unchanged from the original single-vendor page.
 */
import { useCallback, useEffect, useRef, useState } from 'react';
import { api } from '../../lib/api';
import { useImportDetailLink } from './useImportDetailLink';
import { formatDate, formatUsd } from '../../lib/pipelineFormat';
import type {
  IntelligenceImportDetail,
  IntelligenceImportResult,
  IntelligenceImportSummary,
} from '../../types/intelligence_import';
import { cardStyle, thStyle, tdStyle, numStyle, linkBtn, isForbidden, warningStyle, unmatchedRowsWarning } from './shared';

const UNMATCHED_REASON: Record<string, string> = {
  unmatched: 'No matching customer name or alias',
  ambiguous: 'Matches more than one customer',
};

const amountWarning = (n: number) =>
  `${n} amount${n === 1 ? '' : 's'} could not be read and ${n === 1 ? 'was' : 'were'} recorded as unknown; those rows were still imported.`;

interface RedHatPipelinePaneProps {
  /** Open a customer's dashboard (sets the selected customer + view). */
  onOpenCustomer?: (name: string) => void;
}

export function RedHatPipelinePane({ onOpenCustomer }: RedHatPipelinePaneProps = {}) {
  const [history, setHistory] = useState<IntelligenceImportSummary[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [denied, setDenied] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [file, setFile] = useState<File | null>(null);
  const [uploading, setUploading] = useState(false);
  const [result, setResult] = useState<IntelligenceImportResult | null>(null);
  const [detail, setDetail] = useState<IntelligenceImportDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailId, setDetailId] = useImportDetailLink();
  const [deleting, setDeleting] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement | null>(null);

  const loadHistory = useCallback(async () => {
    try {
      setHistory(await api.listIntelligenceImports());
    } catch (err) {
      if (isForbidden(err)) setDenied(true);
      else setError(err instanceof Error ? err.message : 'Failed to load import history');
    } finally {
      setLoaded(true);
    }
  }, []);

  useEffect(() => { void loadHistory(); }, [loadHistory]);

  const handleUpload = async () => {
    if (!file) return;
    setUploading(true);
    setError(null);
    setNotice(null);
    try {
      const res = await api.uploadIntelligenceImport(file);
      setResult(res);
      setFile(null);
      if (fileInputRef.current) fileInputRef.current.value = '';
      await loadHistory();
    } catch (err) {
      if (isForbidden(err)) setDenied(true);
      else setError(err instanceof Error ? err.message : 'Import failed');
    } finally {
      setUploading(false);
    }
  };

  useEffect(() => {
    let active = true;
    setDetail(null);
    setError(null);
    if (detailId === null) { setDetailLoading(false); return () => { active = false; }; }
    setDetailLoading(true);
    const id = detailId;
    api.getIntelligenceImport(id).then((value) => { if (active) setDetail(value); })
      .catch((err: unknown) => { if (active) { if (isForbidden(err)) setDenied(true);
        else if ((err as { status?: number } | null)?.status === 404) setError('Import not found or unavailable.');
        else setError(err instanceof Error ? err.message : 'Failed to load import detail'); } })
      .finally(() => { if (active) setDetailLoading(false); });
    return () => { active = false; };
  }, [detailId]);

  const handleDelete = async () => {
    if (!detail) return;
    if (!window.confirm(`Delete import "${detail.file_name}"? This removes its pipeline rows, the knowledge documents it created, and the technology records it generated.`)) return;
    setDeleting(true);
    setError(null);
    try {
      const res = await api.deleteIntelligenceImport(detail.import_id);
      setNotice(`Import deleted (${res.deleted_rows} pipeline rows, ${res.deleted_knowledge} knowledge documents, ${res.deleted_technologies} technology records removed).`);
      if (result?.import_id === detail.import_id) setResult(null);
      setDetail(null);
      setDetailId(null);
      await loadHistory();
    } catch (err) {
      if (isForbidden(err)) setDenied(true);
      else setError(err instanceof Error ? err.message : 'Delete failed');
    } finally {
      setDeleting(false);
    }
  };

  if (denied) {
    return (
      <div role="alert" data-testid="intelligence-import-denied" style={{ ...cardStyle, color: 'var(--neutral-700)' }}>
        Requires sales manager or higher.
      </div>
    );
  }

  return (
    <div data-testid="intelligence-import-redhat">
      <p style={{ color: 'var(--neutral-500)', margin: '0 0 16px', fontSize: '0.9rem' }}>
        Upload a partner pipeline report (.csv). Each row is matched to an existing customer by customer name or alias (case-insensitive). Rows that do not match are skipped and reported — the rest of the file still imports, and no customers are created.
      </p>

      {error && (
        <div role="alert" aria-live="assertive" data-testid="intelligence-import-error" style={{ padding: '10px 14px', background: 'var(--status-negative-soft)', color: 'var(--status-negative)', borderLeft: '4px solid var(--status-negative)', marginBottom: '16px', fontWeight: 500 }}>
          {error}
        </div>
      )}
      {notice && (
        <div role="status" aria-live="polite" data-testid="intelligence-import-notice" style={{ padding: '10px 14px', background: 'var(--status-positive-soft)', color: 'var(--status-positive)', borderLeft: '4px solid var(--status-positive)', marginBottom: '16px', fontWeight: 500 }}>
          {notice}
        </div>
      )}

      <section style={cardStyle} data-testid="intelligence-import-upload" aria-label="Upload pipeline report">
        <div style={{ display: 'flex', gap: '12px', alignItems: 'center', flexWrap: 'wrap' }}>
          <input
            ref={fileInputRef}
            type="file"
            accept=".csv"
            aria-label="Pipeline report CSV"
            data-testid="intelligence-import-file"
            onChange={(e) => setFile(e.target.files?.[0] ?? null)}
          />
          <button
            role="button"
            aria-label="Import"
            data-testid="intelligence-import-submit"
            disabled={!file || uploading}
            onClick={handleUpload}
            style={{ padding: '8px 16px', borderRadius: 'var(--radius)', border: 'none', background: 'var(--brand-500)', color: 'var(--neutral-0)', cursor: !file || uploading ? 'not-allowed' : 'pointer', opacity: !file || uploading ? 0.6 : 1 }}
          >
            {uploading ? 'Importing…' : 'Import'}
          </button>
        </div>
        {result && (
          <div data-testid="intelligence-import-summary" role="status" style={{ marginTop: '14px', fontSize: '0.9rem', color: 'var(--neutral-700)' }}>
            Imported <strong>{result.file_name}</strong>: {result.total_rows} rows — {result.matched_accounts} matched accounts ({result.matched_rows} rows), {result.unmatched_accounts} unmatched accounts.
            {result.skipped_rows > 0 && (
              <div data-testid="intelligence-import-unmatched-warning" style={warningStyle}>
                ⚠ {unmatchedRowsWarning(result.skipped_rows)}
              </div>
            )}
            {(result.amount_issues ?? []).length > 0 && (
              <div data-testid="intelligence-import-amount-warning" style={warningStyle}>
                ⚠ {amountWarning(result.amount_issues.length)}
              </div>
            )}
          </div>
        )}
      </section>

      <section style={cardStyle} data-testid="intelligence-import-history" aria-label="Import history">
        <h3 style={{ margin: '0 0 8px', fontSize: '1rem', color: 'var(--neutral-700)' }}>Import history</h3>
        {!loaded ? (
          <div role="status" style={{ color: 'var(--neutral-500)' }}>Loading import history…</div>
        ) : history.length === 0 ? (
          <p data-testid="intelligence-import-history-empty" style={{ margin: 0, color: 'var(--neutral-500)' }}>No imports yet.</p>
        ) : (
          <div style={{ overflowX: 'auto' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse' }}>
              <thead>
                <tr style={{ borderBottom: '2px solid var(--divider)' }}>
                  <th style={thStyle}>File</th>
                  <th style={thStyle}>Imported at</th>
                  <th style={thStyle}>Imported by</th>
                  <th style={{ ...thStyle, textAlign: 'right' }}>Rows</th>
                  <th style={{ ...thStyle, textAlign: 'right' }}>Matched accounts</th>
                  <th style={{ ...thStyle, textAlign: 'right' }}>Matched rows</th>
                  <th style={{ ...thStyle, textAlign: 'right' }}>Unmatched accounts</th>
                  <th style={thStyle} aria-hidden="true"></th>
                </tr>
              </thead>
              <tbody>
                {history.map((h) => (
                  <tr
                    key={h.import_id}
                    data-testid={`intelligence-import-row-${h.import_id}`}
                    onClick={() => setDetailId(h.import_id)}
                    style={{ borderBottom: '1px solid var(--neutral-100)', cursor: 'pointer', background: detail?.import_id === h.import_id ? 'var(--neutral-50, #f5f9fa)' : undefined }}
                  >
                    <td style={tdStyle}>{h.file_name}</td>
                    <td style={tdStyle}>{formatDate(h.created_at)}</td>
                    <td style={tdStyle}>{h.imported_by}</td>
                    <td style={numStyle}>{h.total_rows}</td>
                    <td style={numStyle}>{h.matched_accounts}</td>
                    <td style={numStyle}>{h.matched_rows}</td>
                    <td style={numStyle}>{h.unmatched_accounts}</td>
                    <td style={tdStyle}>
                      <button
                        role="button"
                        aria-label={`Open import ${h.file_name}`}
                        style={linkBtn}
                        onClick={(e) => { e.stopPropagation(); setDetailId(h.import_id); }}
                      >
                        Open
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {detailLoading && <div role="status" style={{ color: 'var(--neutral-500)' }}>Loading import detail…</div>}

      {detail && (
        <div data-testid="intelligence-import-detail">
          <section style={cardStyle} data-testid="intelligence-import-detail-matched" aria-label="Matched accounts">
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: '12px', flexWrap: 'wrap', marginBottom: '8px' }}>
              <h3 style={{ margin: 0, fontSize: '1rem', color: 'var(--neutral-700)' }}>
                Matched accounts — {detail.file_name}
              </h3>
              <button
                role="button"
                aria-label="Delete import"
                data-testid="intelligence-import-delete"
                disabled={deleting}
                onClick={handleDelete}
                style={{ padding: '6px 14px', borderRadius: 'var(--radius)', border: '1px solid var(--status-negative)', background: 'var(--neutral-0)', color: 'var(--status-negative)', cursor: deleting ? 'not-allowed' : 'pointer' }}
              >
                {deleting ? 'Deleting…' : 'Delete'}
              </button>
            </div>
            {detail.matched.length === 0 ? (
              <p style={{ margin: 0, color: 'var(--neutral-500)' }}>No accounts matched.</p>
            ) : (
              <div style={{ overflowX: 'auto' }}>
                <table style={{ width: '100%', borderCollapse: 'collapse' }}>
                  <thead>
                    <tr style={{ borderBottom: '2px solid var(--divider)' }}>
                      <th style={thStyle}>Customer</th>
                      <th style={thStyle}>Matched by</th>
                      <th style={{ ...thStyle, textAlign: 'right' }}>Rows</th>
                      <th style={{ ...thStyle, textAlign: 'right' }}>Est. ACV</th>
                      <th style={{ ...thStyle, textAlign: 'right' }}>Est. TCV</th>
                      <th style={thStyle}>Technologies</th>
                      <th style={thStyle} aria-hidden="true"></th>
                    </tr>
                  </thead>
                  <tbody>
                    {detail.matched.map((m) => (
                      <tr key={m.customer_id} data-testid={`intelligence-import-matched-${m.customer_id}`} style={{ borderBottom: '1px solid var(--neutral-100)' }}>
                        <td style={tdStyle}>{m.customer_name}</td>
                        <td style={tdStyle} data-testid={`intelligence-import-matched-by-${m.customer_id}`}>
                          {(m.supplied_names ?? []).map((s) => `${s.matched_by === 'alias' ? 'alias' : 'name'} “${s.name}”${(m.supplied_names ?? []).length > 1 ? ` (${s.row_count})` : ''}`).join(', ') || '—'}
                        </td>
                        <td style={numStyle}>{m.row_count}</td>
                        <td style={numStyle}>{formatUsd(m.est_acv_total)}</td>
                        <td style={numStyle}>{formatUsd(m.est_tcv_total)}</td>
                        <td style={tdStyle} data-testid={`intelligence-import-matched-tech-${m.customer_id}`}>
                          {(m.technologies ?? []).length ? m.technologies.join(', ') : '—'}
                        </td>
                        <td style={tdStyle}>
                          {onOpenCustomer && (
                            <button role="button" aria-label={`Open ${m.customer_name}`} style={linkBtn} onClick={() => onOpenCustomer(m.customer_name)}>
                              open →
                            </button>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
            {detail.matched_out_of_scope > 0 && (
              <p data-testid="intelligence-import-out-of-scope" style={{ margin: '10px 0 0', fontSize: '0.8rem', color: 'var(--neutral-500)' }}>
                {detail.matched_out_of_scope} matched account{detail.matched_out_of_scope === 1 ? '' : 's'} outside your scope {detail.matched_out_of_scope === 1 ? 'is' : 'are'} not shown.
              </p>
            )}
          </section>

          <section style={cardStyle} data-testid="intelligence-import-detail-unmatched" aria-label="Unmatched accounts">
            <h3 style={{ margin: '0 0 8px', fontSize: '1rem', color: 'var(--neutral-700)' }}>
              Unmatched accounts ({detail.unmatched.length})
            </h3>
            {detail.skipped_rows > 0 && (
              <p data-testid="intelligence-import-detail-unmatched-warning" style={{ ...warningStyle, margin: '0 0 10px' }}>
                ⚠ {unmatchedRowsWarning(detail.skipped_rows)} To import them, add the account name as an alias on the customer and re-upload the file.
              </p>
            )}
            {detail.unmatched.length === 0 ? (
              <p style={{ margin: 0, color: 'var(--neutral-500)' }}>Every account matched.</p>
            ) : (
              <div style={{ overflowX: 'auto' }}>
                <table style={{ width: '100%', borderCollapse: 'collapse' }}>
                  <thead>
                    <tr style={{ borderBottom: '2px solid var(--divider)' }}>
                      <th style={thStyle}>Account</th>
                      <th style={thStyle}>Reason</th>
                      <th style={{ ...thStyle, textAlign: 'right' }}>Rows</th>
                    </tr>
                  </thead>
                  <tbody>
                    {detail.unmatched.map((u) => (
                      <tr key={u.account_name} data-testid={`intelligence-import-unmatched-${u.account_name}`} style={{ borderBottom: '1px solid var(--neutral-100)' }}>
                        <td style={tdStyle}>{u.account_name}</td>
                        <td style={tdStyle}>{UNMATCHED_REASON[u.reason] ?? UNMATCHED_REASON.unmatched}</td>
                        <td style={numStyle}>{u.row_count}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>

          {(detail.amount_issues ?? []).length > 0 && (
            <section style={cardStyle} data-testid="intelligence-import-detail-amounts" aria-label="Unreadable amounts">
              <h3 style={{ margin: '0 0 8px', fontSize: '1rem', color: 'var(--neutral-700)' }}>
                Unreadable amounts ({detail.amount_issues.length})
              </h3>
              <p style={{ margin: '0 0 10px', fontSize: '0.85rem', color: 'var(--neutral-500)' }}>
                These rows were imported with the amount recorded as unknown.
              </p>
              <div style={{ overflowX: 'auto' }}>
                <table style={{ width: '100%', borderCollapse: 'collapse' }}>
                  <thead>
                    <tr style={{ borderBottom: '2px solid var(--divider)' }}>
                      <th style={{ ...thStyle, textAlign: 'right' }}>File row</th>
                      <th style={thStyle}>Column</th>
                      <th style={thStyle}>Value</th>
                    </tr>
                  </thead>
                  <tbody>
                    {detail.amount_issues.map((a) => (
                      <tr key={`${a.source_row}-${a.column}`} style={{ borderBottom: '1px solid var(--neutral-100)' }}>
                        <td style={numStyle}>{a.source_row}</td>
                        <td style={tdStyle}>{a.column}</td>
                        <td style={tdStyle}>{a.value}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </section>
          )}
        </div>
      )}
    </div>
  );
}

export default RedHatPipelinePane;
