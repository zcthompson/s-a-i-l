import { ActionButton } from './ActionButton';
import { useState, useEffect, useRef } from 'react';
import { createPortal } from 'react-dom';
import type { UseCase, UseCaseCreate, Customer } from '../types/use_case';
import { api } from '../lib/api';
import { loadTemplates, TemplateData } from '../lib/templates';

type Step = 'template' | 'basic' | 'goals' | 'challenges' | 'painpoints' | 'impact' | 'review';
type TemplateChoice = 'none' | string;

interface AssessmentFormProps {
  // FE-06: save callbacks are async; the form awaits them and owns the
  // failure (a rejected callback surfaces submitError with the input kept —
  // Home's handlers rethrow instead of swallowing the error).
  onSubmit: (data: UseCaseCreate) => void | Promise<void>;
  onCancel: () => void;
  onEdit?: (data: UseCaseCreate) => void | Promise<void>;
  editMode?: boolean;
  initialData?: UseCase | null;
  // Create mode only: pre-select this customer (customer-dashboard context)
  // so the user does not re-pick the customer they are already viewing.
  initialCustomerName?: string;
  // FE-12: notify the parent when the draft becomes dirty / clean so it can
  // guard navigation (sidebar, browser unload). One signal, no content
  // transmitted.
  onDirtyChange?: (dirty: boolean) => void;
}

