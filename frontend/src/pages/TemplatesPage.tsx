import { useState, useEffect } from 'react';
import { useSearchParams } from 'react-router-dom';
import { loadTemplates, TemplateData } from '../lib/templates';
import type { Customer, BootstrapResult } from '../types/use_case';
import { api } from '../lib/api';

type TemplateStep = 'browse' | 'fill';

const DEFAULT_SEED_DEPARTMENTS = ['Customer Success', 'Operations', 'Finance', 'IT'];

interface TemplatesPageProps {
  customer?: Customer;
  // Starting a template assessment bootstraps departments + one draft
  // use case per goal. onCreated lets the caller refresh after a bootstrap.
  onCreated?: () => void | Promise<void>;
  onCancel?: () => void;
  onBack?: () => void;
  onStartBlank?: () => void;
}

export function TemplatesPage({ customer, onCreated, onCancel, onBack, onStartBlank }: TemplatesPageProps) {
  const [_searchParams, setSearchParams] = useSearchParams();
  const [selectedTemplate, setSelectedTemplate] = useState<TemplateData | null>(null);
  const [step, setStep] = useState<TemplateStep>('browse');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState('');
  const [templates, setTemplates] = useState<TemplateData[]>([]);
  const [loading, setLoading] = useState(true);
  // Global mode (no customer context): the caller must pick a customer.
  const [customers, setCustomers] = useState<Customer[]>([]);
  const [globalCustomerId, setGlobalCustomerId] = useState<number | null>(null);
  // Per-vertical seed departments (for the "What will be seeded" block).
  const [departmentsByVertical, setDepartmentsByVertical] = useState<Record<string, string[]>>({});
  // Post-create confirmation shown on the browse grid.
  const [successMessage, setSuccessMessage] = useState('');

  useEffect(() => {
    loadTemplates()
      .then((t) => setTemplates(t))
      .catch(() => setError('Failed to load templates'))
      .finally(() => setLoading(false));
    api.listVerticals()
      .then((v) => setDepartmentsByVertical(v.departments_by_vertical))
      .catch(() => setDepartmentsByVertical({}));
  }, []);

  // Global mode: load the caller's accessible customers.
  useEffect(() => {
    if (customer) return;
    (async () => {
      try {
        const data = await api.listCustomers();
        setCustomers(Array.isArray(data) ? data : []);
      } catch {
        setCustomers([]);
      }
    })();
  }, [customer]);

  const effectiveCustomer: Customer | undefined = customer
    ? customer
    : customers.find((c) => c.id === globalCustomerId);

  // Seed-plan preview states:
  // - 'known': the list shown is what the backend will seed (the mapping is
  //   loaded, or the customer is Other/vertical-less where the default set is
  //   authoritative — resolve_departments returns DEFAULT_DEPARTMENTS).
  // - 'pending': a vertical IS set but its mapping hasn't loaded (fetch
  //   in-flight or failed) — show a note, never a wrong department list.
  // - 'none': global mode before a customer is chosen.
  const effectiveVertical = effectiveCustomer?.vertical;
  const seedState: 'known' | 'pending' | 'none' = !effectiveCustomer
    ? 'none'
    : !effectiveVertical || effectiveVertical === 'Other' || departmentsByVertical[effectiveVertical]
      ? 'known'
      : 'pending';
  const seedDepartments: string[] | null = seedState === 'known'
    ? departmentsByVertical[effectiveVertical!] ?? DEFAULT_SEED_DEPARTMENTS
    : null;
  const seedIsDefault = seedState === 'known' && (!effectiveVertical || effectiveVertical === 'Other');

  const handleSelectTemplate = (template: TemplateData) => {
    setSelectedTemplate(template);
    setStep('fill');
    setError('');
    setSuccessMessage('');
  };

  const handleBack = () => {
    setSelectedTemplate(null);
    setStep('browse');
    setError('');
  };

  const describeResult = (result: BootstrapResult, customerName: string) => {
    const createdDepts = result.departments.filter((d) => d.created).length;
    const deptPhrase = createdDepts > 0
      ? `${createdDepts} new department${createdDepts === 1 ? '' : 's'}`
      : `${result.departments.length} departments (already present)`;
    const goalCount = result.use_cases.length;
    const preseededCount = result.preseeded?.length ?? 0;
    // result.count already includes the pre-seeds — report goal UCs and
    // pre-seeded examples separately so the numbers don't double-count.
    const preseededPhrase = preseededCount > 0
      ? ` + ${preseededCount} example use case${preseededCount === 1 ? '' : 's'} pre-seeded for empty departments`
      : '';
    return `Assessment seeded for ${customerName}: ${deptPhrase} and ${goalCount} draft use case${goalCount === 1 ? '' : 's'} (one per goal)${preseededPhrase}. They appear in the use cases list above.`;
  };

  const handleSubmit = async () => {
    if (!selectedTemplate) return;
    if (!effectiveCustomer) {
      setError('Please select a customer for this assessment');
      return;
    }
    try {
      setSubmitting(true);
      setError('');
      const result = await api.startTemplateAssessment(effectiveCustomer.name, selectedTemplate.id);
      if (customer) {
        setSuccessMessage(describeResult(result, customer.name));
        handleBack();
        if (onCreated) await onCreated();
      } else {
        setSearchParams({ view: 'assessment-list' });
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to start assessment');
    } finally {
      setSubmitting(false);
    }
  };

  const handleCancel = () => {
    if (customer) {
      handleBack();
      return;
    }
    if (onCancel) {
      onCancel();
      return;
    }
    setSearchParams({ view: 'assessment-list' });
  };

  if (loading) {
    return (
      <div style={{ padding: '40px', textAlign: 'center', color: 'var(--neutral-500)' }}>
        Loading templates...
      </div>
    );
  }

  if (step === 'browse') {
    return (
      <div style={{ padding: '24px', maxWidth: '1200px', margin: '0 auto' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: '24px' }}>
          <div>
            <h1 style={{ margin: '0 0 4px 0', fontSize: '1.8rem', color: 'var(--ink)' }}>
              📄 Assessment Templates
            </h1>
            <p style={{ margin: 0, color: 'var(--neutral-500)', fontSize: '0.95rem' }}>
              Select a pre-built template to seed departments and draft use cases for this customer
            </p>
          </div>
          {onBack && (
            <button role="button" aria-label="Back to assessments" onClick={onBack} style={{ padding: '8px 16px', background: 'var(--neutral-500)', color: 'var(--neutral-0)', border: 'none', borderRadius: 'var(--radius)', cursor: 'pointer', fontSize: '0.85rem' }}>
              ← Back to My Assessments
            </button>
          )}
        </div>

        {successMessage && (
          <div role="status" aria-live="polite" style={{
            padding: '12px 16px',
            background: 'var(--status-positive-soft)',
            borderLeft: '4px solid var(--status-positive)',
            borderRadius: 'var(--radius-sm)',
            marginBottom: '20px',
            color: 'var(--status-positive)',
            fontSize: '0.9rem',
          }}>
            <span aria-hidden="true">✅ </span>{successMessage}
          </div>
        )}

        {error && (
          <div role="alert" style={{ padding: '12px 16px', background: 'var(--status-negative-soft)', borderLeft: '4px solid var(--status-negative)', marginBottom: '20px', borderRadius: 'var(--radius-sm)', color: 'var(--status-negative)' }}>
            {error}
          </div>
        )}

        {templates.length === 0 ? (
          <div style={{ padding: '40px', textAlign: 'center', color: 'var(--neutral-500)' }}>
            No templates available. Create a blank assessment to get started.
          </div>
        ) : (
          <div style={{ display: 'grid', gap: '20px', gridTemplateColumns: 'repeat(auto-fill, minmax(320px, 1fr))' }}>
            {templates.map((template) => (
              <div
                key={template.id}
                role="button"
                tabIndex={0}
                aria-label={`Select template ${template.name}`}
                onClick={() => handleSelectTemplate(template)}
                onKeyDown={(event) => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); handleSelectTemplate(template); } }}
                style={{
                  padding: '24px',
                  background: 'var(--neutral-0)',
                  borderRadius: 'var(--radius)',
                  border: '1px solid var(--divider)',
                  cursor: 'pointer',
                  transition: 'all 0.2s',
                }}
                onMouseEnter={(e) => {
                  e.currentTarget.style.borderColor = 'var(--brand-500)';
                  e.currentTarget.style.boxShadow = '0 4px 12px rgba(90, 107, 194, 0.15)';
                }}
                onMouseLeave={(e) => {
                  e.currentTarget.style.borderColor = 'var(--divider)';
                  e.currentTarget.style.boxShadow = 'none';
                }}
              >
                <div style={{ display: 'flex', alignItems: 'flex-start', gap: '16px' }}>
                  <div style={{ fontSize: '2.5rem' }}>{template.icon}</div>
                  <div style={{ flex: 1 }}>
                    <div style={{ fontSize: '1.15rem', fontWeight: 600, color: 'var(--ink)', marginBottom: '6px' }}>
                      {template.name}
                    </div>
                    <div style={{ fontSize: '0.9rem', color: 'var(--neutral-500)', marginBottom: '12px', lineHeight: '1.5' }}>
                      {template.description}
                    </div>
                    <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap' }}>
                      {template.department && (
                        <span style={{
                          fontSize: '0.8rem',
                          padding: '4px 10px',
                          background: 'var(--brand-50)',
                          color: 'var(--brand-700)',
                          borderRadius: 'var(--radius)',
                          fontWeight: 500,
                        }}>
                          {template.department}
                        </span>
                      )}
                      {template.goals && template.goals.length > 0 && (
                        <span style={{
                          fontSize: '0.8rem',
                          padding: '4px 10px',
                          background: 'var(--brand-50)',
                          color: 'var(--brand-700)',
                          borderRadius: 'var(--radius)',
                          fontWeight: 500,
                        }}>
                          {template.goals.length} goals
                        </span>
                      )}
                    </div>
                    {(template.goals?.length || 0) > 0 && (
                      <div style={{ marginTop: '12px', paddingTop: '12px', borderTop: '1px solid var(--divider)' }}>
                        <div style={{ fontSize: '0.85rem', fontWeight: 600, color: 'var(--neutral-700)', marginBottom: '6px' }}>Key Goals:</div>
                        <ul style={{ margin: 0, paddingLeft: '20px', fontSize: '0.85rem', color: 'var(--neutral-500)' }}>
                          {template.goals.slice(0, 3).map((goal, i) => (
                            <li key={i} style={{ marginBottom: '2px' }}>{goal}</li>
                          ))}
                          {(template.goals.length > 3) && (
                            <li style={{ color: 'var(--neutral-500)' }}>...and {template.goals.length - 3} more</li>
                          )}
                        </ul>
                      </div>
                    )}
                  </div>
                  <div style={{ color: 'var(--brand-700)', fontSize: '1.5rem', fontWeight: 'bold' }}>→</div>
                </div>
              </div>
            ))}
          </div>
        )}

        <div style={{ marginTop: '32px', textAlign: 'center' }}>
          {onStartBlank ? (
            <button
              role="button"
              aria-label="Start blank assessment"
              onClick={onStartBlank}
              style={{
                padding: '10px 18px',
                background: 'var(--status-positive-soft)',
                color: 'var(--status-positive)',
                border: '1px solid var(--status-positive-soft)',
                borderRadius: 'var(--radius)',
                cursor: 'pointer',
                fontSize: '0.9rem',
                fontWeight: 500,
              }}
            >
              Can't find what you need? Start a blank assessment →
            </button>
          ) : (
            <p style={{ color: 'var(--neutral-500)', fontSize: '0.9rem', marginBottom: '16px' }}>
              Don't see what you need? Create a blank assessment with your own requirements.
            </p>
          )}
        </div>
      </div>
    );
  }

  // Fill step
  const goalCount = selectedTemplate?.goals?.length || 1;
  return (
    <div style={{ padding: '24px', maxWidth: '800px', margin: '0 auto' }}>
      <div style={{ marginBottom: '24px' }}>
        <button role="button" aria-label="Go back"
          onClick={handleBack}
          style={{
            padding: '8px 16px',
            background: 'var(--neutral-100)',
            border: '1px solid var(--divider)',
            borderRadius: 'var(--radius)',
            cursor: 'pointer',
            fontSize: '0.9rem',
            color: 'var(--neutral-500)',
            marginBottom: '16px',
          }}
        >
          ← Back to Templates
        </button>
        <h1 style={{ margin: '0 0 4px 0', fontSize: '1.5rem', color: 'var(--ink)' }}>
          Start This Assessment
        </h1>
        <p style={{ margin: 0, color: 'var(--neutral-500)', fontSize: '0.95rem' }}>
          Using template: <strong>{selectedTemplate?.name}</strong>
        </p>
      </div>

      {error && (
        <div style={{
          padding: '12px 16px',
          background: 'var(--status-negative-soft)',
          borderLeft: '4px solid var(--status-negative)',
          marginBottom: '20px',
          borderRadius: 'var(--radius-sm)',
        }}>
          <span style={{ color: 'var(--status-negative)', fontWeight: 500 }}>{error}</span>
        </div>
      )}

      <div style={{ background: 'var(--neutral-0)', borderRadius: 'var(--radius)', padding: '24px', border: '1px solid var(--divider)' }}>
        {!customer && (
          <div style={{ marginBottom: '20px' }}>
            <label style={{
              display: 'block',
              marginBottom: '8px',
              fontSize: '0.95rem',
              fontWeight: 600,
              color: 'var(--neutral-700)',
            }}>
              Customer *
            </label>
            <select
              aria-label="Templates Page field"
              value={globalCustomerId ?? ''}
              onChange={(e) => setGlobalCustomerId(e.target.value ? Number(e.target.value) : null)}
              style={{
                width: '100%',
                padding: '12px',
                border: '1px solid var(--divider)',
                borderRadius: 'var(--radius)',
                fontSize: '1rem',
                boxSizing: 'border-box',
                background: 'var(--neutral-0)',
                color: 'var(--ink)',
              }}
            >
              <option value="" disabled>Select a customer…</option>
              {customers.map((c) => (
                <option key={c.id} value={c.id}>{c.name}</option>
              ))}
            </select>
            {customers.length === 0 && (
              <p style={{ margin: '8px 0 0', color: 'var(--status-negative)', fontSize: '0.85rem' }}>
                No customers available — create one first.
              </p>
            )}
          </div>
        )}

        <div style={{ marginBottom: '20px', padding: '16px', background: 'var(--brand-50)', borderRadius: 'var(--radius)', border: '1px solid var(--brand-100)' }}>
          <div style={{ fontSize: '0.9rem', fontWeight: 600, color: 'var(--ink)', marginBottom: '8px' }}>What will be seeded</div>
          <div style={{ fontSize: '0.88rem', color: 'var(--neutral-700)', lineHeight: '1.6' }}>
            {seedState === 'pending' ? (
              <div style={{ color: 'var(--neutral-500)', fontSize: '0.82rem' }}>
                Department mapping for {effectiveVertical} is not loaded — the backend resolves the 4 departments when the assessment starts.
              </div>
            ) : seedState === 'none' ? (
              <div style={{ color: 'var(--neutral-500)', fontSize: '0.82rem' }}>
                Select a customer to see the departments that will be seeded.
              </div>
            ) : (
              <>
                <div><strong>Departments:</strong> {seedDepartments!.join(', ')}</div>
                {seedIsDefault && (
                  <div style={{ color: 'var(--neutral-500)', fontSize: '0.82rem' }}>
                    (default set — {effectiveCustomer?.vertical === 'Other' ? 'vertical is “Other”' : 'no vertical set'})
                  </div>
                )}
                <div style={{ marginTop: '4px' }}>
                  <strong>{goalCount}</strong> draft use case{goalCount === 1 ? '' : 's'} (one per goal)
                </div>
                <div style={{ marginTop: '4px', color: 'var(--neutral-500)', fontSize: '0.82rem' }}>
                  Any department without a matching template goal is pre-seeded with a vertical-determined example use case.
                </div>
              </>
            )}
          </div>
        </div>

        <div style={{ marginBottom: '24px' }}>
          <label style={{
            display: 'block',
            marginBottom: '8px',
            fontSize: '0.95rem',
            fontWeight: 600,
            color: 'var(--neutral-700)',
          }}>
            Template Preview
          </label>
          <div style={{
            padding: '16px',
            background: 'var(--neutral-0)',
            borderRadius: 'var(--radius)',
            fontSize: '0.9rem',
            color: 'var(--neutral-500)',
            lineHeight: '1.6',
            border: '1px solid var(--divider)',
          }}>
            {selectedTemplate?.description && (
              <div style={{ marginBottom: '12px' }}>
                <strong>Description:</strong> {selectedTemplate.description}
              </div>
            )}
            <div style={{ marginBottom: '12px' }}>
              <strong>Department:</strong> {selectedTemplate?.department}
            </div>
            {selectedTemplate?.goals && selectedTemplate.goals.length > 0 && (
              <div style={{ marginBottom: '12px' }}>
                <strong>Goals:</strong>
                <ul style={{ margin: '4px 0', paddingLeft: '20px' }}>
                  {selectedTemplate.goals.map((g, i) => <li key={i}>{g}</li>)}
                </ul>
              </div>
            )}
            {selectedTemplate?.challenges && selectedTemplate.challenges.length > 0 && (
              <div style={{ marginBottom: '12px' }}>
                <strong>Challenges:</strong>
                <ul style={{ margin: '4px 0', paddingLeft: '20px' }}>
                  {selectedTemplate.challenges.map((c, i) => <li key={i}>{c}</li>)}
                </ul>
              </div>
            )}
            {selectedTemplate?.painPoints && selectedTemplate.painPoints.length > 0 && (
              <div>
                <strong>Pain Points:</strong>
                <ul style={{ margin: '4px 0', paddingLeft: '20px' }}>
                  {selectedTemplate.painPoints.map((p, i) => <li key={i}>{p}</li>)}
                </ul>
              </div>
            )}
            {(selectedTemplate?.impactCategory || selectedTemplate?.impactDescription || selectedTemplate?.timeline) && (
              <div style={{ marginTop: '12px', paddingTop: '12px', borderTop: '1px solid var(--divider)' }}>
                <div style={{ fontSize: '0.85rem', fontWeight: 600, color: 'var(--neutral-700)', marginBottom: '6px' }}>Business Impact</div>
                <div style={{ display: 'grid', gap: '6px' }}>
                  {selectedTemplate?.impactCategory && (
                    <div><strong>Category:</strong> {selectedTemplate.impactCategory}</div>
                  )}
                  {selectedTemplate?.timeline && (
                    <div><strong>Timeline:</strong> {selectedTemplate.timeline}</div>
                  )}
                  {selectedTemplate?.impactDescription && (
                    <div>{selectedTemplate.impactDescription}</div>
                  )}
                </div>
              </div>
            )}
          </div>
        </div>

        <div style={{ display: 'flex', gap: '12px', justifyContent: 'flex-end' }}>
          <button role="button" aria-label="Cancel"
            onClick={handleCancel}
            disabled={submitting}
            style={{
              padding: '12px 24px',
              background: 'var(--neutral-100)',
              border: '1px solid var(--divider)',
              borderRadius: 'var(--radius)',
              cursor: 'pointer',
              fontSize: '0.95rem',
              color: 'var(--neutral-500)',
            }}
          >
            Cancel
          </button>
          <button role="button" aria-label="Submit template"
            onClick={handleSubmit}
            disabled={submitting || !effectiveCustomer}
            style={{
              padding: '12px 24px',
              background: !effectiveCustomer ? 'var(--neutral-400)' : 'var(--brand-500)',
              color: 'var(--neutral-0)',
              border: 'none',
              borderRadius: 'var(--radius)',
              cursor: !effectiveCustomer ? 'not-allowed' : 'pointer',
              fontSize: '0.95rem',
              fontWeight: 600,
              opacity: submitting ? 0.7 : 1,
            }}
          >
            {submitting ? 'Creating...' : 'Start Assessment'}
          </button>
        </div>
      </div>
    </div>
  );
}
export default TemplatesPage;
