/**
 * NetSuite — NetSuite Intelligence Import pane of the Intelligence Import
 * surface: upload a NetSuite/distributor subscription billing export
 * (.csv/.xlsx), review the result summary, browse history, inspect an
 * import's read-only unmatched rows, and Re-match the stored rows after
 * names/aliases/access change (no re-upload).
 *
 * Manager-only: the backend 403s for every role other than system
 * admins and sales managers, so any 403 renders the access-denied state.
 *
 * Invariants the pane must preserve:
 * - NEVER creates customers and NEVER offers to create an alias — unmatched
 *   rows are expected; users add aliases themselves in More → Edit Customer
 *   and then use Re-match.
 * - Financial columns are ignored and the uploaded file is not stored; the
 *   pane states that visibly.
 */
import { useCallback, useEffect, useRef, useState } from 'react';
import { api } from '../../lib/api';
import { ActionButton } from '../ActionButton';
import { useImportDetailLink } from './useImportDetailLink';
import { formatDate } from '../../lib/pipelineFormat';
import type {
  NetSuiteDisposition,
  NetSuiteImportDetail,
  NetSuiteImportSummary,
} from '../../types/netsuite_import';
import { cardStyle, thStyle, tdStyle, numStyle, linkBtn, warningStyle, isForbidden } from './shared';

const DISPOSITION_LABEL: Record<NetSuiteDisposition, string> = {
  created: 'Created',
  refreshed: 'Refreshed',
  associated: 'Associated',
  skipped: 'Skipped',
  customer_deleted: 'Customer deleted',
};

const STATUS_LABEL: Record<string, string> = {
  complete: 'Completed',
  complete_with_skips: 'Completed with skipped rows',
};

function statusLabel(status: string): string {
  return STATUS_LABEL[status] ?? status;
}

/** Factual guidance for skipped rows — describes the manual alias path,
 *  never offers to create one (the import never creates aliases). */
function unmatchedGuidance(): string {
  return 'The import never creates customers or aliases. If a supplied name should match an existing account, add that name as an alias in More → Edit Customer, then use Re-match.';
}

