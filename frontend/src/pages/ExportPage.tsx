import { ExportOption } from '../components/ExportOption';
import { SectionIcon } from '../components/SectionIcon';
/**
 * Export section parent page — exports a full customer assessment round
 * (active or archived) as a formatted PDF/Excel/CSV report.
 *
 * Flow: customer → assessment round → output format. Reports are scoped
 * to one assessment round on the server (every sheet of every format is
 * computed from the same scoped set), and the attachment name follows the
 * server's naming scheme: assessment_report_<customer>_<round>.
 */

import { useState, useEffect, useCallback } from 'react';
import type { CSSProperties } from 'react';
import { api } from '../lib/api';
import { CustomerAssessment } from '../types/use_case';

const FORMAT_LABELS: Record<'pdf' | 'excel' | 'csv', string> = { pdf: 'PDF', excel: 'Excel', csv: 'CSV' };
const FORMAT_EXT: Record<'pdf' | 'excel' | 'csv', string> = { pdf: 'pdf', excel: 'xlsx', csv: 'csv' };

interface ExportPageProps {
  initialFormat?: 'pdf' | 'excel' | 'csv';
}

// Mirrors the server's report naming (assessment_report_<customer>_<round>).
function slug(value: string): string {
  return value.toLowerCase().replace(/\s+/g, '_');
}

function reportName(customer: string, assessment: CustomerAssessment | null, format: 'pdf' | 'excel' | 'csv'): string {
  const date = new Date().toISOString().split('T')[0];
  const base = assessment
    ? `assessment_report_${slug(customer)}_${slug(assessment.name)}`
    : `assessment_report_${slug(customer)}`;
  return `${base}_${date}.${FORMAT_EXT[format]}`;
}

const labelStyle: CSSProperties = {
  display: 'block',
  marginBottom: '8px',
  fontSize: '0.9rem',
  fontWeight: 600,
  color: 'var(--ink)',
};

const selectStyle: CSSProperties = {
  padding: '10px 14px',
  border: '1px solid var(--divider)',
  borderRadius: 'var(--radius)',
  fontSize: '0.95rem',
  background: 'var(--neutral-0)',
  color: 'var(--ink)',
};

