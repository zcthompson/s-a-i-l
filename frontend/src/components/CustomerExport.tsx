import { ActionButton } from './ActionButton';
import { ExportOption } from './ExportOption';
import { SectionIcon } from './SectionIcon';
/**
 * Customer Export component — exports only the selected customer's use cases.
 */

import { useState } from 'react';
import { api } from '../lib/api';
import { Customer } from '../types/use_case';
import { UseCase } from '../types/use_case';

interface CustomerExportProps {
  customer: Customer;
  useCases: UseCase[];
  onBack: () => void;
}

export function CustomerExport({ customer, useCases, onBack }: CustomerExportProps) {
  const [exporting, setExporting] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  const handleExportPdf = async () => {
    try {
      setExporting("pdf");
      setError(null);
      setSuccess(null);

      const blob = await api.exportPdf(customer.name);
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `export_${customer.name.replace(/\s+/g, '_')}_report_${new Date().toISOString().split('T')[0]}.pdf`;
      a.click();
      window.URL.revokeObjectURL(url);
      setSuccess('PDF report downloaded successfully.');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'PDF export failed');
    } finally {
      setExporting(null);
    }
  };

  const handleExportExcel = async () => {
    try {
      setExporting("excel");
      setError(null);
      setSuccess(null);

      const blob = await api.exportExcel(customer.name);
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `export_${customer.name.replace(/\s+/g, '_')}_report_${new Date().toISOString().split('T')[0]}.xlsx`;
      a.click();
      window.URL.revokeObjectURL(url);
      setSuccess('Excel report downloaded successfully.');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Excel export failed');
    } finally {
      setExporting(null);
    }
  };

  const handleExportCsv = async () => {
    try {
      setExporting("csv");
      setError(null);
      setSuccess(null);

      const blob = await api.exportCSV(customer.name);
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `export_${customer.name.replace(/\s+/g, '_')}_report_${new Date().toISOString().split('T')[0]}.csv`;
      a.click();
      window.URL.revokeObjectURL(url);
      setSuccess('CSV report downloaded successfully.');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'CSV export failed');
    } finally {
      setExporting(null);
    }
  };

  return (
    <div style={{ maxWidth: '600px', margin: '0 auto', padding: '24px' }}>
      {/* Back button */}
      <div style={{ marginBottom: '16px' }}>
        <ActionButton variant="quiet" role="button" aria-label="Back to customer dashboard"
          onClick={onBack}
        >
          ← Back to {customer.name}
        </ActionButton>
      </div>

      <h2 style={{ color: 'var(--ink)', marginBottom: '12px', fontSize: '1.4rem' }}>
        <SectionIcon name="📤" /> Export — {customer.name}
      </h2>
      <p style={{ color: 'var(--neutral-500)', marginBottom: '24px', fontSize: '0.95rem', lineHeight: 1.5 }}>
        Export all use cases and scoring data for <strong>{customer.name}</strong> ({useCases.length} use cases).
      </p>

      {error && (
        <div role="alert" aria-live="assertive" style={{
          padding: '12px 16px',
          background: 'var(--status-negative-soft)',
          borderLeft: '4px solid var(--status-negative)',
          borderRadius: 'var(--radius-sm)',
          marginBottom: '16px',
          color: 'var(--status-negative)',
          fontSize: '0.9rem',
        }}>
          <span aria-hidden="true">⚠️ </span>{error}
        </div>
      )}

      {success && (
        <div role="status" aria-live="polite" style={{
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
      {exporting && <div role="status" aria-live="polite" style={{ padding: '12px', textAlign: 'center', color: 'var(--neutral-500)' }}>Preparing {exporting.toUpperCase()} export…</div>}

      {/* Export Options */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
        <ExportOption label="Export customer report as PDF" title="Export PDF Report" icon="📄" description={`Formatted PDF report with scoring analysis (${useCases.length} use cases)`} busy={exporting === 'pdf'} disabled={exporting !== null || useCases.length === 0} onClick={handleExportPdf} />

        <ExportOption label="Export customer report as Excel" title="Export Excel" icon="📊" description={`Multiple sheets with full data and department breakdown (${useCases.length} use cases)`} busy={exporting === 'excel'} disabled={exporting !== null || useCases.length === 0} onClick={handleExportExcel} />

        <ExportOption label="Export customer report as CSV" title="Export CSV" icon="📋" description={`Simple CSV format for spreadsheet analysis (${useCases.length} use cases)`} busy={exporting === 'csv'} disabled={exporting !== null || useCases.length === 0} onClick={handleExportCsv} />
      </div>

      {useCases.length === 0 && (
        <p style={{ color: 'var(--neutral-500)', textAlign: 'center', marginTop: '20px', fontSize: '0.9rem' }}>
          No use cases to export for this customer.
        </p>
      )}
    </div>
  );
}
