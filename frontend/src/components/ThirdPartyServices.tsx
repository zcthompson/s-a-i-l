import { useEffect, useMemo, useState } from 'react';
import { api } from '../lib/api';
import {
  BILLING_MODELS,
  DOCUMENT_TYPES,
  ENGAGEMENT_STATUSES,
  SERVICE_CATEGORIES,
  ThirdPartyService,
  ThirdPartyServiceCreate,
  ThirdPartyServiceDocument,
  VerificationState,
  VERIFICATION_STATES,
  formatBillingModel,
  formatDocumentType,
  formatEngagementStatus,
  formatServiceCategory,
} from '../types/sail';

interface Props {
  customerId: number;
  userRole?: string; // customer junction role: owner | member | auditor | none
}

interface ServiceForm {
  vendor_name: string;
  service_category: string;
  engagement_status: string;
  description: string;
  sow_reference: string;
  contract_reference: string;
  started_on: string;
  ended_on: string;
  billing_model: string;
  fee_amount: string;
  verification_state: string;
  notes: string;
  related_use_case_ids: string;
}

interface DocumentForm {
  document_type: string;
  title: string;
  file: File | null;
}

const emptyForm = (): ServiceForm => ({
  vendor_name: '',
  service_category: '',
  engagement_status: 'active',
  description: '',
  sow_reference: '',
  contract_reference: '',
  started_on: '',
  ended_on: '',
  billing_model: '',
  fee_amount: '',
  verification_state: 'verified',
  notes: '',
  related_use_case_ids: '',
});

const emptyDocumentForm = (): DocumentForm => ({ document_type: '', title: '', file: null });

const inputStyle: React.CSSProperties = {
  padding: '8px',
  border: '1px solid var(--divider)',
  borderRadius: 'var(--radius)',
  fontSize: '0.85rem',
  background: 'var(--neutral-0)',
  color: 'var(--ink)',
};

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label style={{ display: 'flex', flexDirection: 'column', gap: '4px', fontSize: '0.8rem', color: 'var(--neutral-600)' }}>
      {label}
      {children}
    </label>
  );
}

function statusColors(status: string): { bg: string; fg: string } {
  switch (status) {
    case 'active': return { bg: 'var(--status-positive)', fg: 'white' };
    case 'planned':
    case 'pending': return { bg: 'var(--status-warning)', fg: '#1f2937' };
    case 'cancelled': return { bg: 'var(--status-negative)', fg: 'white' };
    default: return { bg: 'var(--neutral-200)', fg: 'var(--neutral-700)' };
  }
}

function parseIds(value: string): number[] {
  if (!value.trim()) return [];
  return value
    .split(',')
    .map((part) => Number(part.trim()))
    .filter((id) => Number.isFinite(id) && id > 0);
}

function monthlyFee(service: ThirdPartyService): string {
  if (service.billing_model === null) return '—';
  const model = formatBillingModel(service.billing_model);
  if (service.fee_amount === null) return `${model} · —`;
  return `${model} · ${new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' }).format(service.fee_amount)} / month`;
}