export function NetSuiteImportPane() {
  const [history, setHistory] = useState<NetSuiteImportSummary[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [denied, setDenied] = useState(false);
  const [file, setFile] = useState<File | null>(null);
  const [uploading, setUploading] = useState(false);
  const [result, setResult] = useState<NetSuiteImportDetail | null>(null);
  const [detail, setDetail] = useState<NetSuiteImportDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailId, setDetailId] = useImportDetailLink();
  const [rematching, setRematching] = useState(false);
  const fileInputRef = useRef<HTMLInputElement | null>(null);

  const loadHistory = useCallback(async () => {
    try {
      setHistory(await api.listNetSuiteImports());
    } catch (err) {
      if (isForbidden(err)) { setDenied(true); return; }
      setError(err instanceof Error ? err.message : 'Failed to load import history');
    } finally {
      setLoaded(true);
    }
  }, []);

  useEffect(() => { void loadHistory(); }, [loadHistory]);

  const handleUpload = async () => {
    if (!file) return;
    setUploading(true); setError(null); setNotice(null);
    try {
      const res = await api.uploadNetSuiteImport(file);
      setResult(res); setFile(null);
      if (fileInputRef.current) fileInputRef.current.value = '';
      await loadHistory();
    } catch (err) {
      if (isForbidden(err)) { setDenied(true); return; }
      setError(err instanceof Error ? err.message : 'Import failed');
    } finally { setUploading(false); }
  };

  // Restores a linked record (?import=<id>); 404 = removed or out of scope.
  useEffect(() => {
    let active = true;
    setDetail(null); setError(null);
    if (detailId === null) { setDetailLoading(false); return () => { active = false; }; }
    setDetailLoading(true);
    const id = detailId;
    api.getNetSuiteImport(id).then((value) => { if (active) setDetail(value); })
      .catch((err: unknown) => {
        if (!active) return;
        if (isForbidden(err)) { setDenied(true); return; }
        const status = (err as { status?: number } | null)?.status;
        setError(status === 404 ? 'Import not found or unavailable.' : (err instanceof Error ? err.message : 'Failed to load import detail'));
      })
      .finally(() => { if (active) setDetailLoading(false); });
    return () => { active = false; };
  }, [detailId]);

  const handleRematch = async () => {
    if (!detail || rematching) return;
    setRematching(true); setError(null); setNotice(null);
    try {
      const res = await api.rematchNetSuiteImport(detail.import_id);
      setDetail(res);
      if (result?.import_id === res.import_id) setResult(res);
      setNotice(`Re-matched ${res.file_name}: ${res.matched_rows} of ${res.total_rows} rows now match ${res.matched_accounts} customer${res.matched_accounts === 1 ? '' : 's'}.`);
      await loadHistory();
    } catch (err) {
      if (isForbidden(err)) { setDenied(true); return; }
      setError(err instanceof Error ? err.message : 'Re-match failed');
    } finally { setRematching(false); }
  };

  if (denied) {
    return (
      <div role="alert" data-testid="netsuite-import-denied" style={{ ...cardStyle, color: 'var(--neutral-700)' }}>
        Requires a system admin or sales manager.
      </div>
    );
  }

  const unmatchedRows = detail ? detail.skipped : [];

  return (
    <div data-testid="netsuite-import">
      <p style={{ color: 'var(--neutral-500)', margin: '0 0 16px', fontSize: '0.9rem' }}>
        Upload a NetSuite or distributor subscription billing export (.csv or .xlsx). Rows are matched to existing customers by End Customer Name — the customer name or an alias, case-insensitive. No customers are created and no money is imported.
      </p>
      <p data-testid="netsuite-import-privacy" style={{ margin: '0 0 16px', fontSize: '0.8rem', color: 'var(--neutral-500)' }}>
        Pricing and other financial columns are ignored, and the uploaded file is not stored.
      </p>

      {error && (
        <div role="alert" aria-live="assertive" data-testid="netsuite-import-error" style={{ padding: '10px 14px', background: 'var(--status-negative-soft)', color: 'var(--status-negative)', borderLeft: '4px solid var(--status-negative)', marginBottom: '16px', fontWeight: 500 }}>
          {error}
        </div>
      )}
      {notice && (
        <div role="status" aria-live="polite" data-testid="netsuite-import-notice" style={{ padding: '10px 14px', background: 'var(--status-positive-soft)', color: 'var(--status-positive)', borderLeft: '4px solid var(--status-positive)', marginBottom: '16px', fontWeight: 500 }}>
          {notice}
        </div>
      )}

      <section style={cardStyle} data-testid="netsuite-import-upload" aria-label="Upload NetSuite subscription report">
        <div style={{ display: 'flex', gap: '12px', alignItems: 'center', flexWrap: 'wrap' }}>
          <input
            ref={fileInputRef}
            type="file"
            accept=".csv,.xlsx"
            aria-label="NetSuite subscription report (.csv or .xlsx)"
            data-testid="netsuite-import-file"
            onChange={(e) => setFile(e.target.files?.[0] ?? null)}
          />
          <ActionButton
            data-testid="netsuite-import-submit"
            disabled={!file}
            busy={uploading}
            onClick={handleUpload}
          >
            Import report
          </ActionButton>
        </div>
        {result && (
          <div data-testid="netsuite-import-summary" role="status" style={{ marginTop: '14px', fontSize: '0.9rem', color: 'var(--neutral-700)' }}>
            <div>
              Imported <strong>{result.file_name}</strong> — <strong>{statusLabel(result.status)}</strong>
            </div>
            <div data-testid="netsuite-import-summary-rows">
              {result.total_rows} rows read — {result.matched_rows} rows matched {result.matched_accounts} customer{result.matched_accounts === 1 ? '' : 's'}.
            </div>
            <div data-testid="netsuite-import-summary-tech">
              Technologies: {result.technologies_created} created, {result.technologies_refreshed} refreshed, {result.technologies_associated} associated.
            </div>
            <div data-testid="netsuite-import-summary-risks">
              Risks: {result.risks_created} raised, {result.risks_refreshed} refreshed.
            </div>
            {result.skipped_rows > 0 && (
              <div data-testid="netsuite-import-unmatched-warning" style={warningStyle}>
                ⚠ {result.skipped_rows} row{result.skipped_rows === 1 ? '' : 's'} skipped — unmatched, ambiguous or inaccessible customers, or unclassified products. The rest of the file imported; no customers were created.
              </div>
            )}
          </div>
        )}
      </section>

      <section style={cardStyle} data-testid="netsuite-import-history" aria-label="NetSuite import history">
        <h3 style={{ margin: '0 0 8px', fontSize: '1rem', color: 'var(--neutral-700)' }}>Import history</h3>
        {!loaded ? (
          <div role="status" style={{ color: 'var(--neutral-500)' }}>Loading import history…</div>
        ) : history.length === 0 ? (
          <p data-testid="netsuite-import-history-empty" style={{ margin: 0, color: 'var(--neutral-500)' }}>No NetSuite imports yet.</p>
        ) : (
          <div style={{ overflowX: 'auto' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse' }}>
              <thead>
                <tr style={{ borderBottom: '2px solid var(--divider)' }}>
                  <th style={thStyle}>File</th>
                  <th style={thStyle}>Imported at</th>
                  <th style={thStyle}>Imported by</th>
                  <th style={{ ...thStyle, textAlign: 'right' }}>Rows</th>
                  <th style={{ ...thStyle, textAlign: 'right' }}>Matched</th>
                  <th style={{ ...thStyle, textAlign: 'right' }}>Skipped</th>
                  <th style={{ ...thStyle, textAlign: 'right' }}>Techs</th>
                  <th style={{ ...thStyle, textAlign: 'right' }}>Risks</th>
                  <th style={thStyle}>Status</th>
                  <th style={thStyle} aria-hidden="true"></th>
                </tr>
              </thead>
              <tbody>
                {history.map((h) => (
                  <tr
                    key={h.import_id}
                    data-testid={`netsuite-import-row-${h.import_id}`}
                    onClick={() => setDetailId(h.import_id)}
                    style={{ borderBottom: '1px solid var(--neutral-100)', cursor: 'pointer', background: detail?.import_id === h.import_id ? 'var(--neutral-50)' : undefined }}
                  >
                    <td style={tdStyle}>{h.file_name}</td>
                    <td style={tdStyle}>{formatDate(h.created_at)}</td>
                    <td style={tdStyle}>{h.imported_by}</td>
                    <td style={numStyle}>{h.total_rows}</td>
                    <td style={numStyle}>{h.matched_rows}</td>
                    <td style={numStyle}>{h.skipped_rows}</td>
                    <td style={numStyle}>{h.technologies_created + h.technologies_refreshed + h.technologies_associated}</td>
                    <td style={numStyle}>{h.risks_created + h.risks_refreshed}</td>
                    <td style={tdStyle}>{statusLabel(h.status)}</td>
                    <td style={tdStyle}>
                      <button
                        role="button"
                        aria-label={`Open NetSuite import ${h.file_name}`}
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
        <div data-testid="netsuite-import-detail">
          <section style={cardStyle} aria-label="NetSuite import detail">
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: '12px', flexWrap: 'wrap', marginBottom: '8px' }}>
              <h3 style={{ margin: 0, fontSize: '1rem', color: 'var(--neutral-700)' }}>
                {detail.file_name} — {statusLabel(detail.status)}
              </h3>
              <ActionButton
                variant="secondary"
                data-testid="netsuite-import-rematch"
                busy={rematching}
                onClick={handleRematch}
              >
                Re-match
              </ActionButton>
            </div>
            <p style={{ margin: '0 0 4px', fontSize: '0.85rem', color: 'var(--neutral-700)' }}>
              {detail.total_rows} rows — {detail.matched_rows} matched {detail.matched_accounts} customer{detail.matched_accounts === 1 ? '' : 's'}, {detail.skipped_rows} skipped.
              Technologies (latest action): {detail.technologies_created} created, {detail.technologies_refreshed} refreshed, {detail.technologies_associated} associated.
              Risks on record: {detail.risks}.
            </p>
            <p data-testid="netsuite-import-rematch-help" style={{ margin: '0 0 4px', fontSize: '0.8rem', color: 'var(--neutral-500)' }}>
              Re-match re-applies the stored rows using current customer names, aliases and access — no re-upload. Rows already applied keep their customer.
            </p>
            {detail.invoice_date && (
              <p style={{ margin: 0, fontSize: '0.8rem', color: 'var(--neutral-500)' }}>
                Latest invoice date in the file: {detail.invoice_date}. Imported {formatDate(detail.created_at)} by {detail.imported_by}.
              </p>
            )}
          </section>

          <section style={cardStyle} data-testid="netsuite-import-unmatched" aria-label="Unmatched rows">
            <h3 style={{ margin: '0 0 8px', fontSize: '1rem', color: 'var(--neutral-700)' }}>
              Unmatched rows ({unmatchedRows.length})
            </h3>
            {unmatchedRows.length === 0 ? (
              <p data-testid="netsuite-import-unmatched-empty" style={{ margin: 0, color: 'var(--neutral-500)' }}>All rows matched.</p>
            ) : (
              <>
                <div style={{ overflowX: 'auto' }}>
                  <table style={{ width: '100%', borderCollapse: 'collapse' }}>
                    <thead>
                      <tr style={{ borderBottom: '2px solid var(--divider)' }}>
                        <th style={{ ...thStyle, textAlign: 'right' }}>Row</th>
                        <th style={thStyle}>Supplied name</th>
                        <th style={thStyle}>Product</th>
                        <th style={thStyle}>Disposition</th>
                        <th style={thStyle}>Reason</th>
                        <th style={thStyle}>Suggestion</th>
                      </tr>
                    </thead>
                    <tbody>
                      {unmatchedRows.map((row) => (
                        <tr key={row.id} data-testid={`netsuite-import-unmatched-${row.id}`} style={{ borderBottom: '1px solid var(--neutral-100)' }}>
                          <td style={numStyle}>{row.source_row}</td>
                          <td style={tdStyle}>{row.customer_name || '(blank)'}</td>
                          <td style={tdStyle}>{row.product ?? '—'}</td>
                          <td style={tdStyle}>{DISPOSITION_LABEL[row.disposition] ?? row.disposition}</td>
                          <td style={tdStyle}>{row.reason ?? '—'}</td>
                          <td style={tdStyle}>{row.suggestion ? `Possible match: ${row.suggestion.customer_name}` : '—'}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                <p style={{ margin: '10px 0 0', fontSize: '0.8rem', color: 'var(--neutral-500)' }}>
                  {unmatchedGuidance()}
                </p>
              </>
            )}
          </section>
        </div>
      )}
    </div>
  );
}

export default NetSuiteImportPane;
