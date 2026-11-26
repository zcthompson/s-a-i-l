/**
 * Rep Provided — Generic Account Intelligence (CSV) pane of the Intelligence
 * Import surface: download the header-only template, upload a rep-supplied
 * CSV, review the partial-success summary, browse persistent history, inspect
 * an import's per-row issues + matched customers, and (importer/admin only)
 * download the retained source / issue report or delete the import.
 *
 * Open to every authenticated user — there is NO manager-only denied state:
 * rows the caller cannot write to come back skipped from the backend and the
 * summary/history/detail render that honestly.
 */
import { useCallback, useEffect, useRef, useState } from 'react';
import { api } from '../../lib/api';
import { useImportDetailLink } from './useImportDetailLink';
import { formatDate } from '../../lib/pipelineFormat';
import type {
  RepIntelligenceDetail,
  RepIntelligenceResult,
  RepIntelligenceSummary,
} from '../../types/rep_intelligence';
import { cardStyle, thStyle, tdStyle, numStyle, linkBtn, warningStyle, unmatchedRowsWarning } from './shared';

interface GenericRepIntelligencePaneProps {
  /** Open a customer's dashboard (sets the selected customer + view). */
  onOpenCustomer?: (name: string) => void;
}

const TEMPLATE_FILENAME = 'sail-account-intelligence-template.csv';

const FIELD_GUIDANCE: { column: string; required: boolean; guidance: string }[] = [
  { column: 'customer_name', required: true, guidance: 'Customer name or alias (case-insensitive). Unmatched, ambiguous or inaccessible accounts are skipped and reported; the rest of the file imports.' },
  { column: 'technology_name', required: true, guidance: 'Technology, product or platform name as you know it.' },
  { column: 'hardware_software', required: false, guidance: "'hardware' or 'software'. Blank = unknown." },
  { column: 'is_sale', required: false, guidance: "'yes' or 'no'. Blank = unknown (not 'no')." },
  { column: 'amount', required: false, guidance: 'Decimal; $ and , are ignored. Blank = unknown (not zero).' },
  { column: 'currency', required: false, guidance: '3-letter code such as USD. Blank = unknown.' },
  { column: 'vendor', required: false, guidance: 'Free text. Blank = unknown.' },
  { column: 'version', required: false, guidance: 'Free text. Blank = unknown.' },
  { column: 'quantity', required: false, guidance: 'Whole number; 0 is a recorded zero. Blank = unknown.' },
  { column: 'notes', required: false, guidance: 'Your context, kept verbatim. Nothing is derived from it.' },
];

const STATUS_LABEL: Record<string, string> = {
  completed: 'Completed',
  completed_with_issues: 'Completed with issues',
  failed: 'Failed (no rows imported)',
};

function saveBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

function statusLabel(status: string): string {
  return STATUS_LABEL[status] ?? status;
}

function severityColor(severity: string): string {
  if (severity === 'error') return 'var(--status-negative)';
  if (severity === 'warning') return 'var(--status-warning, var(--neutral-700))';
  return 'var(--neutral-500)';
}