export function ExportPage({ initialFormat }: ExportPageProps = {}) {
  const [customers, setCustomers] = useState<any[]>([]);
  const [customerName, setCustomerName] = useState('');
  const [rounds, setRounds] = useState<CustomerAssessment[]>([]);
  const [assessmentId, setAssessmentId] = useState<number | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadingRounds, setLoadingRounds] = useState(false);
  const [exporting, setExporting] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  const selectedAssessment = rounds.find((r) => r.id === assessmentId) || null;
  const canExport = customerName !== '' && assessmentId !== null;

  // Customers (service-scoped: admin sees all, other users their own).
  useEffect(() => {
    api.listCustomers()
      .then((data) => setCustomers(data))
      .catch((err) => setError(err instanceof Error ? err.message : 'Failed to load customers'))
      .finally(() => setLoading(false));
  }, []);

  // Rounds for the selected customer: active first, then newest first.
  const loadRounds = useCallback((name: string) => {
    setLoadingRounds(true);
    setError(null);
    setRounds([]);
    setAssessmentId(null);
    api.listAssessments(name)
      .then((data: CustomerAssessment[]) => {
        const sorted = [...data].sort((a, b) => {
          if (a.status !== b.status) return a.status === 'active' ? -1 : 1;
          return String(b.created_at || '').localeCompare(String(a.created_at || ''));
        });
        setRounds(sorted);
        const preferred = sorted.find((r) => r.status === 'active') || sorted[0];
        setAssessmentId(preferred ? preferred.id : null);
      })
      .catch((err) => {
        setError(err instanceof Error ? err.message : 'Failed to load assessment rounds');
      })
      .finally(() => setLoadingRounds(false));
  }, []);

  const handleCustomerChange = (name: string) => {
    setCustomerName(name);
    if (name) loadRounds(name);
  };

  const handleExport = async (format: 'pdf' | 'excel' | 'csv') => {
    if (!canExport) return;
    try {
      setExporting(format);
      setError(null);
      setSuccess(null);
      const call =
        format === 'pdf' ? api.exportPdf : format === 'excel' ? api.exportExcel : api.exportCSV;
      const blob: Blob = await call(customerName, undefined, assessmentId ?? undefined);
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = reportName(customerName, selectedAssessment, format);
      a.click();
      window.URL.revokeObjectURL(url);
      setSuccess(`${FORMAT_LABELS[format]} report downloaded successfully.`);
    } catch (err) {
      setError(err instanceof Error ? err.message : `${FORMAT_LABELS[format]} export failed`);
    } finally {
      setExporting(null);
    }
  };

  if (loading) {
    return (
      <div role="status" style={{ padding: '2rem', textAlign: 'center', color: 'var(--brand-700)' }}>
        Loading export options...
      </div>
    );
  }

  return (
    <div style={{ padding: '2rem', maxWidth: '800px', margin: '0 auto' }}>
      <h2 style={{ color: 'var(--ink)', marginBottom: '12px', fontSize: '1.4rem' }}>
        <SectionIcon name="📤" /> Export{initialFormat ? ` — ${FORMAT_LABELS[initialFormat]}` : ''}
      </h2>
      <p style={{ color: 'var(--neutral-500)', marginBottom: '24px', fontSize: '0.95rem', lineHeight: 1.5 }}>
        Export a full customer assessment — an active or archived round — as a formatted report.
        The report contains exactly the selected round's use cases; every sheet is computed from
        the same scoped set.
        {initialFormat && (
          <span style={{ display: 'block', marginTop: '4px', fontSize: '0.85rem', color: 'var(--brand-700)' }}>
            Focused format: {FORMAT_LABELS[initialFormat]} — other formats below.
          </span>
        )}
      </p>

      {error && (
        <div role="alert" style={{
          padding: '12px 16px',
          background: 'var(--status-negative-soft)',
          borderLeft: '4px solid var(--status-negative)',
          borderRadius: 'var(--radius-sm)',
          marginBottom: '16px',
          color: 'var(--status-negative)',
          fontSize: '0.9rem',
        }}>
          {error}
        </div>
      )}

      {success && (
        <div role="status" style={{
          padding: '12px 16px',
          background: 'var(--status-positive-soft)',
          borderLeft: '4px solid var(--status-positive)',
          borderRadius: 'var(--radius-sm)',
          marginBottom: '16px',
          color: 'var(--status-positive)',
          fontSize: '0.9rem',
        }}>
          {success}
        </div>
      )}

      {exporting && <p role="status" style={{ color: 'var(--neutral-600)', fontSize: '.9rem' }}>Preparing {FORMAT_LABELS[exporting as keyof typeof FORMAT_LABELS]} report…</p>}
      {/* Step 1 — customer */}
      <div style={{ marginBottom: '20px' }}>
        <label htmlFor="export-customer" style={labelStyle}>
          1. Customer
        </label>
        <select
          id="export-customer"
          aria-label="Select customer to export"
          value={customerName}
          onChange={(e) => handleCustomerChange(e.target.value)}
          style={{ width: '100%', boxSizing: 'border-box', ...selectStyle }}
        >
          <option value="">{customers.length ? 'Select a customer…' : 'No customers available'}</option>
          {customers.map((c) => (
            <option key={c.id} value={c.name}>{c.name}</option>
          ))}
        </select>
      </div>

      {/* Step 2 — assessment round */}
      {customerName !== '' && (
        <div style={{ marginBottom: '20px' }}>
          <label htmlFor="export-round" style={labelStyle}>
            2. Assessment round
          </label>
          <div style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: '10px' }}>
            <select
              id="export-round"
              aria-label="Select assessment round to export"
              value={assessmentId ?? ''}
              onChange={(e) => setAssessmentId(e.target.value ? Number(e.target.value) : null)}
              disabled={loadingRounds || rounds.length === 0}
              style={{
                flex: '1 1 240px',
                minWidth: 0,
                maxWidth: '100%',
                ...selectStyle,
                opacity: loadingRounds || rounds.length === 0 ? 0.6 : 1,
                cursor: loadingRounds || rounds.length === 0 ? 'not-allowed' : 'pointer',
              }}
            >
              <option value="">
                {loadingRounds
                  ? 'Loading rounds…'
                  : rounds.length === 0
                    ? 'No assessment rounds yet for this customer'
                    : 'Select a round…'}
              </option>
              {rounds.map((r) => (
                <option key={r.id} value={r.id}>
                  {r.name} — {r.status === 'active' ? 'Active' : 'Archived'} ({r.use_case_count} use case{r.use_case_count === 1 ? '' : 's'})
                </option>
              ))}
            </select>
            {selectedAssessment && (
              <span style={{
                padding: '4px 12px',
                borderRadius: 'var(--radius)',
                fontSize: '0.75rem',
                fontWeight: 600,
                whiteSpace: 'nowrap',
                background: selectedAssessment.status === 'active' ? 'var(--status-positive-soft)' : 'var(--neutral-200)',
                color: selectedAssessment.status === 'active' ? 'var(--status-positive)' : 'var(--neutral-600)',
              }}>
                {selectedAssessment.status === 'active' ? '● Active' : '◼ Archived'}
              </span>
            )}
          </div>
        </div>
      )}

      {/* Step 3 — output format */}
      <div style={{ marginBottom: '12px', fontSize: '0.9rem', fontWeight: 600, color: 'var(--ink)' }}>
        3. Output format
      </div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
        <ExportOption label="Export report as PDF" title="Export PDF Report" icon="📄" description="Formatted PDF report for the selected assessment round" busy={exporting === 'pdf'} disabled={exporting !== null || !canExport} onClick={() => handleExport('pdf')} suggested={initialFormat === 'pdf'} />

        <ExportOption label="Export report as Excel" title="Export Excel" icon="📊" description="Multi-sheet Excel workbook for the selected assessment round" busy={exporting === 'excel'} disabled={exporting !== null || !canExport} onClick={() => handleExport('excel')} suggested={initialFormat === 'excel'} />

        <ExportOption label="Export report as CSV" title="Export CSV" icon="📋" description="CSV of the selected round’s use cases for spreadsheet use" busy={exporting === 'csv'} disabled={exporting !== null || !canExport} onClick={() => handleExport('csv')} suggested={initialFormat === 'csv'} />
      </div>
    </div>
  );
}
export default ExportPage;
