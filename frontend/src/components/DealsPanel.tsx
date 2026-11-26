import { SectionIcon } from './SectionIcon';
import { ActionButton } from './ActionButton';
import { BASIS_LABELS, TYPE_LABELS, formatDealAmount, probabilityText, toMinor } from '../lib/deals';
export { formatDealAmount, probabilityText, toMinor } from '../lib/deals';
import { PipelineStageSettings } from './PipelineStageSettings';
import { useAccountListState } from '../lib/useAccountListState';
import { SavedViewsMenu } from './SavedViewsMenu';
/**
 * E6 — Deals (Sales rail). Rep-owned deals, distinct from imported vendor
 * pipeline and from derived Attention cards (decision D6).
 *
 * Honesty rules: amounts render with their currency and basis and are never
 * summed (mixed currencies/bases are not comparable); probability is only
 * what a rep saved — a stage default is shown as a suggestion (D5). Backend
 * 409/422 messages render verbatim; a 409 reloads current state. Write gate
 * mirrors TasksPanel (hidden for auditor/none); the backend 403 is
 * authoritative.
 */
import { useEffect, useRef, useState } from 'react';
import { api, getAuthIsAdmin, getAuthSalesRole } from '../lib/api';
import type { AmountBasis, Deal, DealHistoryEntry, DealInput, DealType, PipelineStage } from '../types/deals';

interface Props {
  customerId: number;
  refreshRequest?: number;
  editRecordId?: number;
  editRequest?: number;
  onChanged?: () => void;
  onOpenDeal?: (id: number) => void;
  createRequest?: number;
  allowCreate?: boolean;
  userRole?: string; // 'owner' | 'member' | 'auditor' | 'none'
}

const inputStyle: React.CSSProperties = {
  padding: '8px', border: '1px solid var(--divider)', borderRadius: 'var(--radius)', fontSize: '0.85rem', background: 'var(--neutral-0)',
};
const muted: React.CSSProperties = { fontSize: '0.8rem', color: 'var(--neutral-500)' };

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label style={{ display: 'flex', flexDirection: 'column', gap: '4px', fontSize: '0.8rem', color: 'var(--neutral-600)', minWidth: 0 }}>
      {label}
      {children}
    </label>
  );
}

type Form = {
  name: string; stage_id: string; amount: string; currency: string; amount_basis: string; probability: string;
  close_date: string; deal_type: string; next_step: string; next_step_date: string; closed_reason: string;
};

const emptyForm = (stageId = ''): Form => ({
  name: '', stage_id: stageId, amount: '', currency: 'USD', amount_basis: '', probability: '',
  close_date: '', deal_type: '', next_step: '', next_step_date: '', closed_reason: '',
});

const formFrom = (d: Deal): Form => ({
  name: d.name, stage_id: String(d.stage_id), amount: d.amount_minor != null ? (d.amount_minor / 100).toFixed(2) : '',
  currency: d.currency, amount_basis: d.amount_basis ?? '', probability: d.probability != null ? String(d.probability) : '',
  close_date: d.close_date ?? '', deal_type: d.deal_type ?? '', next_step: d.next_step ?? '',
  next_step_date: d.next_step_date ?? '', closed_reason: d.closed_reason ?? '',
});