export function AssessmentForm({ onSubmit, onCancel, onEdit, editMode = false, initialData = null, initialCustomerName, onDirtyChange }: AssessmentFormProps) {
  // FE-02: record field initialization happens ONLY in edit mode. Create
  // mode must start blank even if Home still holds a previously viewed
  // record (the old code initialized every field from initialData in both
  // modes). Intentional customer preselection is a separate concern
  // (initialCustomerName / the edit preselection effect below).
  const src = editMode ? initialData : null;
  const [step, setStep] = useState<Step>(editMode ? 'basic' : 'template');
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [selectedTemplate, setSelectedTemplate] = useState<TemplateData | null>(null);
  const [selectedTemplateChoice, setSelectedTemplateChoice] = useState<TemplateChoice>('none');

  const [title, setTitle] = useState(src?.title || '');
  const [description, setDescription] = useState(src?.description || '');
  const [department, setDepartment] = useState(src?.department || '');
  const [goals, setGoals] = useState<string[]>(src?.goals && src.goals.length > 0 ? [...src.goals] : ['', '', '']);
  const [challenges, setChallenges] = useState<string[]>(src?.challenges && src.challenges.length > 0 ? [...src.challenges] : ['', '', '']);
  const [painPoints, setPainPoints] = useState<string[]>(src?.pain_points && src.pain_points.length > 0 ? [...src.pain_points] : ['', '']);
  const [impactCategory, setImpactCategory] = useState(src?.impact_category || '');
  const [impactDescription, setImpactDescription] = useState(src?.impact_description || '');
  const [estimatedSavings, setEstimatedSavings] = useState<number | undefined>(src?.estimated_savings);
  const [estimatedRevenue, setEstimatedRevenue] = useState<number | undefined>(src?.estimated_revenue);
  const [timeline, setTimeline] = useState(src?.timeline_estimate || '');

  // Customer/department state — IDs (integers), not names
  const [customers, setCustomers] = useState<Customer[]>([]);
  const [selectedCustomerName, setSelectedCustomerName] = useState<string>('');
  const [selectedCustomerId, setSelectedCustomerId] = useState<number | null>(null);
  const [newCustomerName, setNewCustomerName] = useState('');
  const [newCustomerDesc, setNewCustomerDesc] = useState('');
  const [newCustomerVertical, setNewCustomerVertical] = useState('');
  const [verticals, setVerticals] = useState<string[]>([]);
  const [templates, setTemplates] = useState<TemplateData[]>([]);
  const [templatesLoading, setTemplatesLoading] = useState(!editMode);
  const [templatesError, setTemplatesError] = useState<string | null>(null);
  const [departments, setDepartments] = useState<{ id: number; name: string }[]>([]);
  // FE-02: department preselection from the record only in edit mode.
  const [selectedDepartmentId, setSelectedDepartmentId] = useState<number | null>(src?.department_id ?? null);
  const [creatingCustomer, setCreatingCustomer] = useState(false);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [deptLoadError, setDeptLoadError] = useState<string | null>(null);

  // FE-12: dirty-state tracking. Snapshot the meaningful draft fields on
  // mount (from the edit-mode record or blank) and compare — the form is
  // "dirty" when any field differs from that initial draft. Navigation
  // (Cancel, sidebar, browser unload) is guarded while dirty; a clean form
  // or a successful save navigates without prompting.
  const initialDraft = useRef<string>(JSON.stringify({
    title: src?.title || '',
    description: src?.description || '',
    department: src?.department || '',
    goals: src?.goals && src.goals.length ? src.goals : ['', '', ''],
    challenges: src?.challenges && src.challenges.length ? src.challenges : ['', '', ''],
    painPoints: src?.pain_points && src.pain_points.length ? src.pain_points : ['', ''],
    impactCategory: src?.impact_category || '',
    impactDescription: src?.impact_description || '',
    estimatedSavings: src?.estimated_savings,
    estimatedRevenue: src?.estimated_revenue,
    timeline: src?.timeline_estimate || '',
  }));
  const isDirty = JSON.stringify({
    title, description, department, goals, challenges, painPoints,
    impactCategory, impactDescription, estimatedSavings, estimatedRevenue, timeline,
  }) !== initialDraft.current;
  const [confirmDiscard, setConfirmDiscard] = useState(false);

  // FE-12: surface the dirty flag to the parent (sidebar navigation guard).
  useEffect(() => { onDirtyChange?.(isDirty); }, [isDirty, onDirtyChange]);
  // FE-12: warn before browser unload / tab close while a draft is dirty.
  useEffect(() => {
    if (!isDirty) return;
    const handler = (e: BeforeUnloadEvent) => {
      e.preventDefault();
      e.returnValue = '';
    };
    window.addEventListener('beforeunload', handler);
    return () => window.removeEventListener('beforeunload', handler);
  }, [isDirty]);

  const handleCancel = () => {
    if (isDirty) {
      setConfirmDiscard(true);
      return;
    }
    onCancel();
  };

  useEffect(() => {
    loadCustomers();
    api.listVerticals().then((v) => setVerticals(v.verticals)).catch(() => setVerticals([]));
    if (!editMode) {
      loadTemplates()
        .then((t) => { setTemplates(t); setTemplatesError(null); })
        .catch(() => setTemplatesError('Failed to load templates'))
        .finally(() => setTemplatesLoading(false));
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps -- pre-existing dependency list; change only with UI verification
  }, []);

  // FE-02: switching customers must clear the (previous customer's)
  // department so it can never be saved under the new one. The clear is
  // user-driven (select onChange / new-customer) + the "customer emptied"
  // transition — NOT a blanket effect on every name change, so the
  // edit-mode preselect and its initial empty-name run keep the record's own
  // department.
  const everHadCustomerRef = useRef(false);
  useEffect(() => {
    if (selectedCustomerName) {
      everHadCustomerRef.current = true;
      loadDepartmentsForCustomer(selectedCustomerName.trim());
    } else if (everHadCustomerRef.current) {
      // The user cleared the customer selection.
      setDepartments([]);
      setSelectedDepartmentId(null);
    }
    // else: initial mount (edit mode still holds the record's department).
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedCustomerName]);

  // If editing, pre-select the existing customer — both NAME and ID
  // (the previous effect set only the name, so the payload could carry a
  // null customer_id in edit mode).
  useEffect(() => {
    if (editMode && initialData?.customer_id) {
      const existing = customers.find(c => c.id === initialData.customer_id);
      if (existing) {
        setSelectedCustomerName(existing.name);
        setSelectedCustomerId(existing.id);
        loadDepartmentsForCustomer(existing.name);
      }
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps -- pre-existing dependency list; change only with UI verification
  }, [editMode, initialData, customers]);

  const loadCustomers = async () => {
    try {
      const data = await api.listCustomers();
      setCustomers(data);
      setLoadError(null);
      // Customer-dashboard context (create mode): pre-select the current
      // customer; the [selectedCustomerName] effect loads its departments.
      if (!editMode && initialCustomerName) {
        const existing = data.find(c => c.name === initialCustomerName);
        if (existing) {
          setSelectedCustomerName(existing.name);
          setSelectedCustomerId(existing.id);
        }
      }
    } catch (err: any) {
      setLoadError(err.message || 'Failed to load customers. Please try again.');
    } finally {
      setLoading(false);
    }
  };

  const loadDepartmentsForCustomer = async (customerName: string) => {
    try {
      const data = await api.listDepartments(customerName);
      // FE-05: stale-response guard — only commit departments for the customer
      // the form CURRENTLY shows. A late response for a previous customer must
      // not populate (or error) the new customer's department list.
      if (customerName !== selectedCustomerName.trim()) return;
      setDepartments(data);
      setDeptLoadError(null);
    } catch (err: any) {
      if (customerName !== selectedCustomerName.trim()) return;
      setDepartments([]);
      // Distinguish a load failure from "customer has no departments"
      setDeptLoadError(err.message || 'Failed to load departments. Please try again.');
    }
  };

  const createCustomer = async () => {
    if (!newCustomerName.trim()) return;
    try {
      setCreatingCustomer(true);
      const customer = await api.createCustomer({
        name: newCustomerName.trim(),
        description: newCustomerDesc.trim() || undefined,
        vertical: newCustomerVertical || undefined,
      });
      setCustomers(prev => [...prev, customer]);
      setSelectedCustomerName(customer.name);
      setSelectedCustomerId(customer.id);
      // FE-02: a freshly created customer has no departments; clear any
      // stale department from the previous customer.
      setSelectedDepartmentId(null);
      setNewCustomerName('');
      setNewCustomerDesc('');
      setNewCustomerVertical('');
    } catch (err: any) {
      setSubmitError(err.message || 'Failed to create customer');
    } finally {
      setCreatingCustomer(false);
    }
  };

  const addGoal = () => setGoals([...goals, '']);
  const updateGoal = (i: number, v: string) => { setGoals(goals.map((g, idx) => idx === i ? v : g)); };
  const removeGoal = (i: number) => setGoals(goals.filter((_, idx) => idx !== i));

  const addChallenge = () => setChallenges([...challenges, '']);
  const updateChallenge = (i: number, v: string) => { setChallenges(challenges.map((c, idx) => idx === i ? v : c)); };
  const removeChallenge = (i: number) => setChallenges(challenges.filter((_, idx) => idx !== i));

  const addPainPoint = () => setPainPoints([...painPoints, '']);
  const updatePainPoint = (i: number, v: string) => { setPainPoints(painPoints.map((p, idx) => idx === i ? v : p)); };
  const removePainPoint = (i: number) => setPainPoints(painPoints.filter((_, idx) => idx !== i));

  const submit = async () => {
    setSubmitError(null);
    if (!selectedCustomerName.trim()) {
      setSubmitError('Please select or create a customer.');
      return;
    }

    const data: UseCaseCreate = {
      title,
      description: description || (selectedTemplate?.description || undefined),
      customer_id: selectedCustomerId !== null ? selectedCustomerId : undefined,
      department_id: selectedDepartmentId ?? undefined,
      department: department || (selectedTemplate?.department || undefined),
      goals: goals.filter(g => g.trim()).length > 0 ? goals.filter(g => g.trim()) : (selectedTemplate?.goals || []),
      challenges: challenges.filter(c => c.trim()).length > 0 ? challenges.filter(c => c.trim()) : (selectedTemplate?.challenges || []),
      pain_points: painPoints.filter(p => p.trim()).length > 0 ? painPoints.filter(p => p.trim()) : (selectedTemplate?.painPoints || []),
      impact_category: impactCategory || (selectedTemplate?.impactCategory || undefined),
      impact_description: impactDescription || (selectedTemplate?.impactDescription || undefined),
      estimated_savings: estimatedSavings,
      estimated_revenue: estimatedRevenue,
      timeline_estimate: timeline || (selectedTemplate?.timeline || undefined),
    };
    try {
      setSubmitting(true);
      if (editMode && onEdit) {
        await onEdit(data);
      } else {
        await onSubmit(data);
      }
      // FE-12: a successful save is no longer a dirty draft — reset the
      // baseline so the (subsequent) navigation does not prompt.
      initialDraft.current = JSON.stringify({
        title, description, department, goals, challenges, painPoints,
        impactCategory, impactDescription, estimatedSavings, estimatedRevenue, timeline,
      });
    } catch (err: any) {
      setSubmitError(err.message || 'Submission failed');
    } finally {
      setSubmitting(false);
    }
  };

  const steps: Step[] = ['basic', 'goals', 'challenges', 'painpoints', 'impact', 'review'];
  const templateSteps: Step[] = editMode ? steps : ['template', ...steps];
  // FE-07: single step-ID→label definition. Labels, step count, and progress
  // all derive from the visible `templateSteps` + this map — so edit mode
  // (which omits the template step) shows "Step 1: Basic Info", not the
  // stale "Step 1: Select Template".
  const STEP_LABEL: Record<Step, string> = {
    template: 'Select Template',
    basic: 'Basic Info',
    goals: 'Goals',
    challenges: 'Challenges',
    painpoints: 'Pain Points',
    impact: 'Business Impact',
    review: 'Review',
  };
  const currentIdx = templateSteps.indexOf(step);
  const stepLabel = STEP_LABEL[step];
  const isFirstStep = editMode ? step === 'basic' : step === 'template';
  const isLastStep = step === 'review';

  const renderStep = () => {
    switch (step) {
      case 'template': return (
        <div>
          <h3 style={{ margin: '0 0 12px 0', color: 'var(--neutral-700)' }}>Select a Template</h3>
          <p style={{ margin: '0 0 20px 0', color: 'var(--neutral-500)', fontSize: '0.9rem' }}>Choose a pre-built assessment template or start blank.</p>
          {templatesLoading && (
            <div role="status" aria-live="polite" style={{ padding: '16px', textAlign: 'center', color: 'var(--neutral-500)' }}>Loading templates…</div>
          )}
          {templatesError && (
            <div role="alert" style={{ padding: '12px 16px', background: 'var(--status-negative-soft)', borderLeft: '4px solid var(--status-negative)', marginBottom: '12px', borderRadius: 'var(--radius-sm)', color: 'var(--status-negative)' }}>{templatesError}</div>
          )}
          <div style={{ display: 'grid', gap: '12px' }}>
            {templates.map((template) => (
              <div
                key={template.id}
                role="button"
                tabIndex={0}
                aria-label={`Select ${template.name} template`}
                onClick={() => {
                  setSelectedTemplate(template);
                  setSelectedTemplateChoice(template.id);
                }}
                onKeyDown={(event) => {
                  if (event.key === 'Enter' || event.key === ' ') {
                    event.preventDefault();
                    setSelectedTemplate(template);
                    setSelectedTemplateChoice(template.id);
                  }
                }}
                style={{
                  padding: '16px',
                  border: selectedTemplateChoice === template.id ? '2px solid var(--brand-500)' : '1px solid var(--divider)',
                  borderRadius: 'var(--radius)',
                  background: selectedTemplateChoice === template.id ? 'var(--brand-100)' : 'var(--neutral-0)',
                  cursor: 'pointer',
                  transition: 'all 0.2s',
                }}
              >
                <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
                  <span style={{ fontSize: '2rem' }}>{template.icon}</span>
                  <div style={{ flex: 1 }}>
                    <div style={{ fontWeight: 600, color: 'var(--ink)', marginBottom: '4px' }}>{template.name}</div>
                    <div style={{ fontSize: '0.85rem', color: 'var(--neutral-500)' }}>{template.description.substring(0, 100)}...</div>
                    <div style={{ marginTop: '6px', display: 'flex', gap: '8px' }}>
                      <span style={{ fontSize: '0.75rem', background: 'var(--brand-50)', color: 'var(--brand-700)', padding: '2px 8px', borderRadius: 'var(--radius-pill)' }}>
                        {template.department}
                      </span>
                      <span style={{ fontSize: '0.75rem', color: 'var(--neutral-500)' }}>
                        {template.goals.length} goals · {template.challenges.length} challenges
                      </span>
                    </div>
                  </div>
                  <div style={{ color: selectedTemplateChoice === template.id ? 'var(--brand-500)' : 'var(--divider)', fontSize: '1.5rem' }}>
                    {selectedTemplateChoice === template.id ? '✓' : '○'}
                  </div>
                </div>
              </div>
            ))}
          </div>
          <div style={{ marginTop: '16px', paddingTop: '16px', borderTop: '1px solid var(--divider)' }}>
            <button role="button" aria-label="Start a blank assessment"
              onClick={() => {
                setSelectedTemplate(null);
                setSelectedTemplateChoice('none');
              }}
              style={{
                padding: '12px 24px',
                background: selectedTemplateChoice === 'none' ? 'var(--brand-100)' : 'var(--neutral-0)',
                border: selectedTemplateChoice === 'none' ? '2px solid var(--brand-500)' : '1px solid var(--divider)',
                borderRadius: 'var(--radius)',
                cursor: 'pointer',
                fontSize: '0.95rem',
                fontWeight: selectedTemplateChoice === 'none' ? 600 : 400,
                color: selectedTemplateChoice === 'none' ? 'var(--brand-700)' : 'var(--neutral-500)',
                width: '100%',
                transition: 'all 0.2s',
              }}
            >
              + Start Blank Assessment
            </button>
          </div>
        </div>
      );
      case 'basic': return (
        <div>
          {/* Customer selection */}
          <div style={{ marginBottom: 16 }}>
            <label style={labelStyle}>Customer *</label>
            <select aria-label="Assessment Form selection"
              style={inputStyle}
              value={selectedCustomerName}
              onChange={e => {
                // FE-02: switching customers clears the previous customer's
                // department (a stale department must never be saved under the
                // new customer).
                setSelectedCustomerName(e.target.value);
                const found = customers.find(c => c.name === e.target.value);
                setSelectedCustomerId(found?.id ?? null);
                setSelectedDepartmentId(null);
              }}
              disabled={loading}
            >
              <option value="">— Select a customer —</option>
              {customers.map(c => (
                <option key={c.id} value={c.name}>{c.name}</option>
              ))}
            </select>
          </div>

          {/* New customer inline form */}
          <div style={{ marginBottom: 16 }}>
            <label style={labelStyle}>New Customer</label>
            <div style={{ display: 'flex', gap: '8px' }}>
              <input aria-label="Customer name"
                style={{ ...inputStyle, flex: 1 }}
                placeholder="Customer name"
                value={newCustomerName}
                onChange={e => setNewCustomerName(e.target.value)}
                disabled={creatingCustomer}
              />
              <input aria-label="Description (optional)"
                style={{ ...inputStyle, flex: 1 }}
                placeholder="Description (optional)"
                value={newCustomerDesc}
                onChange={e => setNewCustomerDesc(e.target.value)}
                disabled={creatingCustomer}
              />
              <button role="button" aria-label="Create a new customer"
                onClick={createCustomer}
                disabled={creatingCustomer || !newCustomerName.trim()}
                style={{
                  padding: '10px 16px',
                  background: creatingCustomer || !newCustomerName.trim() ? 'var(--neutral-400)' : 'var(--status-positive)',
                  color: 'var(--neutral-0)',
                  border: 'none',
                  borderRadius: 'var(--radius)',
                  cursor: creatingCustomer || !newCustomerName.trim() ? 'not-allowed' : 'pointer',
                  fontSize: '0.85rem',
                  fontWeight: 600,
                  whiteSpace: 'nowrap',
                }}
              >
                {creatingCustomer ? '...' : '➕ New'}
              </button>
            </div>
            <select
              aria-label="New customer vertical"
              style={{ ...inputStyle, marginTop: 8 }}
              value={newCustomerVertical}
              onChange={e => setNewCustomerVertical(e.target.value)}
              disabled={creatingCustomer}
            >
              <option value="">Select vertical… (optional)</option>
              {verticals.map(v => <option key={v} value={v}>{v}</option>)}
            </select>
            {newCustomerVertical === 'Other' && (
              <p style={{ margin: '4px 0 0', color: 'var(--neutral-500)', fontSize: '0.8rem' }}>
                Describe the customer's industry in the description.
              </p>
            )}
          </div>

          {/* Department selection */}
          <div style={{ marginBottom: 16 }}>
            <label style={labelStyle}>Department</label>
            <select aria-label="Assessment Form selection"
              style={inputStyle}
              value={selectedDepartmentId ?? ''}
              onChange={e => {
                const val = e.target.value;
                setSelectedDepartmentId(val ? Number(val) : null);
                if (val === 'legacy') {
                  setDepartment('');
                } else if (val) {
                  const dept = departments.find(d => d.id === Number(val));
                  setDepartment(dept?.name || '');
                }
              }}
              disabled={loading || !selectedCustomerName}
            >
              <option value="">— Select a department —</option>
              {departments.map(d => (
                <option key={d.id} value={d.id}>{d.name}</option>
              ))}
              <option value="legacy">— Other (legacy department) —</option>
            </select>
            {selectedDepartmentId && departments.find(d => d.id === selectedDepartmentId) && (
              <p style={{ margin: '4px 0 0', color: 'var(--neutral-500)', fontSize: '0.8rem' }}>
                Selected: {departments.find(d => d.id === selectedDepartmentId)?.name}
              </p>
            )}
            {departments.length === 0 && selectedCustomerName && !deptLoadError && (
              <p style={{ margin: '4px 0 0', color: 'var(--neutral-500)', fontSize: '0.8rem' }}>
                No departments yet for {selectedCustomerName}. Create one in Customer view or select "Other".
              </p>
            )}
            {deptLoadError && departments.length === 0 && selectedCustomerName && (
              <p style={{ margin: '4px 0 0', color: 'var(--status-negative)', fontSize: '0.8rem' }} role="alert">
                {deptLoadError}{' '}
                <button
                  type="button"
                  aria-label="Retry loading departments"
                  onClick={() => loadDepartmentsForCustomer(selectedCustomerName)}
                  style={{ color: 'var(--status-negative)', fontSize: '0.8rem', cursor: 'pointer', background: 'none', border: 'none', padding: 0, textDecoration: 'underline' }}
                >
                  Retry
                </button>
              </p>
            )}
          </div>

          <div style={{ marginBottom: 16 }}>
            <label style={labelStyle}>Use Case Title *</label>
            <input aria-label="Assessment Form field" style={inputStyle} value={title} onChange={e => setTitle(e.target.value)} placeholder="e.g., AI-Powered Customer Support" />
          </div>
          <div style={{ marginBottom: 16 }}>
            <label style={labelStyle}>Description</label>
            <textarea aria-label="Assessment Form field" style={{ ...inputStyle, minHeight: 100 }} value={description} onChange={e => setDescription(e.target.value)} placeholder="Describe the use case and its purpose..." />
          </div>
        </div>
      );
      case 'goals': return (
        <div>
          <h3 style={{ margin: '0 0 12px 0', color: 'var(--neutral-700)' }}>Goals</h3>
          <p style={{ margin: '0 0 16px 0', color: 'var(--neutral-500)', fontSize: '0.9rem' }}>What objectives do you want this use case to achieve?</p>
          {goals.map((g, i) => (
            <div key={i} style={{ marginBottom: 10, display: 'flex', gap: 8, alignItems: 'center' }}>
              <span style={{ color: 'var(--brand-700)', fontWeight: 600, minWidth: 20 }}>{i + 1}.</span>
              <input aria-label="Assessment Form field" style={{ ...inputStyle, flex: 1 }} value={g} onChange={e => updateGoal(i, e.target.value)} placeholder={`Goal ${i + 1}`} />
              {goals.length > 1 && (
                <button role="button" aria-label={`Remove goal ${i + 1}`} onClick={() => removeGoal(i)} style={{ background: 'var(--status-negative-soft)', border: 'none', borderRadius: 'var(--radius-sm)', padding: '4px 8px', cursor: 'pointer', color: 'var(--status-negative)', fontSize: '0.8rem' }}>X</button>
              )}
            </div>
          ))}
          <button role="button" aria-label="Add a goal" onClick={addGoal} style={{ padding: '8px 16px', background: 'var(--neutral-100)', border: '1px dashed var(--neutral-400)', borderRadius: 'var(--radius)', cursor: 'pointer', color: 'var(--neutral-500)', fontSize: '0.85rem' }}>+ Add Goal</button>
        </div>
      );
      case 'challenges': return (
        <div>
          <h3 style={{ margin: '0 0 12px 0', color: 'var(--neutral-700)' }}>Challenges</h3>
          <p style={{ margin: '0 0 16px 0', color: 'var(--neutral-500)', fontSize: '0.9rem' }}>What challenges does this use case address?</p>
          {challenges.map((c, i) => (
            <div key={i} style={{ marginBottom: 10, display: 'flex', gap: 8, alignItems: 'center' }}>
              <span style={{ color: 'var(--brand-700)', fontWeight: 600, minWidth: 20 }}>{i + 1}.</span>
              <input aria-label="Assessment Form field" style={{ ...inputStyle, flex: 1 }} value={c} onChange={e => updateChallenge(i, e.target.value)} placeholder={`Challenge ${i + 1}`} />
              {challenges.length > 1 && (
                <button role="button" aria-label={`Remove challenge ${i + 1}`} onClick={() => removeChallenge(i)} style={{ background: 'var(--status-negative-soft)', border: 'none', borderRadius: 'var(--radius-sm)', padding: '4px 8px', cursor: 'pointer', color: 'var(--status-negative)', fontSize: '0.8rem' }}>X</button>
              )}
            </div>
          ))}
          <button role="button" aria-label="Add a challenge" onClick={addChallenge} style={{ padding: '8px 16px', background: 'var(--neutral-100)', border: '1px dashed var(--neutral-400)', borderRadius: 'var(--radius)', cursor: 'pointer', color: 'var(--neutral-500)', fontSize: '0.85rem' }}>+ Add Challenge</button>
        </div>
      );
      case 'painpoints': return (
        <div>
          <h3 style={{ margin: '0 0 12px 0', color: 'var(--neutral-700)' }}>Pain Points</h3>
          <p style={{ margin: '0 0 16px 0', color: 'var(--neutral-500)', fontSize: '0.9rem' }}>What specific pain points are driving this use case?</p>
          {painPoints.map((p, i) => (
            <div key={i} style={{ marginBottom: 10, display: 'flex', gap: 8, alignItems: 'center' }}>
              <span style={{ color: 'var(--brand-700)', fontWeight: 600, minWidth: 20 }}>{i + 1}.</span>
              <input aria-label="Assessment Form field" style={{ ...inputStyle, flex: 1 }} value={p} onChange={e => updatePainPoint(i, e.target.value)} placeholder={`Pain Point ${i + 1}`} />
              {painPoints.length > 1 && (
                <button role="button" aria-label={`Remove pain point ${i + 1}`} onClick={() => removePainPoint(i)} style={{ background: 'var(--status-negative-soft)', border: 'none', borderRadius: 'var(--radius-sm)', padding: '4px 8px', cursor: 'pointer', color: 'var(--status-negative)', fontSize: '0.8rem' }}>X</button>
              )}
            </div>
          ))}
          <button role="button" aria-label="Add a pain point" onClick={addPainPoint} style={{ padding: '8px 16px', background: 'var(--neutral-100)', border: '1px dashed var(--neutral-400)', borderRadius: 'var(--radius)', cursor: 'pointer', color: 'var(--neutral-500)', fontSize: '0.85rem' }}>+ Add Pain Point</button>
        </div>
      );
      case 'impact': return (
        <div>
          <h3 style={{ margin: '0 0 16px 0', color: 'var(--neutral-700)' }}>Business Impact</h3>
          <div style={{ marginBottom: 16 }}>
            <label style={labelStyle}>Impact Category</label>
            <select aria-label="Assessment Form selection" style={inputStyle} value={impactCategory} onChange={e => setImpactCategory(e.target.value)}>
              <option value="">Select category...</option>
              {['Cost Reduction', 'Revenue Growth', 'Risk Mitigation', 'Efficiency', 'Innovation', 'Compliance'].map(c => (
                <option key={c} value={c}>{c}</option>
              ))}
            </select>
          </div>
          <div style={{ marginBottom: 16 }}>
            <label style={labelStyle}>Impact Description</label>
            <textarea aria-label="Assessment Form field" style={{ ...inputStyle, minHeight: 80 }} value={impactDescription} onChange={e => setImpactDescription(e.target.value)} placeholder="Describe the expected business impact..." />
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: 16 }}>
            <div style={{ gridColumn: '1 / -1' }}>
              <label style={labelStyle}>Business Impact Estimation</label>
              <p style={{ margin: '0 0 8px 0', color: 'var(--neutral-500)', fontSize: '0.85rem' }}>
                Deterministic keyword-based estimation of savings, revenue, and timeline based on your use case details, goals, and challenges.
              </p>
              <button role="button" aria-label="Estimate business impact"
                onClick={() => {
                  if (!title || !description) {
                    alert('Please enter a title and description first.');
                    return;
                  }
                  setSubmitting(true);
                  try {
                    // Deterministic keyword-based estimation (no inference/AI)
                    const allText = [title, description, ...goals.filter(g => g.trim()), ...challenges.filter(c => c.trim()), impactCategory || '', department].join(' ').toLowerCase();
                    const kwSavings = ['save', 'reduce', 'cut', 'lower', 'minimize', 'eliminate', 'automation', 'streamline', 'efficiency', 'optimize', 'cost reduction'];
                    const kwRevenue = ['sell', 'revenue', 'grow', 'increase', 'convert', 'pipeline', 'acquisition', 'upsell', 'cross-sell', 'new customer'];
                    const kwTimeline = ['urgent', 'quick', 'immediate', 'fast', 'rapid', '3 months', '6 weeks', 'asap'];
                    const kwSavingsCount = kwSavings.filter(kw => allText.includes(kw)).length;
                    const kwRevenueCount = kwRevenue.filter(kw => allText.includes(kw)).length;
                    const kwTimelineCount = kwTimeline.filter(kw => allText.includes(kw)).length;
                    const baseSavings = Math.round(10000 + kwSavingsCount * 25000);
                    const baseRevenue = Math.round(5000 + kwRevenueCount * 20000);
                    setEstimatedSavings(baseSavings);
                    setEstimatedRevenue(baseRevenue);
                    setTimeline(kwTimelineCount > 0 ? 'Immediate (0-3 months)' : 'Short-term (3-6 months)');
                  } catch {
                    setSubmitError('Estimation failed. Please enter values manually.');
                  } finally {
                    setSubmitting(false);
                  }
                }}
                style={{
                  padding: '12px 20px',
                  background: 'var(--brand-500)',
                  color: 'var(--neutral-0)',
                  border: 'none',
                  borderRadius: 'var(--radius)',
                  cursor: submitting ? 'wait' : 'pointer',
                  fontSize: '0.9rem',
                  fontWeight: 600,
                  opacity: submitting ? 0.7 : 1,
                }}
              >
                {submitting ? '⏳ Estimating...' : '📊 Estimate with Rules'}
              </button>
              <p style={{ margin: '8px 0 0 0', color: 'var(--neutral-500)', fontSize: '0.8rem' }}>
                {estimatedSavings || estimatedRevenue ? '✓ Values estimated — you can adjust if needed' : 'Click to generate estimates based on keyword analysis of your use case details'}
              </p>
            </div>
            <div>
              <label style={labelStyle}>Estimated Savings ($)</label>
              <input aria-label="Assessment Form field" style={inputStyle} type="number" value={estimatedSavings ?? ''} onChange={e => setEstimatedSavings(e.target.value ? Number(e.target.value) : undefined)} placeholder="AI estimated or enter manually" />
            </div>
            <div>
              <label style={labelStyle}>Estimated Revenue ($)</label>
              <input aria-label="Assessment Form field" style={inputStyle} type="number" value={estimatedRevenue ?? ''} onChange={e => setEstimatedRevenue(e.target.value ? Number(e.target.value) : undefined)} placeholder="AI estimated or enter manually" />
            </div>
          </div>
          <div style={{ marginTop: 16 }}>
            <label style={labelStyle}>Timeline Estimate</label>
            <select aria-label="Assessment Form selection" style={inputStyle} value={timeline} onChange={e => setTimeline(e.target.value)}>
              <option value="">Select timeline...</option>
              {['Immediate (0-3 months)', 'Short-term (3-6 months)', 'Medium-term (6-12 months)', 'Long-term (12+ months)'].map(t => (
                <option key={t} value={t}>{t}</option>
              ))}
            </select>
          </div>
        </div>
      );
      case 'review': return (
        <div>
          <h3 style={{ margin: '0 0 20px 0', color: 'var(--neutral-700)' }}>Review Your Assessment</h3>
          <p style={{ color: 'var(--neutral-500)', fontSize: '0.9rem', marginBottom: 20 }}>Review all information before submitting.</p>
          <div style={{ display: 'grid', gap: 16 }}>
            <div style={{ padding: 16, background: 'var(--neutral-0)', borderRadius: 'var(--radius)' }}>
              <h4 style={{ margin: '0 0 8px 0', color: 'var(--brand-700)', fontSize: '0.95rem' }}>Basic Information</h4>
              <pre style={{ margin: 0, fontSize: '0.9rem', color: 'var(--neutral-700)', lineHeight: 1.6, whiteSpace: 'pre-wrap' }}>
                {`Customer: ${selectedCustomerName || '—'}\nDepartment: ${departments.find(d => d.id === selectedDepartmentId)?.name || department || '—'}\n${description ? 'Description: ' + description : ''}`}
              </pre>
            </div>
            <div style={{ padding: 16, background: 'var(--neutral-0)', borderRadius: 'var(--radius)' }}>
              <h4 style={{ margin: '0 0 8px 0', color: 'var(--brand-700)', fontSize: '0.95rem' }}>Goals</h4>
              <pre style={{ margin: 0, fontSize: '0.9rem', color: 'var(--neutral-700)', lineHeight: 1.6, whiteSpace: 'pre-wrap' }}>
                {goals.filter(g => g.trim()).map((g, i) => `  ${i + 1}. ${g}`).join('\n') || '  None specified'}
              </pre>
            </div>
            <div style={{ padding: 16, background: 'var(--neutral-0)', borderRadius: 'var(--radius)' }}>
              <h4 style={{ margin: '0 0 8px 0', color: 'var(--brand-700)', fontSize: '0.95rem' }}>Challenges</h4>
              <pre style={{ margin: 0, fontSize: '0.9rem', color: 'var(--neutral-700)', lineHeight: 1.6, whiteSpace: 'pre-wrap' }}>
                {challenges.filter(c => c.trim()).map((c, i) => `  ${i + 1}. ${c}`).join('\n') || '  None specified'}
              </pre>
            </div>
            <div style={{ padding: 16, background: 'var(--neutral-0)', borderRadius: 'var(--radius)' }}>
              <h4 style={{ margin: '0 0 8px 0', color: 'var(--brand-700)', fontSize: '0.95rem' }}>Pain Points</h4>
              <pre style={{ margin: 0, fontSize: '0.9rem', color: 'var(--neutral-700)', lineHeight: 1.6, whiteSpace: 'pre-wrap' }}>
                {painPoints.filter(p => p.trim()).map((p, i) => `  ${i + 1}. ${p}`).join('\n') || '  None specified'}
              </pre>
            </div>
            <div style={{ padding: 16, background: 'var(--neutral-0)', borderRadius: 'var(--radius)' }}>
              <h4 style={{ margin: '0 0 8px 0', color: 'var(--brand-700)', fontSize: '0.95rem' }}>Business Impact</h4>
              <pre style={{ margin: 0, fontSize: '0.9rem', color: 'var(--neutral-700)', lineHeight: 1.6, whiteSpace: 'pre-wrap' }}>
                {`Category: ${impactCategory || '—'}\nSavings: ${estimatedSavings?.toLocaleString() || '0'}\nRevenue: ${estimatedRevenue?.toLocaleString() || '0'}\nTimeline: ${timeline || '—'}`}
              </pre>
            </div>
          </div>
        </div>
      );
      default: return null;
    }
  };

  return (
    <div style={{ maxWidth: 800, margin: '0 auto', padding: '24px', boxSizing: 'border-box' }}>
      <div style={{ marginBottom: 24 }}>
        <h1 style={{ margin: '0 0 8px 0', fontSize: 'clamp(1.2rem, 4vw, 1.5rem)', color: 'var(--ink)' }}>
          {editMode ? 'Edit Assessment' : 'New Assessment'}
        </h1>
        <p style={{ margin: 0, color: 'var(--neutral-500)', fontSize: '0.9rem' }}>AI Readiness Assessment — Step {currentIdx + 1} of {templateSteps.length}</p>
      </div>

      <div style={{ marginBottom: 28 }}>
        <div style={{ display: 'flex', gap: 4, marginBottom: 8 }}>
          {templateSteps.map((_, i) => (
            <div key={i} style={{ flex: 1, height: 4, borderRadius: 'var(--radius-sm)', background: i <= currentIdx ? 'var(--brand-500)' : 'var(--divider)' }} />
          ))}
        </div>
        <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 'clamp(0.65rem, 2.5vw, 0.75rem)', color: 'var(--neutral-500)' }}>
          <span>Step {currentIdx + 1}: {stepLabel}</span>
          <span>{Math.round((currentIdx + 1) / templateSteps.length * 100)}% Complete</span>
        </div>
      </div>

      <div style={{ background: 'var(--neutral-0)', borderRadius: 'var(--radius)', padding: 'clamp(16px, 4vw, 24px)', boxShadow: 'var(--shadow-card)' }}>
        {renderStep()}
      </div>

      {loading && <div role="status" aria-live="polite" style={{ padding: '16px', textAlign: 'center', color: 'var(--neutral-500)' }}>Loading form options…</div>}
      {submitting && <div role="status" aria-live="polite" style={{ padding: '12px', textAlign: 'center', color: 'var(--neutral-500)' }}>Saving assessment…</div>}
      {submitError && (
        <div role="alert" aria-live="assertive" style={{ padding: '12px 16px', background: 'var(--status-negative-soft)', borderLeft: '4px solid var(--status-negative)', margin: '16px 0', borderRadius: 'var(--radius-sm)', color: 'var(--status-negative)' }}>
          <span aria-hidden="true">⚠️ </span>{submitError}
        </div>
      )}
      {loadError && (
        <div role="alert" aria-live="assertive" style={{ padding: '12px 16px', background: 'var(--status-negative-soft)', borderLeft: '4px solid var(--status-negative)', margin: '16px 0', borderRadius: 'var(--radius-sm)', color: 'var(--status-negative)', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <span aria-hidden="true">⚠️ </span>
          <span>{loadError}</span>
          <ActionButton variant="primary"
            aria-label="Retry loading customers"
            onClick={() => { setLoadError(null); loadCustomers(); }}
          >
            Retry
          </ActionButton>
        </div>
      )}

      <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: 20, gap: 12, flexWrap: 'wrap' }}>
        {isFirstStep ? (
          <button role="button" aria-label="Cancel assessment" onClick={handleCancel}
            style={{ padding: '10px 20px', background: 'var(--neutral-100)', border: '1px solid var(--divider)', borderRadius: 'var(--radius)', cursor: 'pointer', fontSize: '0.9rem', color: 'var(--neutral-500)' }}>
            Cancel
          </button>
        ) : (
          <button role="button" aria-label="Go to previous step" onClick={() => setStep(templateSteps[Math.max(0, currentIdx - 1)] as Step)}
            style={{ padding: '10px 20px', background: 'var(--neutral-100)', border: '1px solid var(--divider)', borderRadius: 'var(--radius)', cursor: 'pointer', fontSize: '0.9rem', color: 'var(--neutral-500)' }}>
            ← Previous
          </button>
        )}
        <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap' }}>
          {isLastStep ? (
            <button role="button" aria-label="Submit assessment" onClick={submit} disabled={submitting || !title.trim()}
              style={{ padding: '10px 24px', background: !title.trim() ? 'var(--neutral-400)' : 'var(--brand-500)', color: 'var(--neutral-0)', border: 'none', borderRadius: 'var(--radius)', cursor: !title.trim() ? 'not-allowed' : 'pointer', fontSize: '0.9rem', fontWeight: 'bold', opacity: submitting ? 0.7 : 1, minWidth: '160px' }}>
              {submitting ? 'Submitting...' : editMode ? 'Save Changes' : 'Submit Assessment'}
            </button>
          ) : (
            <ActionButton variant="primary" role="button" aria-label="Go to next step" onClick={() => setStep(templateSteps[Math.min(currentIdx + 1, templateSteps.length - 1)] as Step)}>
              Next
            </ActionButton>
          )}
        </div>
      </div>

      {/* FE-12: discard guard — warn before abandoning a dirty draft. Stay
          keeps the current step/fields; Discard navigates once. A clean form
          (or a successful save) never shows this. */}
      {confirmDiscard && createPortal(
        <div role="dialog" aria-modal="true" aria-label="Discard unsaved changes?"
          style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.5)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 1100, padding: 16 }}>
          <div style={{ background: 'var(--neutral-0)', borderRadius: 'var(--radius)', boxShadow: 'var(--shadow-card)', maxWidth: 440, width: '100%', padding: 24 }}>
            <h2 style={{ margin: '0 0 8px', fontSize: '1.1rem', color: 'var(--ink)' }}>Discard unsaved changes?</h2>
            <p style={{ margin: '0 0 20px', color: 'var(--neutral-500)', fontSize: '0.9rem' }}>
              This assessment has changes that have not been saved. If you leave, they will be lost.
            </p>
            <div style={{ display: 'flex', gap: 12, justifyContent: 'flex-end' }}>
              <button role="button" aria-label="Stay and keep editing"
                onClick={() => setConfirmDiscard(false)}
                style={{ padding: '10px 18px', background: 'var(--neutral-100)', border: '1px solid var(--divider)', borderRadius: 'var(--radius)', cursor: 'pointer', fontSize: '0.9rem', color: 'var(--neutral-700)', fontWeight: 600 }}>
                Stay
              </button>
              <ActionButton variant="danger" role="button" aria-label="Discard and leave"
                onClick={() => { setConfirmDiscard(false); onCancel(); }}>
                Discard
              </ActionButton>
            </div>
          </div>
        </div>,
        document.body,
      )}
    </div>
  );
}

const labelStyle: React.CSSProperties = {
  display: 'block', marginBottom: 6, fontSize: '0.9rem', fontWeight: 600, color: 'var(--neutral-700)',
};
const inputStyle: React.CSSProperties = {
  width: '100%', padding: '10px 12px', border: '1px solid var(--divider)', borderRadius: 'var(--radius)', fontSize: '0.95rem', boxSizing: 'border-box',
};
export default AssessmentForm;
