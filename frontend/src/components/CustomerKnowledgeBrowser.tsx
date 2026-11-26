import React, { useState, useEffect, useCallback, useMemo, useRef } from 'react';
import { createPortal } from 'react-dom';
import { marked } from 'marked';
import DOMPurify from 'dompurify';
import { api } from '../lib/api';
import { scopedId, useScopedView } from '../lib/useScopedView';
import { getAuthToken } from '../lib/auth';
import { RowActions } from './workspacePrimitives';
import type {
  CustomerKnowledgeEntry,
  KnowledgeEnrichmentItem,
  KnowledgeEnrichmentStatus,
  KnowledgeProcessingStatus,
} from '../types/customer_knowledge';
import {
  KNOWLEDGE_CATEGORIES,
  knowledgeCategoryLabel,
} from '../types/customer_knowledge';

/** Poll interval while any visible document is PROCESSING (item 10): the
 *  page never reloads; the list is refreshed until every visible job
 *  reaches a terminal state (READY/FAILED/UPLOADED). */
const POLL_INTERVAL_MS = 5000;

/** Status presentation (item 10): Uploaded neutral / Processing blue
 *  progress / Ready green / Failed red. */
const STATUS_META: Record<KnowledgeProcessingStatus, { label: string; color: string; bg: string; pulse?: boolean }> = {
  UPLOADED: { label: 'Uploaded', color: 'var(--neutral-600)', bg: 'var(--neutral-100)' },
  PROCESSING: { label: 'Processing', color: 'var(--brand-700)', bg: 'var(--brand-50)', pulse: true },
  READY: { label: 'Ready', color: 'var(--status-positive)', bg: 'var(--status-positive-soft)' },
  FAILED: { label: 'Failed', color: 'var(--status-negative)', bg: 'var(--status-negative-soft)' },
};

function statusMeta(status: string): { label: string; color: string; bg: string; pulse?: boolean } {
  return STATUS_META[status as KnowledgeProcessingStatus] ?? STATUS_META.UPLOADED;
}

/** Enrichment lifecycle presentation:
 *  shown ONLY once the document has reached a terminal processing state,
 *  because enrichment is a distinct second stage. */
const ENRICHMENT_META: Record<KnowledgeEnrichmentStatus, { label: string; color: string; bg: string; pulse?: boolean }> = {
  NOT_RUN: { label: 'Not analyzed', color: 'var(--neutral-500)', bg: 'var(--neutral-100)' },
  ENRICHING: { label: 'Analyzing', color: 'var(--brand-700)', bg: 'var(--brand-50)', pulse: true },
  ENRICHED: { label: 'Enriched', color: 'var(--status-positive)', bg: 'var(--status-positive-soft)' },
  FAILED: { label: 'Analysis failed', color: 'var(--status-negative)', bg: 'var(--status-negative-soft)' },
  SKIPPED: { label: 'Analysis skipped', color: 'var(--neutral-500)', bg: 'var(--neutral-100)' },
};

function enrichmentMeta(status: string): { label: string; color: string; bg: string; pulse?: boolean } {
  return ENRICHMENT_META[status as KnowledgeEnrichmentStatus] ?? ENRICHMENT_META.NOT_RUN;
}

/** Provenance badge (item 6): explicit vs derived vs suggested must be
 *  visually distinct — this is the "customer stated" vs "AI believes" split. */
const PROVENANCE_META: Record<string, { label: string; color: string; bg: string }> = {
  explicit: { label: 'Stated', color: 'var(--status-positive)', bg: 'var(--status-positive-soft)' },
  derived: { label: 'Inferred', color: 'var(--brand-700)', bg: 'var(--brand-50)' },
  suggested: { label: 'Suggested', color: 'var(--neutral-600)', bg: 'var(--neutral-100)' },
};

function provenanceMeta(status: string): { label: string; color: string; bg: string } {
  return PROVENANCE_META[status] ?? PROVENANCE_META.derived;
}

function itemKindLabel(kind: string): string {
  const labels: Record<string, string> = {
    customer_fact: 'Customer fact',
    business_objective: 'Objective',
    business_challenge: 'Challenge',
    project: 'Project / Initiative',
    stakeholder: 'Stakeholder',
    requirement: 'Requirement',
    decision: 'Decision',
    follow_up_item: 'Follow-up',
    risk: 'Risk',
    technology: 'Technology',
    technology_dependency: 'Technology dependency',
    use_case: 'Use case',
    opportunity: 'Opportunity',
  };
  return labels[kind] || kind.replace(/_/g, ' ');
}

interface CustomerKnowledgeBrowserProps {
  customerId?: number;
  allowWrite?: boolean;
  onClose?: () => void;
}

const KNOWLEDGE_VIEW_KEYS = ['id'] as const;