export function DealsPanel({ customerId, userRole, createRequest = 0, allowCreate, refreshRequest = 0, editRecordId, editRequest = 0, onChanged, onOpenDeal }: Props) {
  const [deals, setDeals] = useState<Deal[]>([]);
  const [stages, setStages] = useState<PipelineStage[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [editing, setEditing] = useState<Deal | 'new' | null>(null);
  const [form, setForm] = useState<Form>(emptyForm());
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [confirmDeleteId, setConfirmDeleteId] = useState<number | null>(null);
  const [historyFor, setHistoryFor] = useState<number | null>(null);
  const consumedEdit = useRef(0);
  const consumedCreate = useRef(0);
  const historySequence = useRef(0);
  const [historyState, setHistoryState] = useState<'loading' | 'error' | 'done'>('done');
  const [history, setHistory] = useState<DealHistoryEntry[]>([]);

  const [filters, updateFilters] = useAccountListState(customerId, 'deal', { stage: '', owner: '', close_from: '', close_to: '', sort: 'close', layout: 'list' });
  const { stage: stageFilter, owner: ownerFilter, close_from: closeFrom, close_to: closeTo, sort, layout } = filters;
  const setStageFilter = (stage: string) => updateFilters({ stage });
  const setOwnerFilter = (owner: string) => updateFilters({ owner });
  const setCloseFrom = (close_from: string) => updateFilters({ close_from });
  const setCloseTo = (close_to: string) => updateFilters({ close_to });
  const setSort = (sort: string) => updateFilters({ sort });
  const setLayout = (layout: string) => updateFilters({ layout });
  const visibleDeals = deals.filter(deal => (!stageFilter || String(deal.stage_id) === stageFilter) &&
    (!ownerFilter || (ownerFilter === 'unassigned' ? deal.owner_user_id == null : String(deal.owner_user_id) === ownerFilter)) &&
    (!closeFrom || !!deal.close_date && deal.close_date >= closeFrom) && (!closeTo || !!deal.close_date && deal.close_date <= closeTo))
    .sort((a, b) => sort === 'name' ? a.name.localeCompare(b.name) : sort === 'updated' ? (b.updated_at ?? '').localeCompare(a.updated_at ?? '') : (a.close_date ?? '9999').localeCompare(b.close_date ?? '9999') || a.id - b.id);
  const columns = stages.slice().sort((a, b) => a.position - b.position);
  deals.forEach(deal => { if (!columns.some(stage => stage.id === deal.stage_id)) columns.push(deal.stage); });
  const owners = new Map(deals.filter(deal => deal.owner_user_id != null).map(deal => [String(deal.owner_user_id), deal.owner_name || 'Unnamed owner']));
  const resetFilters = () => updateFilters({ stage: '', owner: '', close_from: '', close_to: '' });
  const canEdit = (allowCreate ?? true) && userRole !== 'auditor' && userRole !== 'none';

  const load = async () => {
    setLoading(true);
    try {
      const [list, stageList] = await Promise.all([api.listDeals(customerId), api.listPipelineStages()]);
      setDeals(Array.isArray(list) ? list : []);
      setStages(Array.isArray(stageList) ? stageList : []);
      setError(null);
    } catch (e: any) {
      setError(e?.message || 'Failed to load deals');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    setDeals([]);
    setEditing(null);
    setHistoryFor(null);
    setError(null);
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps -- reload only when the account changes
  }, [customerId, refreshRequest]);

  const set = (k: keyof Form, v: string) => setForm((f) => ({ ...f, [k]: v }));
  const selectedStage = stages.find((s) => String(s.id) === form.stage_id);

  const openNew = () => {
    setEditing('new');
    setForm(emptyForm(stages.find((s) => s.stage_class === 'open') ? String(stages.find((s) => s.stage_class === 'open')!.id) : ''));
    setSaveError(null);
  };

  const submit = async () => {
    if (!form.name.trim()) return setSaveError('Name is required.');
    const minor = toMinor(form.amount);
    if (Number.isNaN(minor)) return setSaveError('Amount must be a number with up to two decimal places.');
    if (minor != null && !form.amount_basis) return setSaveError('Choose a basis (one-time, ACV, TCV or MRR) for the amount.');
    const probability = form.probability.trim() === '' ? null : Number(form.probability);
    if (probability != null && (!Number.isInteger(probability) || probability < 0 || probability > 100)) {
      return setSaveError('Probability must be a whole number from 0 to 100.');
    }
    const data: DealInput = {
      name: form.name.trim(), stage_id: Number(form.stage_id), amount_minor: minor, currency: form.currency.trim().toUpperCase(),
      amount_basis: (form.amount_basis || null) as AmountBasis | null, probability, close_date: form.close_date || null,
      deal_type: (form.deal_type || null) as DealType | null, next_step: form.next_step.trim() || null,
      next_step_date: form.next_step_date || null, closed_reason: form.closed_reason.trim() || null,
    };
    setSaving(true);
    setSaveError(null);
    try {
      if (editing === 'new') await api.createDeal(customerId, data);
      else if (editing) await api.updateDeal(editing.id, { ...data, expected_version: editing.version });
      setEditing(null);
      await load();
      onChanged?.();
    } catch (e: any) {
      setSaveError(e?.message || 'Failed to save');
      if (e?.status === 409) await load();
    } finally {
      setSaving(false);
    }
  };

  const remove = async (d: Deal) => {
    setError(null);
    try {
      await api.deleteDeal(d.id, d.version);
      setConfirmDeleteId(null);
      await load();
    } catch (e: any) {
      setError(e?.message || 'Failed to delete');
      await load();
    }
  };

  const toggleHistory = async (d: Deal, retry = false) => {
    const request = ++historySequence.current;
    if (!retry && historyFor === d.id) return setHistoryFor(null);
    setHistoryState('loading');
    setHistoryFor(d.id);
    setHistory([]);
    try {
      const rows = await api.dealHistory(d.id);
      if (request === historySequence.current) { setHistory(rows); setHistoryState('done'); }
    } catch {
      if (request === historySequence.current) setHistoryState('error');
    }
  };

  const form_ = (
    <div data-testid="deal-form" style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(min(100%, 180px), 1fr))', gap: '10px', padding: '12px', border: '1px solid var(--divider)', borderRadius: 'var(--radius)', background: 'var(--neutral-0)', marginBottom: '12px' }}>
      <Field label="Name *"><input autoFocus aria-label="Deal name" style={inputStyle} value={form.name} onChange={(e) => set('name', e.target.value)} /></Field>
      <Field label="Stage">
        <select aria-label="Deal stage" style={inputStyle} value={form.stage_id} onChange={(e) => set('stage_id', e.target.value)}>
          {stages.map((s) => <option key={s.id} value={s.id}>{s.label}</option>)}
        </select>
      </Field>
      <Field label="Amount"><input aria-label="Deal amount" inputMode="decimal" style={inputStyle} value={form.amount} onChange={(e) => set('amount', e.target.value)} /></Field>
      <Field label="Currency"><input aria-label="Deal currency" maxLength={3} style={inputStyle} value={form.currency} onChange={(e) => set('currency', e.target.value)} /></Field>
      <Field label="Basis">
        <select aria-label="Deal amount basis" style={inputStyle} value={form.amount_basis} onChange={(e) => set('amount_basis', e.target.value)}>
          <option value="">Not set</option>
          {(Object.keys(BASIS_LABELS) as AmountBasis[]).map((b) => <option key={b} value={b}>{BASIS_LABELS[b]}</option>)}
        </select>
      </Field>
      <Field label="Probability %">
        <input aria-label="Deal probability" inputMode="numeric" style={inputStyle} value={form.probability}
          placeholder={selectedStage?.default_probability != null ? `Stage suggests ${selectedStage.default_probability}` : ''}
          onChange={(e) => set('probability', e.target.value)} />
      </Field>
      <Field label="Close date"><input aria-label="Deal close date" type="date" style={inputStyle} value={form.close_date} onChange={(e) => set('close_date', e.target.value)} /></Field>
      <Field label="Type">
        <select aria-label="Deal type" style={inputStyle} value={form.deal_type} onChange={(e) => set('deal_type', e.target.value)}>
          <option value="">Not set</option>
          {(Object.keys(TYPE_LABELS) as DealType[]).map((t) => <option key={t} value={t}>{TYPE_LABELS[t]}</option>)}
        </select>
      </Field>
      <Field label="Next step"><input aria-label="Deal next step" style={inputStyle} value={form.next_step} onChange={(e) => set('next_step', e.target.value)} /></Field>
      <Field label="Next step date"><input aria-label="Deal next step date" type="date" style={inputStyle} value={form.next_step_date} onChange={(e) => set('next_step_date', e.target.value)} /></Field>
      {selectedStage && selectedStage.stage_class !== 'open' && (
        <Field label={selectedStage.stage_class === 'lost' ? 'Closed reason *' : 'Closed reason'}>
          <input aria-label="Deal closed reason" style={inputStyle} value={form.closed_reason} onChange={(e) => set('closed_reason', e.target.value)} />
        </Field>
      )}
      <div style={{ gridColumn: '1 / -1', display: 'flex', gap: '8px', flexWrap: 'wrap', alignItems: 'center' }}>
        <ActionButton variant="primary" density="compact" busy={saving} onClick={submit}>{editing === 'new' ? 'Create deal' : 'Save deal'}</ActionButton>
        <ActionButton variant="quiet" density="compact" onClick={() => setEditing(null)}>Cancel</ActionButton>
        {saveError && <span role="alert" style={{ color: 'var(--status-negative)', fontSize: '0.8rem' }}>{saveError}</span>}
      </div>
    </div>
  );

  useEffect(() => {
    if (createRequest && canEdit && stages.length && consumedCreate.current !== createRequest) {
      consumedCreate.current = createRequest;
      setEditing('new'); setForm(emptyForm(String(stages.find(stage => stage.stage_class === 'open')?.id ?? stages[0].id))); setSaveError(null);
    }
  }, [createRequest, canEdit, stages]);

  useEffect(() => {
    if (!canEdit || !editRecordId || !editRequest || consumedEdit.current === editRequest) return;
    consumedEdit.current = editRequest;
    let active = true;
    api.getDeal(editRecordId).then(row => {
      if (!active) return;
      if (row.customer_id !== customerId) throw new Error('Deal unavailable');
      setEditing(row); setForm(formFrom(row)); setSaveError(null);
    }).catch(error => { if (active) setError(error instanceof Error ? error.message : 'Deal unavailable'); });
    return () => { active = false; };
  }, [canEdit, editRequest, editRecordId, customerId]);

  const renderDeal = (d: Deal) => (

            <li key={d.id} data-testid={`deal-${d.id}`} style={{ padding: '10px 12px', border: '1px solid var(--divider)', borderRadius: 'var(--radius)', background: 'var(--neutral-0)', minWidth: 0, overflowWrap: 'anywhere' }}>
              <div style={{ display: 'flex', gap: '10px', flexWrap: 'wrap', alignItems: 'baseline' }}>
                <strong style={{ color: 'var(--ink)' }}>{d.name}</strong>
                <span data-testid={`deal-stage-${d.id}`} style={{ fontSize: '0.75rem', padding: '2px 8px', borderRadius: '10px', background: d.stage.stage_class === 'won' ? 'var(--status-positive-soft)' : d.stage.stage_class === 'lost' ? 'var(--status-negative-soft)' : 'var(--neutral-100)' }}>{d.stage.label}</span>
                <span data-testid={`deal-amount-${d.id}`} style={{ color: 'var(--neutral-700)' }}>{formatDealAmount(d)}</span>
              </div>
              <div style={{ ...muted, display: 'flex', gap: '12px', flexWrap: 'wrap', marginTop: '4px' }}>
                <span>Close: {d.close_date ?? 'not set'}</span>
                <span data-testid={`deal-probability-${d.id}`}>Probability: {probabilityText(d)}</span>
                <span>Owner: {d.owner_name ?? 'unassigned'}</span>
                {d.deal_type && <span>{TYPE_LABELS[d.deal_type]}</span>}
                {d.next_step && <span>Next: {d.next_step}{d.next_step_date ? ` (${d.next_step_date})` : ''}</span>}
                {d.closed_reason && <span>Reason: {d.closed_reason}</span>}
              </div>
              <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap', marginTop: '8px' }}>
                {onOpenDeal && <ActionButton variant="quiet" density="compact" onClick={() => onOpenDeal(d.id)}>Details & evidence</ActionButton>}
                {canEdit && <ActionButton variant="secondary" density="compact" onClick={() => { setEditing(d); setForm(formFrom(d)); setSaveError(null); }}>Edit</ActionButton>}
                <ActionButton variant="quiet" density="compact" aria-expanded={historyFor === d.id} onClick={() => toggleHistory(d)}>History</ActionButton>
                {canEdit && (confirmDeleteId === d.id ? (
                  <>
                    <ActionButton variant="danger" density="compact" onClick={() => remove(d)}>Confirm delete</ActionButton>
                    <ActionButton variant="quiet" density="compact" onClick={() => setConfirmDeleteId(null)}>Keep</ActionButton>
                  </>
                ) : <ActionButton variant="secondary" data-tone="danger" density="compact" onClick={() => setConfirmDeleteId(d.id)}>Delete</ActionButton>)}
              </div>
              {canEdit && <label style={{ display: 'block', marginTop: 8 }}>Move to stage
                <select aria-label={`Move ${d.name} to stage`} value={d.stage_id} onChange={event => {
                  setEditing(d); setForm({ ...formFrom(d), stage_id: event.target.value }); setSaveError(null);
                }}><option value={d.stage_id}>{d.stage.label}</option>{stages.filter(stage => stage.id !== d.stage_id && stage.active).map(stage => <option key={stage.id} value={stage.id}>{stage.label}</option>)}</select>
                <span style={muted}> Review and save the change above.</span>
              </label>}
              {historyFor === d.id && (
                <div>
                  {historyState === 'loading' && <p role="status">Loading stage history…</p>}
                  {historyState === 'error' && <p role="alert">Stage history unavailable. <ActionButton variant="quiet" density="compact" onClick={() => { void toggleHistory(d, true); }}>Retry history</ActionButton></p>}
                  {historyState === 'done' && history.length === 0 && <p>No stage changes recorded.</p>}
                  <ol data-testid={`deal-history-${d.id}`} style={{ ...muted, margin: '8px 0 0', paddingLeft: '18px' }}>
                  {history.map((h, i) => (
                    <li key={i}>{h.at.slice(0, 10)} · {h.from_stage ? `${h.from_stage} → ` : ''}{h.to_stage} · {h.actor}{h.note ? ` · ${h.note}` : ''}</li>
                  ))}
                </ol></div>
              )}
            </li>
  );

  return (
    <section data-testid="deals-panel" aria-labelledby="deals-heading" style={{ minWidth: 0 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: '8px', flexWrap: 'wrap', marginBottom: '8px' }}>
        <h3 id="deals-heading" style={{ margin: 0, fontSize: '1.05rem', color: 'var(--neutral-700)' }}>
          Deals{!loading && ` (${deals.filter((d) => d.stage.stage_class === 'open').length} open)`}
        </h3>
        {canEdit && editing === null && stages.length > 0 && <ActionButton variant="primary" density="compact" icon={<SectionIcon name="➕" size={16} />} onClick={openNew}>New deal</ActionButton>}
      </div>
      <p style={{ ...muted, margin: '0 0 12px' }}>Rep-maintained deals. Imported vendor pipeline and Attention cards stay separate and are never added in.</p>
      {error && <div role="alert" style={{ color: 'var(--status-negative)', fontSize: '0.85rem', marginBottom: '8px' }}>{error} <ActionButton variant="quiet" density="compact" onClick={() => void load()}>Retry deals</ActionButton></div>}
      {(getAuthIsAdmin() || getAuthSalesRole() === 'sales_admin') && <details className="crm-disclosure"><summary>Pipeline stage settings</summary><PipelineStageSettings onChanged={() => void load()} /></details>}
      <SavedViewsMenu surface="account_deals" customerId={customerId} currentParams={{ customer_id: String(customerId), ...filters }} onApply={params => {
        if (params.customer_id === String(customerId)) updateFilters(Object.fromEntries(Object.entries(params).filter(([key]) => key !== 'customer_id').map(([key, value]) => [key, value ?? ''])));
      }} />
      <div className="crm-list-controls" aria-label="Deal filters">
        <Field label="Stage"><select aria-label="Filter deals by stage" value={stageFilter} onChange={event => setStageFilter(event.target.value)}><option value="">All stages</option>{stageFilter && !columns.some(stage => String(stage.id) === stageFilter) && <option value={stageFilter}>Stage unavailable</option>}{columns.map(stage => <option key={stage.id} value={stage.id}>{stage.label}</option>)}</select></Field>
        <Field label="Owner"><select aria-label="Filter deals by owner" value={ownerFilter} onChange={event => setOwnerFilter(event.target.value)}><option value="">All owners</option><option value="unassigned">Unassigned</option>{ownerFilter && ownerFilter !== 'unassigned' && !owners.has(ownerFilter) && <option value={ownerFilter}>Owner unavailable</option>}{[...owners].map(([id, label]) => <option key={id} value={id}>{label}</option>)}</select></Field>
        <Field label="Close from"><input aria-label="Close date from" type="date" value={closeFrom} onChange={event => setCloseFrom(event.target.value)} /></Field>
        <Field label="Close through"><input aria-label="Close date through" type="date" value={closeTo} min={closeFrom} onChange={event => setCloseTo(event.target.value)} /></Field>
        <Field label="Sort"><select aria-label="Sort deals" value={sort} onChange={event => setSort(event.target.value)}><option value="close">Close date</option><option value="name">Name</option><option value="updated">Recently updated</option></select></Field>
        <Field label="View"><select aria-label="Deal layout" value={layout} onChange={event => setLayout(event.target.value)}><option value="list">List</option><option value="board">Pipeline board</option></select></Field>
        <ActionButton variant="quiet" density="compact" onClick={resetFilters}>Clear deal filters</ActionButton>
      </div>
      {editing !== null && form_}
      {loading ? <div role="status" style={muted}>Loading deals…</div> : error && deals.length === 0 ? <p>Deal records unavailable.</p> : deals.length === 0 && layout !== 'board' ? (
        <div data-testid="deals-empty" style={muted}>No deals recorded for this account yet.</div>
      ) : (
        <>
          {visibleDeals.length === 0 && <p>No deals match these filters. <ActionButton variant="quiet" density="compact" onClick={resetFilters}>Clear deal filters</ActionButton></p>}
          {layout === 'board' ? <div className="crm-board" role="region" aria-label="Deal pipeline board" tabIndex={0}>
            {columns.map(stage => <section key={stage.id} className="crm-board-column" aria-label={`${stage.label} deals`}>
              <h4>{stage.label} ({visibleDeals.filter(deal => deal.stage_id === stage.id).length})</h4>
              <ul style={{ listStyle: 'none', padding: 0 }}>{visibleDeals.filter(deal => deal.stage_id === stage.id).map(renderDeal)}</ul>
            </section>)}
          </div> : (        <ul style={{ listStyle: 'none', margin: 0, padding: 0, display: 'flex', flexDirection: 'column', gap: '8px' }}>
          {visibleDeals.map(renderDeal)}
        </ul>)}
        </>
      )}
    </section>
  );
}
