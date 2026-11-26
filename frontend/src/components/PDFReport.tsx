/**
 * PDF Report generation UI component.
 * Provides "Export PDF" button with preview options.
 */

import { useState } from 'react';
import { api } from '../lib/api';
import { UseCase } from '../types/use_case';

interface PDFReportProps {
  useCases?: UseCase[];
  selectedIds?: number[];
  onBack?: () => void;
}

export function PDFReport({ useCases = [], selectedIds = [], onBack }: PDFReportProps) {
  const [exporting, setExporting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const [allChecked, setAllChecked] = useState(true);

  const handleExport = async () => {
    try {
      setExporting(true);
      setError(null);
      setSuccess(null);

      const ids = selectedIds.length > 0 ? selectedIds : useCases.map(uc => uc.id);
      if (ids.length === 0) {
        setError('No use cases selected for export');
        return;
      }

      const blob = await api.exportPdf();
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `sail_report_${new Date().toISOString().split('T')[0]}.pdf`;
      a.click();
      window.URL.revokeObjectURL(url);
      setSuccess(`PDF report exported successfully (${ids.length} use cases)`);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to export PDF');
    } finally {
      setExporting(false);
    }
  };

  if (useCases.length === 0) {
    return (
      <div style={{ padding: '2rem', textAlign: 'center', color: 'var(--neutral-500)' }}>
        No use cases available for export
      </div>
    );
  }

  return (
    <div style={{
      background: 'var(--neutral-0)',
      borderRadius: 'var(--radius)',
      boxShadow: 'var(--shadow-card)',
      padding: '1.5rem',
    }}>
      <h3 style={{ margin: '0 0 1rem 0', fontSize: '1.1rem' }}>📄 Export PDF Report</h3>

      {error && (
        <div role="alert" aria-live="assertive" style={{
          padding: '10px',
          background: 'var(--status-negative-soft)',
          borderRadius: 'var(--radius)', borderLeft: '4px solid var(--status-negative)',
          color: 'var(--status-negative)',
          marginBottom: '1rem',
          fontSize: '0.9rem',
        }}>
          <span aria-hidden="true">⚠️ </span>{error}
        </div>
      )}

      {success && (
        <div role="status" aria-live="polite" style={{
          padding: '10px',
          background: 'var(--status-positive-soft)',
          borderRadius: 'var(--radius)',
          color: 'var(--status-positive)',
          marginBottom: '1rem',
          fontSize: '0.9rem',
        }}>
          {success}
        </div>
      )}
      {exporting && <div role="status" aria-live="polite" style={{ padding: '12px', textAlign: 'center', color: 'var(--neutral-500)' }}>Preparing PDF report…</div>}

      <div style={{ marginBottom: '1rem' }}>
        <label style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '0.75rem' }}>
          <input aria-label="P D F Report field"
            type="checkbox"
            checked={allChecked}
            onChange={(e) => setAllChecked(e.target.checked)}
            style={{ width: '18px', height: '18px' }}
          />
          <strong>Select all</strong>
        </label>

        <div style={{ maxHeight: '200px', overflowY: 'auto', border: '1px solid var(--divider)', borderRadius: 'var(--radius)', padding: '0.5rem' }}>
          {useCases.map((useCase) => (
            <label
              key={useCase.id}
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: '8px',
                padding: '8px',
                borderBottom: '1px solid var(--divider)',
                cursor: 'pointer',
              }}
            >
              <input aria-label="P D F Report field"
                type="checkbox"
                checked={!allChecked && selectedIds.includes(useCase.id)}
                onChange={(e) => {
                  if (e.target.checked) {
                    setAllChecked(false);
                  } else {
                    const remaining = selectedIds.filter(id => id !== useCase.id);
                    if (remaining.length === 0) setAllChecked(true);
                  }
                }}
                style={{ width: '16px', height: '16px' }}
              />
              <div>
                <div style={{ fontWeight: 500, fontSize: '0.9rem' }}>{useCase.title}</div>
                <div style={{ fontSize: '0.8rem', color: 'var(--neutral-500)' }}>
                  {useCase.department || 'No department'} · Score: {useCase.overall_score?.toFixed(1) ?? 'N/A'}
                </div>
              </div>
            </label>
          ))}
        </div>
      </div>

      <div style={{ display: 'flex', gap: '0.75rem', flexWrap: 'wrap' }}>
        <button role="button" aria-label="Export PDF report"
          onClick={handleExport}
          disabled={exporting || selectedIds.length === 0 && !allChecked}
          style={{
            padding: '10px 20px',
            background: exporting ? 'var(--neutral-400)' : 'var(--status-negative)',
            color: 'var(--neutral-0)',
            border: 'none',
            borderRadius: 'var(--radius)',
            cursor: exporting || selectedIds.length === 0 && !allChecked ? 'not-allowed' : 'pointer',
            fontWeight: 'bold',
            fontSize: '0.95rem',
          }}
        >
          {exporting ? '⏳ Exporting...' : '📄 Export PDF'}
        </button>
        <button role="button" aria-label="Export Excel report"
          onClick={() => {
            // Export Excel
            api.exportExcel().then(blob => {
              const url = window.URL.createObjectURL(blob);
              const a = document.createElement('a');
              a.href = url;
              a.download = `sail_export_${new Date().toISOString().split('T')[0]}.xlsx`;
              a.click();
              window.URL.revokeObjectURL(url);
            });
          }}
          style={{
            padding: '10px 20px',
            background: 'var(--brand-500)',
            color: 'var(--neutral-0)',
            border: 'none',
            borderRadius: 'var(--radius)',
            cursor: 'pointer',
            fontWeight: 'bold',
            fontSize: '0.95rem',
          }}
        >
          📊 Export Excel
        </button>
        {onBack && (
          <button role="button" aria-label="Back to dashboard"
            onClick={onBack}
            style={{
              padding: '10px 20px',
              background: 'var(--neutral-500)',
              color: 'var(--neutral-0)',
              border: 'none',
              borderRadius: 'var(--radius)',
              cursor: 'pointer',
              fontWeight: 'bold',
              fontSize: '0.95rem',
            }}
          >
            ← Back
          </button>
        )}
      </div>
    </div>
  );
}
export default PDFReport;