export function ThirdPartyServices({ customerId, userRole }: Props) {
  const [services, setServices] = useState<ThirdPartyService[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [statusFilter, setStatusFilter] = useState('');
  const [categoryFilter, setCategoryFilter] = useState('');
  const [search, setSearch] = useState('');
  const [expandedId, setExpandedId] = useState<number | null>(null);
  const [formOpen, setFormOpen] = useState(false);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [form, setForm] = useState<ServiceForm>(emptyForm());
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [confirmDeleteId, setConfirmDeleteId] = useState<number | null>(null);
  const [documents, setDocuments] = useState<Record<number, ThirdPartyServiceDocument[]>>({});
  const [documentsLoadingId, setDocumentsLoadingId] = useState<number | null>(null);
  const [documentForm, setDocumentForm] = useState<DocumentForm>(emptyDocumentForm());
  const [documentBusy, setDocumentBusy] = useState(false);
  const [documentError, setDocumentError] = useState<string | null>(null);
  const [confirmDocumentDeleteId, setConfirmDocumentDeleteId] = useState<number | null>(null);

  const canEdit = userRole !== 'auditor' && userRole !== 'none';

  const load = async () => {
    setLoading(true);
    setError(null);
    try {
      setServices(await api.listCustomerThirdPartyServices(customerId));
    } catch (err: any) {
      setError(err?.message || 'Failed to load third-party services');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    setServices([]);
    setExpandedId(null);
    setFormOpen(false);
    setDocuments({});
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [customerId]);

  const filtered = useMemo(() => {
    let result = services;
    if (statusFilter) result = result.filter((service) => service.engagement_status === statusFilter);
    if (categoryFilter) result = result.filter((service) => service.service_category === categoryFilter);
    if (search.trim()) {
      const query = search.trim().toLowerCase();
      result = result.filter((service) =>
        service.vendor_name.toLowerCase().includes(query)
        || service.description.toLowerCase().includes(query)
        || (service.sow_reference || '').toLowerCase().includes(query),
      );
    }
    return [...result].sort((a, b) => b.id - a.id);
  }, [services, statusFilter, categoryFilter, search]);

  const set = <K extends keyof ServiceForm>(key: K, value: ServiceForm[K]) =>
    setForm((current) => ({ ...current, [key]: value }));

  const startCreate = () => {
    setEditingId(null);
    setForm(emptyForm());
    setSaveError(null);
    setFormOpen(true);
    setExpandedId(null);
  };

  const startEdit = (service: ThirdPartyService) => {
    setEditingId(service.id);
    setForm({
      vendor_name: service.vendor_name,
      service_category: service.service_category,
      engagement_status: service.engagement_status,
      description: service.description,
      sow_reference: service.sow_reference || '',
      contract_reference: service.contract_reference || '',
      started_on: service.started_on || '',
      ended_on: service.ended_on || '',
      billing_model: service.billing_model || '',
      fee_amount: service.fee_amount === null ? '' : String(service.fee_amount),
      verification_state: service.verification_state,
      notes: service.notes || '',
      related_use_case_ids: service.related_use_case_ids.join(', '),
    });
    setSaveError(null);
    setFormOpen(true);
    setExpandedId(null);
  };

  const submit = async () => {
    if (!form.vendor_name.trim() || !form.service_category || !form.description.trim()) {
      setSaveError('Vendor, category, and description are required.');
      return;
    }
    if (form.started_on && form.ended_on && form.ended_on < form.started_on) {
      setSaveError('End date must be on or after start date.');
      return;
    }
    if (form.fee_amount.trim() && !form.billing_model) {
      setSaveError('A billing model is required when a monthly fee is entered.');
      return;
    }
    const fee = form.fee_amount.trim() ? Number(form.fee_amount) : null;
    if (fee !== null && !Number.isFinite(fee)) {
      setSaveError('Monthly fee must be a valid number.');
      return;
    }

    const payload: ThirdPartyServiceCreate = {
      vendor_name: form.vendor_name.trim(),
      service_category: form.service_category,
      engagement_status: form.engagement_status,
      description: form.description.trim(),
      sow_reference: form.sow_reference.trim() || null,
      contract_reference: form.contract_reference.trim() || null,
      started_on: form.started_on || null,
      ended_on: form.ended_on || null,
      billing_model: form.billing_model || null,
      fee_amount: form.billing_model ? fee : null,
      verification_state: form.verification_state as VerificationState,
      notes: form.notes.trim() || null,
      use_case_ids: parseIds(form.related_use_case_ids),
    };

    setSaving(true);
    setSaveError(null);
    try {
      if (editingId !== null) await api.updateThirdPartyService(editingId, payload);
      else await api.createThirdPartyService(customerId, payload);
      setFormOpen(false);
      await load();
    } catch (err: any) {
      setSaveError(err?.message || 'Failed to save third-party service');
    } finally {
      setSaving(false);
    }
  };

  const deleteService = async (id: number) => {
    setConfirmDeleteId(null);
    try {
      await api.deleteThirdPartyService(id);
      if (expandedId === id) setExpandedId(null);
      await load();
    } catch (err: any) {
      setError(err?.message || 'Failed to delete third-party service');
    }
  };

  const loadDocuments = async (serviceId: number) => {
    setDocumentsLoadingId(serviceId);
    setDocumentError(null);
    try {
      const items = await api.listThirdPartyServiceDocuments(serviceId);
      setDocuments((current) => ({ ...current, [serviceId]: items }));
    } catch (err: any) {
      setDocumentError(err?.message || 'Failed to load documents');
    } finally {
      setDocumentsLoadingId(null);
    }
  };

  const toggleExpanded = (serviceId: number) => {
    const next = expandedId === serviceId ? null : serviceId;
    setExpandedId(next);
    setDocumentForm(emptyDocumentForm());
    setDocumentError(null);
    setConfirmDocumentDeleteId(null);
    if (next !== null) loadDocuments(next);
  };

  const uploadDocument = async (serviceId: number) => {
    if (!documentForm.file || !documentForm.document_type) {
      setDocumentError('Document type and file are required.');
      return;
    }
    setDocumentBusy(true);
    setDocumentError(null);
    try {
      await api.uploadThirdPartyServiceDocument(
        serviceId,
        documentForm.file,
        documentForm.document_type,
        documentForm.title || undefined,
      );
      setDocumentForm(emptyDocumentForm());
      await loadDocuments(serviceId);
    } catch (err: any) {
      setDocumentError(err?.message || 'Failed to upload document');
    } finally {
      setDocumentBusy(false);
    }
  };

  const downloadDocument = async (document: ThirdPartyServiceDocument) => {
    setDocumentError(null);
    try {
      const blob = await api.downloadThirdPartyServiceDocument(document.id);
      const url = URL.createObjectURL(blob);
      const anchor = window.document.createElement('a');
      anchor.href = url;
      anchor.download = document.file_name;
      window.document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      URL.revokeObjectURL(url);
    } catch (err: any) {
      setDocumentError(err?.message || 'Failed to download document');
    }
  };

  const deleteDocument = async (serviceId: number, documentId: number) => {
    setConfirmDocumentDeleteId(null);
    setDocumentBusy(true);
    setDocumentError(null);
    try {
      await api.deleteThirdPartyServiceDocument(serviceId, documentId);
      await loadDocuments(serviceId);
    } catch (err: any) {
      setDocumentError(err?.message || 'Failed to delete document');
    } finally {
      setDocumentBusy(false);
    }
  };

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '16px', gap: '12px' }}>
        <div>
          <h2 style={{ margin: 0, fontSize: '1.15rem', color: 'var(--ink)' }}>Third-Party Professional Services</h2>
          <div style={{ fontSize: '0.8rem', color: 'var(--neutral-500)' }}>
            Customer engagements with systems integrators, MSPs, consultants, and other service partners.
          </div>
        </div>
        {canEdit && (
          <button role="button" aria-label="Add third-party service" onClick={startCreate}
            style={{ padding: '10px 18px', background: 'var(--brand-500)', color: 'var(--neutral-0)', border: 'none', borderRadius: 'var(--radius)', cursor: 'pointer', fontSize: '0.9rem', fontWeight: 600 }}>
            ➕ Add Service
          </button>
        )}
      </div>

      <div style={{ display: 'flex', gap: '10px', flexWrap: 'wrap', marginBottom: '16px' }}>
        <select aria-label="Filter third-party services by status" value={statusFilter} onChange={(event) => setStatusFilter(event.target.value)} style={{ ...inputStyle, minWidth: '160px' }}>
          <option value="">All statuses</option>
          {ENGAGEMENT_STATUSES.map((status) => <option key={status} value={status}>{formatEngagementStatus(status)}</option>)}
        </select>
        <select aria-label="Filter third-party services by category" value={categoryFilter} onChange={(event) => setCategoryFilter(event.target.value)} style={{ ...inputStyle, minWidth: '190px' }}>
          <option value="">All categories</option>
          {SERVICE_CATEGORIES.map((category) => <option key={category} value={category}>{formatServiceCategory(category)}</option>)}
        </select>
        <input aria-label="Search third-party services" placeholder="Search vendor / description / SOW…" value={search} onChange={(event) => setSearch(event.target.value)} style={{ ...inputStyle, flex: '1 1 240px' }} />
      </div>

      {error && <div role="alert" style={{ padding: '10px 14px', background: 'rgba(220,53,69,0.1)', color: 'var(--status-negative)', borderRadius: 'var(--radius)', marginBottom: '12px', fontSize: '0.85rem' }}>{error}</div>}

      {formOpen && (
        <div role="dialog" aria-label={editingId === null ? 'Add third-party service' : 'Edit third-party service'} style={{ background: 'var(--neutral-0)', borderRadius: 'var(--radius)', padding: '16px', boxShadow: 'var(--shadow-card)', marginBottom: '16px' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '12px' }}>
            <h3 style={{ margin: 0, fontSize: '1rem' }}>{editingId === null ? 'Add Third-Party Service' : 'Edit Third-Party Service'}</h3>
            <button role="button" aria-label="Close third-party service form" onClick={() => setFormOpen(false)} style={{ background: 'none', border: 'none', cursor: 'pointer', fontSize: '1rem' }}>✕</button>
          </div>
          {saveError && <div role="alert" style={{ padding: '8px 12px', background: 'rgba(220,53,69,0.1)', color: 'var(--status-negative)', borderRadius: 'var(--radius)', marginBottom: '12px', fontSize: '0.85rem' }}>{saveError}</div>}
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(210px, 1fr))', gap: '12px' }}>
            <Field label="Vendor *"><input aria-label="Vendor" style={inputStyle} value={form.vendor_name} onChange={(event) => set('vendor_name', event.target.value)} /></Field>
            <Field label="Category *"><select aria-label="Service category" style={inputStyle} value={form.service_category} onChange={(event) => set('service_category', event.target.value)}><option value="">Select…</option>{SERVICE_CATEGORIES.map((category) => <option key={category} value={category}>{formatServiceCategory(category)}</option>)}</select></Field>
            <Field label="Status"><select aria-label="Engagement status" style={inputStyle} value={form.engagement_status} onChange={(event) => set('engagement_status', event.target.value)}>{ENGAGEMENT_STATUSES.map((status) => <option key={status} value={status}>{formatEngagementStatus(status)}</option>)}</select></Field>
            <Field label="Verification state"><select aria-label="Service verification state" style={inputStyle} value={form.verification_state} onChange={(event) => set('verification_state', event.target.value)}>{VERIFICATION_STATES.map((state) => <option key={state} value={state}>{formatEngagementStatus(state)}</option>)}</select></Field>
            <Field label="Start date"><input aria-label="Service start date" type="date" style={inputStyle} value={form.started_on} onChange={(event) => set('started_on', event.target.value)} /></Field>
            <Field label="End date"><input aria-label="Service end date" type="date" style={inputStyle} value={form.ended_on} onChange={(event) => set('ended_on', event.target.value)} /></Field>
            <Field label="Billing model"><select aria-label="Billing model" style={inputStyle} value={form.billing_model} onChange={(event) => set('billing_model', event.target.value)}><option value="">—</option>{BILLING_MODELS.map((model) => <option key={model} value={model}>{formatBillingModel(model)}</option>)}</select></Field>
            {form.billing_model && <Field label="Monthly fee (30 days)"><input aria-label="Monthly fee" type="number" step="0.01" style={inputStyle} value={form.fee_amount} onChange={(event) => set('fee_amount', event.target.value)} /></Field>}
            <Field label="SOW reference"><input aria-label="SOW reference" style={inputStyle} value={form.sow_reference} onChange={(event) => set('sow_reference', event.target.value)} /></Field>
            <Field label="Contract / PO reference"><input aria-label="Contract or PO reference" style={inputStyle} value={form.contract_reference} onChange={(event) => set('contract_reference', event.target.value)} /></Field>
            <Field label="Related use case ids (comma-sep.)"><input aria-label="Related use case ids" placeholder="e.g. 3, 4" style={inputStyle} value={form.related_use_case_ids} onChange={(event) => set('related_use_case_ids', event.target.value)} /></Field>
          </div>
          <div style={{ display: 'grid', gap: '12px', marginTop: '12px' }}>
            <Field label="Description *"><textarea aria-label="Service description" rows={3} style={inputStyle} value={form.description} onChange={(event) => set('description', event.target.value)} /></Field>
            <Field label="Notes"><textarea aria-label="Service notes" rows={2} style={inputStyle} value={form.notes} onChange={(event) => set('notes', event.target.value)} /></Field>
          </div>
          <div style={{ display: 'flex', gap: '10px', marginTop: '14px' }}>
            <button role="button" aria-label="Save third-party service" disabled={saving} onClick={submit} style={{ padding: '10px 18px', background: saving ? 'var(--neutral-300)' : 'var(--brand-500)', color: saving ? 'var(--neutral-700)' : 'var(--neutral-0)', border: 'none', borderRadius: 'var(--radius)', cursor: saving ? 'not-allowed' : 'pointer', fontSize: '0.9rem', fontWeight: 600 }}>{saving ? 'Saving…' : editingId === null ? 'Add Service' : 'Save Changes'}</button>
            <button role="button" aria-label="Cancel third-party service form" onClick={() => setFormOpen(false)} style={{ padding: '10px 18px', background: 'var(--neutral-0)', color: 'var(--neutral-600)', border: '1px solid var(--divider)', borderRadius: 'var(--radius)', cursor: 'pointer', fontSize: '0.9rem' }}>Cancel</button>
          </div>
        </div>
      )}

      {loading ? (
        <div role="status" style={{ padding: '24px', textAlign: 'center', color: 'var(--neutral-500)' }}>Loading…</div>
      ) : filtered.length === 0 ? (
        <div style={{ padding: '24px', textAlign: 'center', color: 'var(--neutral-500)', background: 'var(--neutral-0)', borderRadius: 'var(--radius)' }}>{services.length === 0 ? 'No third-party services recorded yet.' : 'No services match the current filters.'}</div>
      ) : filtered.map((service) => {
        const expanded = expandedId === service.id;
        const badge = statusColors(service.engagement_status);
        const serviceDocuments = documents[service.id] || [];
        return (
          <div key={service.id} style={{ background: 'var(--neutral-0)', borderRadius: 'var(--radius)', boxShadow: 'var(--shadow-card)', marginBottom: '8px', overflow: 'hidden' }}>
            <div role="button" tabIndex={0} aria-label={`Expand ${service.vendor_name} service`} onClick={() => toggleExpanded(service.id)} onKeyDown={(event) => { if (event.key === 'Enter' || event.key === ' ') toggleExpanded(service.id); }} style={{ display: 'flex', alignItems: 'center', gap: '10px', padding: '12px 14px', cursor: 'pointer', flexWrap: 'wrap' }}>
              <span style={{ fontSize: '0.7rem', color: badge.fg, background: badge.bg, borderRadius: '10px', padding: '2px 8px', fontWeight: 600 }}>{formatEngagementStatus(service.engagement_status)}</span>
              <span style={{ fontSize: '0.7rem', color: 'var(--neutral-0)', background: 'var(--brand-500)', borderRadius: '10px', padding: '2px 8px', fontWeight: 600 }}>{formatServiceCategory(service.service_category)}</span>
              <span style={{ fontWeight: 600, color: 'var(--ink)', fontSize: '0.92rem', flex: '1 1 180px' }}>{service.vendor_name}</span>
              <span style={{ fontSize: '0.78rem', color: 'var(--neutral-600)' }}>{monthlyFee(service)}</span>
              <span style={{ fontSize: '0.78rem', color: 'var(--neutral-500)' }}>{service.started_on || '—'} → {service.ended_on || '—'}</span>
            </div>
            {expanded && (
              <div style={{ padding: '12px 14px', borderTop: '1px solid var(--divider)', fontSize: '0.85rem' }}>
                <div style={{ color: 'var(--ink)', whiteSpace: 'pre-wrap', marginBottom: '10px' }}>{service.description}</div>
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(155px, 1fr))', gap: '10px', fontSize: '0.8rem' }}>
                  {[
                    ['SOW reference', service.sow_reference || '—'],
                    ['Contract / PO', service.contract_reference || '—'],
                    ['Verification', formatEngagementStatus(service.verification_state)],
                    ['Related use cases', service.related_use_case_ids.join(', ') || '—'],
                    ['Notes', service.notes || '—'],
                  ].map(([label, value]) => <div key={label}><div style={{ color: 'var(--neutral-500)', fontSize: '0.7rem', textTransform: 'uppercase', letterSpacing: '0.3px' }}>{label}</div><div style={{ color: 'var(--ink)', whiteSpace: 'pre-wrap' }}>{value}</div></div>)}
                </div>
                {canEdit && <div style={{ display: 'flex', gap: '10px', marginTop: '12px' }}>
                  <button role="button" aria-label="Edit third-party service" onClick={() => startEdit(service)} style={{ padding: '6px 14px', background: 'var(--neutral-0)', color: 'var(--brand-700)', border: '1px solid var(--brand-500)', borderRadius: 'var(--radius)', cursor: 'pointer', fontSize: '0.8rem', fontWeight: 600 }}>✏️ Edit</button>
                  {confirmDeleteId === service.id ? <button role="button" aria-label="Confirm delete third-party service" onClick={() => deleteService(service.id)} style={{ padding: '6px 14px', background: 'var(--status-negative)', color: 'var(--neutral-0)', border: 'none', borderRadius: 'var(--radius)', cursor: 'pointer', fontSize: '0.8rem', fontWeight: 600 }}>Confirm delete?</button> : <button role="button" aria-label="Delete third-party service" onClick={() => setConfirmDeleteId(service.id)} style={{ padding: '6px 14px', background: 'var(--neutral-0)', color: 'var(--status-negative)', border: '1px solid var(--status-negative)', borderRadius: 'var(--radius)', cursor: 'pointer', fontSize: '0.8rem' }}>🗑️ Delete</button>}
                </div>}

                <div style={{ marginTop: '16px', paddingTop: '14px', borderTop: '1px solid var(--divider)' }}>
                  <h4 style={{ margin: '0 0 10px', color: 'var(--ink)', fontSize: '0.9rem' }}>Documents</h4>
                  {documentError && <div role="alert" style={{ padding: '8px 10px', background: 'rgba(220,53,69,0.1)', color: 'var(--status-negative)', borderRadius: 'var(--radius)', marginBottom: '10px' }}>{documentError}</div>}
                  {canEdit && <div style={{ display: 'grid', gridTemplateColumns: 'minmax(130px, 180px) minmax(180px, 1fr) minmax(190px, 1fr) auto', gap: '8px', alignItems: 'end', marginBottom: '12px' }}>
                    <Field label="Document type *"><select aria-label="Document type" style={inputStyle} value={documentForm.document_type} onChange={(event) => setDocumentForm((current) => ({ ...current, document_type: event.target.value }))}><option value="">Select…</option>{DOCUMENT_TYPES.map((type) => <option key={type} value={type}>{formatDocumentType(type)}</option>)}</select></Field>
                    <Field label="Title"><input aria-label="Document title" style={inputStyle} value={documentForm.title} onChange={(event) => setDocumentForm((current) => ({ ...current, title: event.target.value }))} /></Field>
                    <Field label="File *"><input aria-label="Third-party service document file" type="file" style={inputStyle} onChange={(event) => setDocumentForm((current) => ({ ...current, file: event.target.files?.[0] || null }))} /></Field>
                    <button role="button" aria-label="Upload third-party service document" disabled={documentBusy} onClick={() => uploadDocument(service.id)} style={{ padding: '9px 14px', background: documentBusy ? 'var(--neutral-300)' : 'var(--brand-500)', color: documentBusy ? 'var(--neutral-700)' : 'var(--neutral-0)', border: 'none', borderRadius: 'var(--radius)', cursor: documentBusy ? 'not-allowed' : 'pointer', fontSize: '0.8rem', fontWeight: 600 }}>{documentBusy ? 'Uploading…' : 'Upload'}</button>
                  </div>}
                  {documentsLoadingId === service.id ? <div role="status" style={{ color: 'var(--neutral-500)', padding: '8px 0' }}>Loading documents…</div> : serviceDocuments.length === 0 ? <div style={{ color: 'var(--neutral-500)', padding: '8px 0' }}>No documents uploaded.</div> : serviceDocuments.map((document) => <div key={document.id} style={{ display: 'flex', gap: '10px', alignItems: 'center', padding: '8px 0', borderTop: '1px solid var(--divider)', flexWrap: 'wrap' }}>
                    <span style={{ fontSize: '0.68rem', color: 'var(--neutral-0)', background: 'var(--brand-700)', borderRadius: '10px', padding: '2px 8px', fontWeight: 600 }}>{formatDocumentType(document.document_type)}</span>
                    <span style={{ color: 'var(--ink)', fontWeight: 600 }}>{document.file_name}</span>
                    <span style={{ color: 'var(--neutral-500)', flex: '1 1 160px' }}>{document.title || '—'}</span>
                    <button role="button" aria-label={`Download ${document.file_name}`} onClick={() => downloadDocument(document)} style={{ padding: 0, background: 'none', border: 'none', color: 'var(--brand-700)', cursor: 'pointer', fontSize: '0.8rem', textDecoration: 'underline' }}>Download</button>
                    {canEdit && (confirmDocumentDeleteId === document.id ? <button role="button" aria-label={`Confirm delete document ${document.file_name}`} disabled={documentBusy} onClick={() => deleteDocument(service.id, document.id)} style={{ padding: '5px 10px', background: 'var(--status-negative)', border: 'none', borderRadius: 'var(--radius)', color: 'var(--neutral-0)', cursor: 'pointer', fontSize: '0.75rem' }}>Confirm delete?</button> : <button role="button" aria-label={`Delete document ${document.file_name}`} onClick={() => setConfirmDocumentDeleteId(document.id)} style={{ padding: '5px 10px', background: 'var(--neutral-0)', border: '1px solid var(--status-negative)', borderRadius: 'var(--radius)', color: 'var(--status-negative)', cursor: 'pointer', fontSize: '0.75rem' }}>Delete</button>)}
                  </div>)}
                </div>
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}

export default ThirdPartyServices;