export function GenericRepIntelligencePane({ onOpenCustomer }: GenericRepIntelligencePaneProps = {}) {
  const [history, setHistory] = useState<RepIntelligenceSummary[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [file, setFile] = useState<File | null>(null);
  const [uploading, setUploading] = useState(false);
  const [result, setResult] = useState<RepIntelligenceResult | null>(null);
  const [detail, setDetail] = useState<RepIntelligenceDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailId, setDetailId] = useImportDetailLink();
  const [deleting, setDeleting] = useState(false);
  const [downloading, setDownloading] = useState(false);
  const fileInputRef = useRef<HTMLInputElement | null>(null);

  const loadHistory = useCallback(async () => {
    try {
      setHistory(await api.listRepIntelligenceImports());
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load import history');
    } finally {
      setLoaded(true);
    }
  }, []);

  useEffect(() => { void loadHistory(); }, [loadHistory]);

  const runDownload = async (fetcher: () => Promise<Blob>, filename: string, failure: string) => {
    setDownloading(true);
    setError(null);
    try {
      saveBlob(await fetcher(), filename);
    } catch (err) {
      setError(err instanceof Error ? err.message : failure);
    } finally {
      setDownloading(false);
    }
  };

  const handleUpload = async () => {
    if (!file) return;
    setUploading(true);
    setError(null);
    setNotice(null);
    try {
      const res = await api.uploadRepIntelligenceImport(file);
      setResult(res);
      setFile(null);
      if (fileInputRef.current) fileInputRef.current.value = '';
      await loadHistory();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Import failed');
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
    api.getRepIntelligenceImport(id).then((value) => { if (active) setDetail(value); })
      .catch((err: unknown) => { if (active) { if ((err as { status?: number } | null)?.status === 404 || (err as { status?: number } | null)?.status === 403) setError('Import not found or unavailable.');
        else setError(err instanceof Error ? err.message : 'Failed to load import detail'); } })
      .finally(() => { if (active) setDetailLoading(false); });
    return () => { active = false; };
  }, [detailId]);

  const handleDelete = async () => {
    if (!detail) return;
    if (!window.confirm(`Delete import "${detail.file_name}"? This removes its rows and the technology records it currently owns. Manual and other-source records are kept.`)) return;
    setDeleting(true);
    setError(null);
    try {
      const res = await api.deleteRepIntelligenceImport(detail.import_id);
      setNotice(`Import deleted (${res.deleted_rows} rows, ${res.deleted_technologies} technology records removed).`);
      if (result?.import_id === detail.import_id) setResult(null);
      setDetail(null);
      setDetailId(null);
      await loadHistory();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Delete failed');
    } finally {
      setDeleting(false);
    }
  };

  const detailIssues = detail
    ? detail.rows.flatMap((r) => r.issues.map((issue, i) => ({ row: r, issue, key: `${r.id}-${i}` })))
    : [];
  const cleanRows = detail ? detail.rows.filter((r) => r.issues.length === 0).length : 0;

  return (
    <div data-testid="rep-intel">
      <p style={{ color: 'var(--neutral-500)', margin: '0 0 16px', fontSize: '0.9rem' }}>
        Upload account intelligence you collected (.csv). Rows are matched to customers you can access by customer name or alias (case-insensitive); problem rows are skipped and reported while the rest import. No customers are created. Imported technologies are recorded as unverified rep observations.
      </p>

      {error && (
        <div role="alert" aria-live="assertive" data-testid="rep-intel-error" style={{ padding: '10px 14px', background: 'var(--status-negative-soft)', color: 'var(--status-negative)', borderLeft: '4px solid var(--status-negative)', marginBottom: '16px', fontWeight: 500 }}>
          {error}
        </div>
      )}
      {notice && (
        <div role="status" aria-live="polite" data-testid="rep-intel-notice" style={{ padding: '10px 14px', background: 'var(--status-positive-soft)', color: 'var(--status-positive)', borderLeft: '4px solid var(--status-positive)', marginBottom: '16px', fontWeight: 500 }}>
          {notice}
        </div>
      )}

      <section style={cardStyle} data-testid="rep-intel-guidance" aria-label="Field guidance">
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: '12px', flexWrap: 'wrap', marginBottom: '8px' }}>
          <h3 style={{ margin: 0, fontSize: '1rem', color: 'var(--neutral-700)' }}>CSV columns</h3>
          <button
            role="button"
            aria-label="Download template"
            data-testid="rep-intel-template"
            disabled={downloading}
            onClick={() => void runDownload(() => api.downloadRepIntelligenceTemplate(), TEMPLATE_FILENAME, 'Template download failed')}
            style={{ padding: '6px 14px', borderRadius: 'var(--radius)', border: '1px solid var(--brand-500)', background: 'var(--neutral-0)', color: 'var(--brand-700)', cursor: downloading ? 'not-allowed' : 'pointer' }}
          >
            Download template
          </button>
        </div>
        <div style={{ overflowX: 'auto' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse' }}>
            <thead>
              <tr style={{ borderBottom: '2px solid var(--divider)' }}>
                <th style={thStyle}>Column</th>
                <th style={thStyle}>Required</th>
                <th style={thStyle}>Guidance</th>
              </tr>
            </thead>
            <tbody>
              {FIELD_GUIDANCE.map((f) => (
                <tr key={f.column} data-testid={`rep-intel-guidance-${f.column}`} style={{ borderBottom: '1px solid var(--neutral-100)' }}>
                  <td style={{ ...tdStyle, fontFamily: 'monospace' }}>{f.column}</td>
                  <td style={{ ...tdStyle, fontWeight: f.required ? 600 : 400 }}>{f.required ? 'Required' : 'Optional'}</td>
                  <td style={tdStyle}>{f.guidance}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p style={{ margin: '10px 0 0', fontSize: '0.8rem', color: 'var(--neutral-500)' }}>
          The template contains the header row only. Unknown extra columns are ignored; blank rows are skipped.
        </p>
      </section>

      <section style={cardStyle} data-testid="rep-intel-upload" aria-label="Upload account intelligence">
        <div style={{ display: 'flex', gap: '12px', alignItems: 'center', flexWrap: 'wrap' }}>
          <input
            ref={fileInputRef}
            type="file"
            accept=".csv"
            aria-label="Account intelligence CSV"
            data-testid="rep-intel-file"
            onChange={(e) => setFile(e.target.files?.[0] ?? null)}
          />
          <button
            role="button"
            aria-label="Import"
            data-testid="rep-intel-submit"
            disabled={!file || uploading}
            onClick={handleUpload}
            style={{ padding: '8px 16px', borderRadius: 'var(--radius)', border: 'none', background: 'var(--brand-500)', color: 'var(--neutral-0)', cursor: !file || uploading ? 'not-allowed' : 'pointer', opacity: !file || uploading ? 0.6 : 1 }}
          >
            {uploading ? 'Importing…' : 'Import'}
          </button>
        </div>
        {result && (
          <div data-testid="rep-intel-summary" role="status" style={{ marginTop: '14px', fontSize: '0.9rem', color: 'var(--neutral-700)' }}>
            <div>
              Imported <strong>{result.file_name}</strong> — <strong>{statusLabel(result.status)}</strong>
            </div>
            <div>
              {result.total_rows} rows processed — {result.imported_rows} imported, {result.imported_with_issues} imported with issues, {result.skipped_rows} skipped.
            </div>
            {(result.unmatched_customer_rows ?? 0) > 0 && (
              <div data-testid="rep-intel-unmatched-warning" style={warningStyle}>
                ⚠ {unmatchedRowsWarning(result.unmatched_customer_rows ?? 0)}
              </div>
            )}
            <div>
              Technologies: {result.technologies_created} created, {result.technologies_refreshed} refreshed.
            </div>
          </div>
        )}
      </section>

      <section style={cardStyle} data-testid="rep-intel-history" aria-label="Import history">
        <h3 style={{ margin: '0 0 8px', fontSize: '1rem', color: 'var(--neutral-700)' }}>Import history</h3>
        {!loaded ? (
          <div role="status" style={{ color: 'var(--neutral-500)' }}>Loading import history…</div>
        ) : history.length === 0 ? (
          <p data-testid="rep-intel-history-empty" style={{ margin: 0, color: 'var(--neutral-500)' }}>No imports yet.</p>
        ) : (
          <div style={{ overflowX: 'auto' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse' }}>
              <thead>
                <tr style={{ borderBottom: '2px solid var(--divider)' }}>
                  <th style={thStyle}>File</th>
                  <th style={thStyle}>Imported at</th>
                  <th style={thStyle}>Imported by</th>
                  <th style={{ ...thStyle, textAlign: 'right' }}>Rows</th>
                  <th style={{ ...thStyle, textAlign: 'right' }}>Imported</th>
                  <th style={{ ...thStyle, textAlign: 'right' }}>With issues</th>
                  <th style={{ ...thStyle, textAlign: 'right' }}>Skipped</th>
                  <th style={thStyle}>Status</th>
                  <th style={{ ...thStyle, textAlign: 'right' }}>Techs</th>
                  <th style={thStyle} aria-hidden="true"></th>
                </tr>
              </thead>
              <tbody>
                {history.map((h) => (
                  <tr
                    key={h.import_id}
                    data-testid={`rep-intel-row-${h.import_id}`}
                    onClick={() => setDetailId(h.import_id)}
                    style={{ borderBottom: '1px solid var(--neutral-100)', cursor: 'pointer', background: detail?.import_id === h.import_id ? 'var(--neutral-50)' : undefined }}
                  >
                    <td style={tdStyle}>{h.file_name}</td>
                    <td style={tdStyle}>{formatDate(h.created_at)}</td>
                    <td style={tdStyle}>{h.imported_by}</td>
                    <td style={numStyle}>{h.total_rows}</td>
                    <td style={numStyle}>{h.imported_rows}</td>
                    <td style={numStyle}>{h.imported_with_issues}</td>
                    <td style={numStyle}>{h.skipped_rows}</td>
                    <td style={tdStyle}>{statusLabel(h.status)}</td>
                    <td style={numStyle}>{h.technologies_created + h.technologies_refreshed}</td>
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
        <div data-testid="rep-intel-detail">
          <section style={cardStyle} aria-label="Import detail">
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: '12px', flexWrap: 'wrap', marginBottom: '8px' }}>
              <h3 style={{ margin: 0, fontSize: '1rem', color: 'var(--neutral-700)' }}>
                {detail.file_name} — {statusLabel(detail.status)}
              </h3>
              {detail.can_manage && (
                <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap' }}>
                  <button
                    role="button"
                    aria-label="Download source file"
                    data-testid="rep-intel-source"
                    disabled={downloading}
                    onClick={() => void runDownload(() => api.downloadRepIntelligenceSource(detail.import_id), detail.file_name, 'Source download failed')}
                    style={{ padding: '6px 14px', borderRadius: 'var(--radius)', border: '1px solid var(--divider)', background: 'var(--neutral-0)', color: 'var(--neutral-700)', cursor: downloading ? 'not-allowed' : 'pointer' }}
                  >
                    Download source
                  </button>
                  <button
                    role="button"
                    aria-label="Download issue report"
                    data-testid="rep-intel-issues-download"
                    disabled={downloading}
                    onClick={() => void runDownload(() => api.downloadRepIntelligenceIssues(detail.import_id), `import-${detail.import_id}-issues.csv`, 'Issue report download failed')}
                    style={{ padding: '6px 14px', borderRadius: 'var(--radius)', border: '1px solid var(--divider)', background: 'var(--neutral-0)', color: 'var(--neutral-700)', cursor: downloading ? 'not-allowed' : 'pointer' }}
                  >
                    Download issue report
                  </button>
                  <button
                    role="button"
                    aria-label="Delete import"
                    data-testid="rep-intel-delete"
                    disabled={deleting}
                    onClick={handleDelete}
                    style={{ padding: '6px 14px', borderRadius: 'var(--radius)', border: '1px solid var(--status-negative)', background: 'var(--neutral-0)', color: 'var(--status-negative)', cursor: deleting ? 'not-allowed' : 'pointer' }}
                  >
                    {deleting ? 'Deleting…' : 'Delete'}
                  </button>
                </div>
              )}
            </div>
            <p style={{ margin: 0, fontSize: '0.85rem', color: 'var(--neutral-700)' }}>
              {detail.total_rows} rows — {detail.imported_rows} imported, {detail.imported_with_issues} with issues, {detail.skipped_rows} skipped. Technologies: {detail.technologies_created} created, {detail.technologies_refreshed} refreshed.
            </p>
          </section>

          <section style={cardStyle} data-testid="rep-intel-detail-customers" aria-label="Matched customers">
            <h3 style={{ margin: '0 0 8px', fontSize: '1rem', color: 'var(--neutral-700)' }}>
              Matched customers ({detail.matched.length})
            </h3>
            {detail.matched.length === 0 ? (
              <p style={{ margin: 0, color: 'var(--neutral-500)' }}>No accessible customers matched.</p>
            ) : (
              <ul style={{ listStyle: 'none', margin: 0, padding: 0 }}>
                {detail.matched.map((m) => (
                  <li key={m.customer_id} data-testid={`rep-intel-customer-${m.customer_id}`} style={{ display: 'flex', gap: '12px', alignItems: 'center', padding: '6px 0', borderBottom: '1px solid var(--neutral-100)', fontSize: '0.85rem' }}>
                    <span>{m.customer_name}</span>
                    {onOpenCustomer && (
                      <button role="button" aria-label={`Open ${m.customer_name}`} style={linkBtn} onClick={() => onOpenCustomer(m.customer_name)}>
                        open →
                      </button>
                    )}
                  </li>
                ))}
              </ul>
            )}
            {detail.matched_out_of_scope > 0 && (
              <p data-testid="rep-intel-out-of-scope" style={{ margin: '10px 0 0', fontSize: '0.8rem', color: 'var(--neutral-500)' }}>
                {detail.matched_out_of_scope} matched account{detail.matched_out_of_scope === 1 ? '' : 's'} outside your scope {detail.matched_out_of_scope === 1 ? 'is' : 'are'} not shown.
              </p>
            )}
          </section>

          <section style={cardStyle} data-testid="rep-intel-detail-issues" aria-label="Row issues">
            <h3 style={{ margin: '0 0 8px', fontSize: '1rem', color: 'var(--neutral-700)' }}>
              Row issues ({detailIssues.length})
            </h3>
            {detailIssues.length === 0 ? (
              <p style={{ margin: 0, color: 'var(--neutral-500)' }}>No issues — every row imported cleanly.</p>
            ) : (
              <div style={{ overflowX: 'auto' }}>
                <table style={{ width: '100%', borderCollapse: 'collapse' }}>
                  <thead>
                    <tr style={{ borderBottom: '2px solid var(--divider)' }}>
                      <th style={{ ...thStyle, textAlign: 'right' }}>Row</th>
                      <th style={thStyle}>Customer</th>
                      <th style={thStyle}>Technology</th>
                      <th style={thStyle}>Field</th>
                      <th style={thStyle}>Reason</th>
                      <th style={thStyle}>Message</th>
                      <th style={thStyle}>Severity</th>
                      <th style={thStyle}>Disposition</th>
                    </tr>
                  </thead>
                  <tbody>
                    {detailIssues.map(({ row, issue, key }) => (
                      <tr key={key} data-testid={`rep-intel-issue-${key}`} style={{ borderBottom: '1px solid var(--neutral-100)' }}>
                        <td style={numStyle}>{row.source_row}</td>
                        <td style={tdStyle}>{row.customer_name ?? row.customer_name_supplied ?? '—'}</td>
                        <td style={tdStyle}>{row.technology_name_supplied ?? '—'}</td>
                        <td style={tdStyle}>{issue.field}</td>
                        <td style={{ ...tdStyle, fontFamily: 'monospace' }}>{issue.code}</td>
                        <td style={tdStyle}>{issue.message}</td>
                        <td style={{ ...tdStyle, color: severityColor(issue.severity), fontWeight: 600 }}>{issue.severity}</td>
                        <td style={tdStyle}>{issue.disposition}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
            <p data-testid="rep-intel-detail-clean" style={{ margin: '10px 0 0', fontSize: '0.8rem', color: 'var(--neutral-500)' }}>
              {cleanRows} row{cleanRows === 1 ? '' : 's'} imported with no issues.
            </p>
          </section>
        </div>
      )}
    </div>
  );
}

export default GenericRepIntelligencePane;