export function CustomerKnowledgeBrowser({ customerId, onClose, allowWrite = false }: CustomerKnowledgeBrowserProps) {
  const [knowledgeView, updateKnowledgeView] = useScopedView(customerId, 'knowledge', KNOWLEDGE_VIEW_KEYS);
  const selectedKnowledgeId = scopedId(knowledgeView.id);
  const [entries, setEntries] = useState<CustomerKnowledgeEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  // Document-detail / normalized-content modal state
  const [detailEntry, setDetailEntry] = useState<CustomerKnowledgeEntry | null>(null);
  const [contentMarkdown, setContentMarkdown] = useState<string | null>(null);
  const [contentLoading, setContentLoading] = useState(false);
  const [rawView, setRawView] = useState(false);
  const [reprocessing, setReprocessing] = useState(false);
  // Knowledge category chosen at upload (item 1). '' = let the LLM decide.
  const [uploadCategory, setUploadCategory] = useState('');
  // UX audit #5: the upload panel used to render by default (a modal-style
  // overlay inverted read-vs-write priority on first visit and wasn't a real
  // dialog). The entries list is now the default view; the upload dialog
  // opens on demand from the "Upload Knowledge File" button (or the empty
  // state), and is a real dialog (role="dialog", Esc-to-close).
  const [uploadOpen, setUploadOpen] = useState(false);
  // Enrichment items of the open detail entry (item 6 / item 13)
  const [enrichmentItems, setEnrichmentItems] = useState<KnowledgeEnrichmentItem[]>([]);
  const [itemsLoading, setItemsLoading] = useState(false);
  const [retryingEnrichment, setRetryingEnrichment] = useState(false);
  const pollTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const customerRef = useRef(customerId);
  const detailSeq = useRef(0);
  if (customerRef.current !== customerId) detailSeq.current += 1;
  customerRef.current = customerId;
  const listSeq = useRef(0);

  const fetchEntries = useCallback(async () => {
    if (customerRef.current !== customerId) return;
    const requestedCustomer = customerId;
    const seq = ++listSeq.current;
    try {
      const result = await api.listCustomerKnowledge(customerId);
      if (customerRef.current === requestedCustomer && listSeq.current === seq) setEntries(result || []);
    } catch (err: any) {
      if (customerRef.current === requestedCustomer && listSeq.current === seq) setError(err.message || 'Failed to load knowledge entries');
    } finally {
      if (customerRef.current === requestedCustomer && listSeq.current === seq) setLoading(false);
    }
  }, [customerId]);

  useEffect(() => {
    setLoading(true);
    setEntries([]);
    setDetailEntry(null);
    setContentMarkdown(null);
    setEnrichmentItems([]);
    setUploadOpen(false);
    setError(null);
    fetchEntries();
    return () => { listSeq.current += 1; };
  }, [fetchEntries]);

  // Poll while any visible document is PROCESSING (item 10) or ENRICHING
  // (item 2: LLM analysis is a second, visible stage).
  const anyProcessing = entries.some(
    (e) => e.processing_status === 'PROCESSING' || e.enrichment_status === 'ENRICHING',
  );
  useEffect(() => {
    if (!anyProcessing) {
      if (pollTimer.current) {
        clearTimeout(pollTimer.current);
        pollTimer.current = null;
      }
      return;
    }
    pollTimer.current = setTimeout(() => {
      fetchEntries();
    }, POLL_INTERVAL_MS);
    return () => {
      if (pollTimer.current) {
        clearTimeout(pollTimer.current);
        pollTimer.current = null;
      }
    };
  }, [anyProcessing, fetchEntries, entries]);

  // Esc closes the upload dialog (UX audit #5 — it is a real dialog now).
  useEffect(() => {
    if (!uploadOpen) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setUploadOpen(false);
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [uploadOpen]);

  const handleUpload = async (event: React.ChangeEvent<HTMLInputElement>) => {
    if (!allowWrite) return;
    const file = event.target.files?.[0];
    if (!file) return;
    try {
      setUploading(true);
      const result = await api.uploadCustomerKnowledge(file, customerId, uploadCategory || undefined);
      setNotice(
        `${file.name} uploaded — processing started. ${result?.classified_type ? `Type: ${result.classified_type}.` : ''} The application LLM will analyze it automatically once parsing completes.`
      );
      // The upload returns once the original is stored + processing
      // initiated; refresh to show the PROCESSING row (polling then follows).
      await fetchEntries();
      event.target.value = '';
    } catch (err: any) {
      setError(err.message || 'Failed to upload file');
    } finally {
      setUploading(false);
    }
  };

  const handleDelete = async (id: number) => {
    if (!allowWrite) return;
    if (!window.confirm('Are you sure you want to delete this knowledge entry?')) return;
    try {
      await api.deleteCustomerKnowledge(id);
      await fetchEntries();
    } catch (err: any) {
      setError(err.message || 'Failed to delete entry');
    }
  };

  const handleReprocess = async (id: number) => {
    if (!allowWrite) return;
    setReprocessing(true);
    try {
      await api.reprocessKnowledge(id);
      setNotice('Reprocessing started — the document will be re-parsed and re-analyzed by the LLM.');
      await fetchEntries();
    } catch (err: any) {
      setError(err.message || 'Failed to start reprocess');
    } finally {
      setReprocessing(false);
    }
  };

  // Retry LLM analysis only (item 16: Docling is NOT rerun — Reprocess is
  // the full-pipeline action).
  const handleRetryEnrichment = async (id: number) => {
    if (!allowWrite) return;
    setRetryingEnrichment(true);
    try {
      await api.retryKnowledgeEnrichment(id);
      await fetchEntries();
      // Refetch items for the open detail (if any) once the poll lands.
      if (detailEntry && detailEntry.id === id) {
        await fetchItems(id);
      }
    } catch (err: any) {
      setError(err.message || 'Failed to retry analysis');
    } finally {
      setRetryingEnrichment(false);
    }
  };

  const fetchItems = async (knowledgeId: number) => {
    const seq = detailSeq.current;
    setItemsLoading(true);
    try {
      const items = await api.listKnowledgeItems(knowledgeId);
      if (seq === detailSeq.current) setEnrichmentItems(items || []);
    } catch {
      if (seq === detailSeq.current) setEnrichmentItems([]);
    } finally {
      if (seq === detailSeq.current) setItemsLoading(false);
    }
  };

  const showDetails = (entry: CustomerKnowledgeEntry) => {
    const seq = ++detailSeq.current;
    setDetailEntry(entry);
    setRawView(false);
    if (entry.processing_status === 'READY' && entry.normalized_content_present) {
      setContentMarkdown(null);
      setContentLoading(true);
      api
        .getKnowledgeContent(entry.id)
        .then((res) => { if (seq === detailSeq.current) setContentMarkdown(res.normalized_content); })
        .catch((err: any) => {
          if (seq === detailSeq.current) {
            setContentMarkdown(null);
            setError(err.message || 'Failed to load normalized content');
          }
        })
        .finally(() => { if (seq === detailSeq.current) setContentLoading(false); });
    } else {
      setContentMarkdown(null);
    }
    // Items are available once enrichment has run (ENRICHED/FAILED).
    if (entry.enrichment_status === 'ENRICHED') {
      fetchItems(entry.id);
    } else {
      setEnrichmentItems([]);
    }
  };

  useEffect(() => {
    if (loading) return;
    if (selectedKnowledgeId === null) {
      if (detailEntry) {
        detailSeq.current += 1;
        setDetailEntry(null);
        setContentMarkdown(null);
        setRawView(false);
        setEnrichmentItems([]);
      }
      return;
    }
    const entry = entries.find((item) => item.id === selectedKnowledgeId && (customerId === undefined || item.customer_id === customerId));
    if (entry && detailEntry?.id !== entry.id) showDetails(entry);
    if (!entry && detailEntry) {
      detailSeq.current += 1;
      setDetailEntry(null);
      setContentMarkdown(null);
    }
    // showDetails uses only the selected entry and stable state setters.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedKnowledgeId, entries, loading, customerId, detailEntry?.id]);

  const openDetails = (entry: CustomerKnowledgeEntry) => updateKnowledgeView({ id: String(entry.id) });

  const closeDetails = () => {
    updateKnowledgeView({ id: null });
    detailSeq.current += 1;
    setDetailEntry(null);
    setContentMarkdown(null);
    setRawView(false);
    setEnrichmentItems([]);
  };

  const handleDownload = (entry: CustomerKnowledgeEntry) => {
    // Auth-gated original download: fetch with the Bearer token (a plain
    // <a> href cannot carry the header) then trigger a browser download.
    const token = getAuthToken();
    const url = api.knowledgeDownloadUrl(entry.id);
    fetch(url, { headers: token ? { Authorization: `Bearer ${token}` } : {} })
      .then((res) => {
        if (!res.ok) throw new Error(`Download failed: ${res.statusText}`);
        return res.blob();
      })
      .then((blob) => {
        const a = document.createElement('a');
        a.href = URL.createObjectURL(blob);
        a.download = entry.file_name;
        document.body.appendChild(a);
        a.click();
        a.remove();
        URL.revokeObjectURL(a.href);
      })
      .catch((err: any) => setError(err.message || 'Failed to download original'));
  };

  const getTypeLabel = (type: string) => {
    const labels: Record<string, string> = {
      software_inventory: 'Software',
      hardware_inventory: 'Hardware',
      process_document: 'Process',
      policy_document: 'Policy',
      other: 'Other',
      markdown: 'Markdown',
      text: 'Text',
      document: 'Document',
      spreadsheet: 'Spreadsheet',
      presentation: 'Presentation',
      html: 'HTML',
      table: 'Table',
      image: 'Image',
      file: 'File',
    };
    return labels[type] || type;
  };

  const renderedMarkdown = useMemo(() => {
    if (!contentMarkdown) return '';
    const html = marked.parse(contentMarkdown, { async: false }) as string;
    return DOMPurify.sanitize(html, { USE_PROFILES: { html: true } });
  }, [contentMarkdown]);

  if (loading) {
    return <div style={{ padding: '20px' }}>Loading knowledge entries...</div>;
  }

  return (
    <div style={{ padding: '20px', position: 'relative' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '20px', gap: '12px', flexWrap: 'wrap' }}>
        <h2 style={{ margin: 0 }}>Customer Knowledge Base</h2>
        <div style={{ display: 'flex', gap: '8px' }}>
          {/* UX audit #5: upload is now on-demand — the entries list is the
              default view on first visit. */}
          <button
            role="button"
            aria-label="Upload Knowledge File"
            disabled={!allowWrite}
            onClick={() => setUploadOpen(true)}
            style={{ padding: '8px 16px', background: 'var(--brand-500)', color: 'var(--neutral-0)', border: 'none', borderRadius: 'var(--radius)', cursor: 'pointer', fontSize: '0.85rem', fontWeight: 600 }}
          >
            ⬆ Upload Knowledge File
          </button>
          {onClose && (
            <button
              role="button"
              aria-label="Close knowledge base"
              onClick={onClose}
              style={{ padding: '8px 16px', background: 'var(--neutral-500)', color: 'var(--neutral-0)', border: 'none', borderRadius: 'var(--radius)', cursor: 'pointer' }}
            >
              Close
            </button>
          )}
        </div>
      </div>

      {!loading && !error && selectedKnowledgeId !== null && !entries.some((entry) => entry.id === selectedKnowledgeId && (customerId === undefined || entry.customer_id === customerId)) && <p role="alert">Knowledge entry not found or unavailable.</p>}
      {error && (
        <div style={{ padding: '12px', background: 'var(--status-negative-soft)', borderRadius: 'var(--radius)', marginBottom: '16px', color: 'var(--status-negative)' }}>
          {error}
          <button
            role="button"
            aria-label="Dismiss error"
            onClick={() => setError(null)}
            style={{ marginLeft: '12px', background: 'none', border: 'none', cursor: 'pointer', color: 'var(--status-negative)' }}
          >
            ✕
          </button>
        </div>
      )}
      {notice && (
        <div style={{ padding: '12px', background: 'var(--brand-50)', borderRadius: 'var(--radius)', marginBottom: '16px', color: 'var(--brand-700)', display: 'flex', gap: '12px' }}>
          <span>{notice}</span>
          <button role="button" aria-label="Dismiss notice" onClick={() => setNotice(null)} style={{ background: 'none', border: 'none', cursor: 'pointer', color: 'var(--brand-700)' }}>✕</button>
        </div>
      )}

      {/* Upload dialog (UX audit #5: on-demand + real dialog semantics) */}
      {uploadOpen && allowWrite && createPortal(
        <div
          role="dialog"
          aria-modal="true"
          aria-label="Upload Knowledge File"
          style={{
            position: 'fixed', inset: 0, zIndex: 40, background: 'rgba(0,0,0,0.45)',
            display: 'flex', alignItems: 'center', justifyContent: 'center', padding: '24px',
          }}
          onClick={() => setUploadOpen(false)}
        >
          <div
            onClick={(e) => e.stopPropagation()}
            style={{
              background: 'var(--neutral-0)', borderRadius: 'var(--radius)', maxWidth: '560px', width: '100%',
              boxShadow: 'var(--shadow-card)', padding: '20px 24px',
            }}
          >
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '12px' }}>
              <h3 style={{ margin: 0, fontSize: '1rem' }}>Upload Knowledge File</h3>
              <button role="button" aria-label="Close upload dialog" onClick={() => setUploadOpen(false)} style={{ background: 'none', border: 'none', fontSize: '1.1rem', cursor: 'pointer', color: 'var(--neutral-500)' }}>✕</button>
            </div>
            <p style={{ margin: '0 0 12px 0', fontSize: '0.85rem', color: 'var(--neutral-500)' }}>
              Upload PDF, CSV, DOCX, PPTX, HTML, ODF or images — documents are normalized to Markdown and then
              analyzed automatically by the application LLM to extract customer intelligence. Markdown files are stored directly.
            </p>
            <div style={{ display: 'flex', gap: '12px', alignItems: 'flex-end', flexWrap: 'wrap' }}>
              <label style={{ display: 'inline-block', padding: '8px 16px', background: 'var(--brand-500)', color: 'var(--neutral-0)', borderRadius: 'var(--radius)', cursor: uploading ? 'not-allowed' : 'pointer', opacity: uploading ? 0.6 : 1 }}>
                {uploading ? 'Uploading...' : 'Choose File'}
                <input
                  type="file"
                  accept=".pdf,.csv,.tsv,.txt,.md,.markdown,.doc,.docx,.xls,.xlsx,.ppt,.pptx,.html,.htm,.png,.jpg,.jpeg,.tif,.tiff"
                  onChange={handleUpload}
                  disabled={uploading}
                  style={{ display: 'none' }}
                />
              </label>
              <label style={{ display: 'flex', flexDirection: 'column', gap: '4px', fontSize: '0.75rem', color: 'var(--neutral-600)' }}>
                <span>Knowledge Category (optional — the LLM can classify it)</span>
                <select
                  aria-label="Knowledge category"
                  value={uploadCategory}
                  onChange={(e) => setUploadCategory(e.target.value)}
                  disabled={uploading}
                  style={{ padding: '7px 10px', borderRadius: 'var(--radius)', border: '1px solid var(--divider)', background: 'var(--neutral-0)', fontSize: '0.8rem', minWidth: '260px' }}
                >
                  <option value="">Auto (let the LLM decide)</option>
                  {KNOWLEDGE_CATEGORIES.map((c) => (
                    <option key={c.value} value={c.value}>{c.label}</option>
                  ))}
                </select>
              </label>
            </div>
          </div>
        </div>,
        document.body,
      )}

      {/* Entries Table */}
      <div style={{ background: 'var(--neutral-0)', borderRadius: 'var(--radius)', boxShadow: 'var(--shadow-card)' }}>
        {entries.length === 0 ? (
          <div style={{ padding: '40px', textAlign: 'center', color: 'var(--neutral-500)' }}>
            No knowledge entries found.{allowWrite ? ' Upload files to get started.' : ''}
            <div style={{ marginTop: '14px' }}>
              <button
                role="button"
                aria-label="Upload your first knowledge file"
                disabled={!allowWrite}
            onClick={() => setUploadOpen(true)}
                style={{ padding: '8px 18px', background: 'var(--brand-500)', color: 'var(--neutral-0)', border: 'none', borderRadius: 'var(--radius)', cursor: 'pointer', fontSize: '0.85rem', fontWeight: 600 }}
              >
                ⬆ Upload Knowledge File
              </button>
            </div>
          </div>
        ) : (
          <table style={{ width: '100%', borderCollapse: 'collapse' }}>
            <thead>
              <tr style={{ borderBottom: '2px solid var(--divider)' }}>
                <th style={{ padding: '12px', textAlign: 'left', fontSize: '0.85rem', color: 'var(--neutral-500)' }}>Type</th>
                <th style={{ padding: '12px', textAlign: 'left', fontSize: '0.85rem', color: 'var(--neutral-500)' }}>File Name</th>
                <th style={{ padding: '12px', textAlign: 'left', fontSize: '0.85rem', color: 'var(--neutral-500)' }}>Upload Date</th>
                <th style={{ padding: '12px', textAlign: 'left', fontSize: '0.85rem', color: 'var(--neutral-500)' }}>Status</th>
                <th style={{ padding: '12px', textAlign: 'left', fontSize: '0.85rem', color: 'var(--neutral-500)' }}>Actions</th>
              </tr>
            </thead>
            <tbody>
              {entries.map((entry) => {
                const meta = statusMeta(entry.processing_status);
                const processing = entry.processing_status === 'PROCESSING';
                return (
                  <tr key={entry.id} style={{ borderBottom: '1px solid var(--divider)' }}>
                    <td style={{ padding: '12px' }}>
                      <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
                        <span style={{ padding: '4px 8px', background: 'var(--neutral-100)', borderRadius: 'var(--radius)', fontSize: '0.8rem' }}>
                          {getTypeLabel(entry.knowledge_type)}
                        </span>
                        {entry.knowledge_category && (
                          <span
                            title="Knowledge category (item 1)"
                            style={{ fontSize: '0.72rem', color: 'var(--neutral-500)', maxWidth: '200px' }}
                          >
                            {knowledgeCategoryLabel(entry.knowledge_category)}
                          </span>
                        )}
                      </div>
                    </td>
                    <td style={{ padding: '12px', fontSize: '0.9rem' }}>{entry.file_name}</td>
                    <td style={{ padding: '12px', fontSize: '0.85rem', color: 'var(--neutral-500)' }}>
                      {new Date(entry.uploaded_at).toLocaleDateString()}
                    </td>
                    <td style={{ padding: '12px' }}>
                      <div style={{ display: 'flex', flexDirection: 'column', gap: '6px', alignItems: 'flex-start' }}>
                        <span
                          role="status"
                          aria-label={`Processing status: ${meta.label}`}
                          title={entry.processing_status === 'FAILED' ? (entry.processing_error || undefined) : undefined}
                          style={{
                            padding: '4px 10px', background: meta.bg, borderRadius: 'var(--radius)',
                            fontSize: '0.8rem', color: meta.color, fontWeight: 600,
                            display: 'inline-flex', alignItems: 'center', gap: '6px',
                          }}
                        >
                          {processing && (
                            <span
                              aria-hidden="true"
                              style={{
                                width: '8px', height: '8px', borderRadius: '50%',
                                background: 'var(--brand-500)',
                                animation: 'sail-knowledge-pulse 1.2s ease-in-out infinite',
                              }}
                            />
                          )}
                          {meta.label}
                        </span>
                        {/* LLM analysis stage (items 2, 16): a second chip,
                            shown once the document leaves the Docling stage. */}
                        {entry.processing_status === 'READY' && (
                          <span
                            role="status"
                            aria-label={`Analysis status: ${enrichmentMeta(entry.enrichment_status || 'NOT_RUN').label}`}
                            title={
                              (entry.enrichment_status === 'FAILED' || entry.enrichment_status === 'SKIPPED')
                                ? (entry.enrichment_error || undefined)
                                : undefined
                            }
                            style={{
                              padding: '3px 8px', background: enrichmentMeta(entry.enrichment_status || 'NOT_RUN').bg,
                              borderRadius: 'var(--radius)', fontSize: '0.72rem',
                              color: enrichmentMeta(entry.enrichment_status || 'NOT_RUN').color, fontWeight: 600,
                              display: 'inline-flex', alignItems: 'center', gap: '5px',
                            }}
                          >
                            {entry.enrichment_status === 'ENRICHING' && (
                              <span
                                aria-hidden="true"
                                style={{
                                  width: '7px', height: '7px', borderRadius: '50%',
                                  background: 'var(--brand-500)',
                                  animation: 'sail-knowledge-pulse 1.2s ease-in-out infinite',
                                }}
                              />
                            )}
                            {enrichmentMeta(entry.enrichment_status || 'NOT_RUN').label}
                          </span>
                        )}
                      </div>
                    </td>
                    <td style={{ padding: '12px' }}>
                      <RowActions
                        ariaLabel={`Actions for ${entry.file_name}`}
                        items={[
                          {
                            label: 'View details',
                            onClick: () => openDetails(entry),
                            divider: true,
                          },
                          {
                            label: 'View normalized content',
                            onClick: () => openDetails(entry),
                            disabled: entry.processing_status !== 'READY' || !entry.normalized_content_present,
                          },
                          {
                            label: entry.enrichment_status === 'FAILED' ? 'Retry LLM analysis' : 'Reprocess',
                            onClick: () =>
                              entry.processing_status === 'READY' && entry.enrichment_status === 'FAILED'
                                ? handleRetryEnrichment(entry.id)
                                : handleReprocess(entry.id),
                            disabled: !allowWrite || processing || reprocessing || retryingEnrichment,
                          },
                          {
                            label: entry.knowledge_type === 'rvtools_report' && entry.processor_version !== 'rvtools-summary/2'
                              ? 'Download original (legacy totals may be incomplete)' : 'Download original',
                            onClick: () => handleDownload(entry),
                            divider: true,
                          },
                          {
                            label: 'Delete entry',
                            disabled: !allowWrite,
                            onClick: () => handleDelete(entry.id),
                            destructive: true,
                          },
                        ]}
                      />
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </div>

      <style>{`
        @keyframes sail-knowledge-pulse {
          0%, 100% { opacity: 1; transform: scale(1); }
          50% { opacity: 0.4; transform: scale(0.8); }
        }
        [data-sail-md] table { border-collapse: collapse; margin: 8px 0; width: 100%; }
        [data-sail-md] th, [data-sail-md] td { border: 1px solid var(--divider); padding: 6px 10px; text-align: left; font-size: 0.85rem; }
        [data-sail-md] code { background: var(--neutral-100); padding: 1px 5px; border-radius: 4px; font-size: 0.85em; }
        [data-sail-md] pre { background: var(--neutral-100); padding: 10px; border-radius: var(--radius); overflow-x: auto; }
        [data-sail-md] h1, [data-sail-md] h2, [data-sail-md] h3 { margin: 14px 0 6px; }
        [data-sail-md] ul, [data-sail-md] ol { margin: 6px 0 6px 20px; padding: 0; }
        [data-sail-md] p { margin: 6px 0; }
      `}</style>

      {/* Document details / normalized content modal (item 11) */}
      {detailEntry && createPortal(
        <div
          role="dialog"
          aria-modal="true"
          aria-label={`Details for ${detailEntry.file_name}`}
          onClick={closeDetails}
          style={{
            position: 'fixed', inset: 0, zIndex: 50, background: 'rgba(0,0,0,0.45)',
            display: 'flex', alignItems: 'center', justifyContent: 'center', padding: '24px',
          }}
        >
          <div
            onClick={(e) => e.stopPropagation()}
            style={{
              background: 'var(--neutral-0)', borderRadius: 'var(--radius)', maxWidth: '860px', width: '100%',
              maxHeight: '85vh', overflow: 'auto', boxShadow: 'var(--shadow-card)',
            }}
          >
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '16px 20px', borderBottom: '2px solid var(--divider)' }}>
              <div>
                <div style={{ fontSize: '1rem', fontWeight: 700 }}>{detailEntry.file_name}</div>
                <div style={{ fontSize: '0.8rem', color: 'var(--neutral-500)', marginTop: '2px' }}>
                  {getTypeLabel(detailEntry.knowledge_type)}
                  {detailEntry.original_content_type ? ` · ${detailEntry.original_content_type}` : ''}
                  {detailEntry.processor ? ` · processor: ${detailEntry.processor}` : ''}
                  {detailEntry.processed_at ? ` · ${new Date(detailEntry.processed_at).toLocaleString()}` : ''}
                </div>
              </div>
              <button aria-label="Close details" onClick={closeDetails} style={{ background: 'none', border: 'none', fontSize: '1.2rem', cursor: 'pointer', color: 'var(--neutral-500)' }}>✕</button>
            </div>

            {detailEntry.knowledge_type === 'rvtools_report' && detailEntry.processor_version !== 'rvtools-summary/2' && (
              <p style={{ margin: '14px 20px', color: 'var(--status-warning)' }}>
                This older report may contain incomplete totals in its original download. Its extracted intelligence and linked records may also reflect those totals and should be reviewed. Use the current VMware Footprint for corrected totals.
              </p>
            )}

            {detailEntry.processing_status === 'FAILED' && detailEntry.processing_error && (
              <div style={{ margin: '14px 20px 0', padding: '12px', background: 'var(--status-negative-soft)', borderRadius: 'var(--radius)', color: 'var(--status-negative)', fontSize: '0.85rem' }}>
                <strong>Processing failed.</strong> {detailEntry.processing_error}
                <div style={{ marginTop: '8px' }}>
                  <button
                    onClick={() => handleReprocess(detailEntry.id)}
                    disabled={!allowWrite || reprocessing}
                    style={{ padding: '6px 14px', background: 'var(--brand-500)', color: 'var(--neutral-0)', border: 'none', borderRadius: 'var(--radius)', cursor: 'pointer', fontSize: '0.85rem', fontWeight: 600 }}
                  >
                    {reprocessing ? 'Reprocessing…' : 'Reprocess'}
                  </button>
                </div>
              </div>
            )}

            {/* LLM enrichment failure (item 16): separate from the Docling
                failure — the normalized content below stays available and
                ONLY the analysis stage is retried. */}
            {detailEntry.processing_status === 'READY' && detailEntry.enrichment_status === 'FAILED' && (
              <div style={{ margin: '14px 20px 0', padding: '12px', background: 'var(--status-negative-soft)', borderRadius: 'var(--radius)', color: 'var(--status-negative)', fontSize: '0.85rem' }}>
                <strong>LLM analysis failed.</strong>{' '}
                {detailEntry.enrichment_error || 'The normalized document is still available — retry the analysis.'}
                <div style={{ marginTop: '8px' }}>
                  <button
                    aria-label="Retry LLM analysis"
                    onClick={() => handleRetryEnrichment(detailEntry.id)}
                    disabled={!allowWrite || retryingEnrichment}
                    style={{ padding: '6px 14px', background: 'var(--brand-500)', color: 'var(--neutral-0)', border: 'none', borderRadius: 'var(--radius)', cursor: 'pointer', fontSize: '0.85rem', fontWeight: 600 }}
                  >
                    {retryingEnrichment ? 'Retrying…' : 'Retry LLM analysis'}
                  </button>
                </div>
              </div>
            )}

            {contentLoading && (
              <div style={{ padding: '20px', color: 'var(--neutral-500)' }}>Loading normalized content…</div>
            )}

            {!contentLoading && contentMarkdown !== null && (
              <div style={{ padding: '16px 20px' }}>
                <div style={{ display: 'flex', justifyContent: 'flex-end', marginBottom: '8px' }}>
                  <button
                    role="tab"
                    aria-pressed={rawView}
                    onClick={() => setRawView((v) => !v)}
                    style={{ padding: '4px 12px', background: 'var(--neutral-100)', border: '1px solid var(--divider)', borderRadius: 'var(--radius)', cursor: 'pointer', fontSize: '0.8rem' }}
                  >
                    {rawView ? 'Rendered view' : 'Raw Markdown'}
                  </button>
                </div>
                {rawView ? (
                  <pre style={{ whiteSpace: 'pre-wrap', fontSize: '0.85rem', color: 'var(--neutral-700)', margin: 0 }}>{contentMarkdown}</pre>
                ) : (
                  <div data-sail-md dangerouslySetInnerHTML={{ __html: renderedMarkdown }} />
                )}
              </div>
            )}

            {!contentLoading && contentMarkdown === null && detailEntry.processing_status === 'READY' && (
              <div style={{ padding: '20px', color: 'var(--neutral-500)', fontSize: '0.85rem' }}>
                No normalized content available yet.
              </div>
            )}

            {!contentLoading && contentMarkdown === null && detailEntry.processing_status !== 'READY' && (
              <div style={{ padding: '20px', color: 'var(--neutral-500)', fontSize: '0.85rem' }}>
                This document has not reached the Ready state
                {' '}(<span style={{ color: statusMeta(detailEntry.processing_status).color, fontWeight: 600 }}>{statusMeta(detailEntry.processing_status).label}</span>).
                {detailEntry.processing_status === 'PROCESSING' && ' Normalized content will be available once processing completes.'}
              </div>
            )}

            {/* Extracted customer intelligence (items 4, 6, 13): what the LLM
                learned from this document — provenance distinguishes what the
                customer stated from what the AI inferred/suggested. */}
            {!contentLoading && detailEntry.processing_status === 'READY' && detailEntry.enrichment_status === 'ENRICHED' && (
              <div style={{ padding: '16px 20px 20px', borderTop: '2px solid var(--divider)', marginTop: '8px' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: '4px' }}>
                  <h4 style={{ margin: 0, fontSize: '0.9rem' }}>
                    Extracted intelligence
                    {detailEntry.enrichment_model ? (
                      <span style={{ fontWeight: 400, color: 'var(--neutral-500)', fontSize: '0.75rem' }}>
                        {' '}· model: {detailEntry.enrichment_model}
                      </span>
                    ) : null}
                  </h4>
                  <span style={{ fontSize: '0.72rem', color: 'var(--neutral-500)' }}>
                    {enrichmentItems.length} item{enrichmentItems.length === 1 ? '' : 's'}
                  </span>
                </div>
                <p style={{ margin: '0 0 10px 0', fontSize: '0.75rem', color: 'var(--neutral-500)' }}>
                  “Stated” = customer-stated fact · “Inferred” = derived from the document · “Suggested” = AI candidate requiring validation.
                </p>
                {itemsLoading ? (
                  <div style={{ padding: '12px', color: 'var(--neutral-500)', fontSize: '0.85rem' }}>Loading intelligence…</div>
                ) : enrichmentItems.length === 0 ? (
                  <div style={{ padding: '12px', color: 'var(--neutral-500)', fontSize: '0.85rem' }}>
                    No structured intelligence was extracted from this document.
                  </div>
                ) : (
                  <ul style={{ margin: 0, padding: 0, listStyle: 'none', display: 'flex', flexDirection: 'column', gap: '8px' }}>
                    {enrichmentItems.map((item) => {
                      const pm = provenanceMeta(item.provenance);
                      return (
                        <li
                          key={item.id}
                          data-provenance={item.provenance}
                          style={{
                            padding: '10px 12px', background: 'var(--neutral-50)',
                            border: '1px solid var(--divider)', borderRadius: 'var(--radius)',
                          }}
                        >
                          <div style={{ display: 'flex', alignItems: 'center', gap: '8px', flexWrap: 'wrap' }}>
                            <span style={{ fontWeight: 600, fontSize: '0.85rem' }}>{item.name}</span>
                            <span style={{ fontSize: '0.72rem', color: 'var(--neutral-500)' }}>{itemKindLabel(item.kind)}</span>
                            <span
                              style={{
                                padding: '1px 8px', borderRadius: 'var(--radius)',
                                fontSize: '0.7rem', fontWeight: 600,
                                background: pm.bg, color: pm.color,
                              }}
                            >
                              {pm.label}
                            </span>
                            {typeof item.confidence === 'number' && (
                              <span style={{ fontSize: '0.7rem', color: 'var(--neutral-500)' }}>
                                confidence {(item.confidence * 100).toFixed(0)}%
                              </span>
                            )}
                            {item.applied_status && item.applied_status !== 'skipped' && (
                              <span
                                title={`Applied to ${item.applied_object_type || 'customer knowledge'} (${item.applied_status})`}
                                style={{ fontSize: '0.7rem', color: item.applied_status === 'failed' ? 'var(--status-negative)' : 'var(--status-positive)', fontWeight: 600 }}
                              >
                                → {item.applied_object_type || 'knowledge'}: {item.applied_status}
                              </span>
                            )}
                          </div>
                          {item.description && (
                            <div style={{ fontSize: '0.8rem', color: 'var(--neutral-700)', marginTop: '4px' }}>{item.description}</div>
                          )}
                          {item.evidence && (
                            <div style={{ fontSize: '0.75rem', color: 'var(--neutral-500)', marginTop: '4px', fontStyle: 'italic' }}>
                              “{item.evidence}”{item.source_reference ? ` — ${item.source_reference}` : ''}
                            </div>
                          )}
                        </li>
                      );
                    })}
                  </ul>
                )}
              </div>
            )}
          </div>
        </div>,
        document.body,
      )}
    </div>
  );
}
