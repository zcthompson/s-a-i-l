import { useCallback, useEffect, useState } from 'react';
import { api } from '../lib/api';
import type { PipelineStage } from '../types/deals';
const blank = () => ({ key: '', label: '', stage_class: 'open', position: '10', probability: '', active: true, remap: '' });
export function PipelineStageSettings({ onChanged }: { onChanged: () => void }) {
  const [stages, setStages] = useState<PipelineStage[]>([]);
  const [editing, setEditing] = useState<number | null>(null);
  const [form, setForm] = useState(blank());
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const load = useCallback(async () => {
    try { setStages(await api.listPipelineStages(true)); } catch (error) { setError(error instanceof Error ? error.message : 'Stage settings unavailable'); }
  }, []);
  useEffect(() => { void load(); }, [load]);
  const set = (key: keyof ReturnType<typeof blank>, value: string | boolean) => setForm(previous => ({ ...previous, [key]: value }));
  const save = async () => {
    setError('');
    const probability = form.probability === '' ? null : Number(form.probability);
    if (!form.label.trim() || !Number.isInteger(Number(form.position)) || probability !== null && (!Number.isInteger(probability) || probability < 0 || probability > 100)) return setError('Provide a label, integer position and probability from 0 to 100, or leave probability blank.');
    if (editing && !form.active && !window.confirm('Retire this stage for all accounts? Deals will move to the chosen stage.')) return;
    setBusy(true);
    try {
      if (editing) await api.updatePipelineStage(editing, { label: form.label.trim(), position: Number(form.position), default_probability: probability, active: form.active, ...(form.remap ? { remap_to_stage_id: Number(form.remap) } : {}) });
      else await api.createPipelineStage({ key: form.key, label: form.label.trim(), stage_class: form.stage_class, position: Number(form.position), default_probability: probability });
      setEditing(null); setForm(blank()); await load(); onChanged();
    } catch (error) { setError(error instanceof Error ? error.message : 'Stage save failed'); }
    finally { setBusy(false); }
  };
  return <section aria-label="Pipeline stage administration" className="crm-surface">
    <h3>Pipeline stages · all accounts</h3>
    <p>Stage probability is a suggestion. Retiring a used stage requires an active replacement of the same class.</p>
    {error && <p role="alert">{error} <button onClick={() => void load()}>Retry stages</button></p>}
    <ul>{stages.map(stage => <li key={stage.id}>{stage.label} · {stage.stage_class} · position {stage.position} · {stage.active ? 'active' : 'retired'} <button onClick={() => { setEditing(stage.id); setForm({ key: stage.key, label: stage.label, stage_class: stage.stage_class, position: String(stage.position), probability: stage.default_probability == null ? '' : String(stage.default_probability), active: stage.active, remap: '' }); }}>Edit {stage.label}</button></li>)}</ul>
    <form onSubmit={event => { event.preventDefault(); void save(); }} className="crm-list-controls">
      <h4>{editing ? 'Edit stage' : 'New stage'}</h4>
      {!editing && <label>Stable key<input required aria-label="Stage key" pattern="[a-z][a-z0-9_]*" value={form.key} onChange={event => set('key', event.target.value)} /></label>}
      <label>Label<input required aria-label="Stage label" value={form.label} onChange={event => set('label', event.target.value)} /></label>
      <label>Class<select aria-label="Stage class" disabled={!!editing} value={form.stage_class} onChange={event => set('stage_class', event.target.value)}>{['open', 'won', 'lost'].map(value => <option key={value}>{value}</option>)}</select></label>
      <label>Position<input aria-label="Stage position" type="number" value={form.position} onChange={event => set('position', event.target.value)} /></label>
      <label>Suggested probability<input aria-label="Stage suggested probability" type="number" min="0" max="100" value={form.probability} onChange={event => set('probability', event.target.value)} /></label>
      {editing && <><label><input type="checkbox" checked={form.active} onChange={event => set('active', event.target.checked)} />Active stage</label>
        {!form.active && <label>Replacement<select aria-label="Replacement stage" value={form.remap} onChange={event => set('remap', event.target.value)}><option value="">Select if stage is in use</option>{stages.filter(stage => stage.active && stage.id !== editing && stage.stage_class === form.stage_class).map(stage => <option key={stage.id} value={stage.id}>{stage.label}</option>)}</select></label>}</>}
      <button disabled={busy} type="submit">{busy ? 'Saving…' : 'Save stage'}</button>
      <button type="button" onClick={() => { setEditing(null); setForm(blank()); }}>Cancel stage edit</button>
    </form>
  </section>;
}
