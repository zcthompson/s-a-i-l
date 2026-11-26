import { useEffect, useState } from 'react';
import { api } from '../lib/api';
import { formatDealAmount, probabilityText } from '../lib/deals';
import { useWorkspaceActions } from '../lib/useWorkspaceActions';
import type { Deal, DealInput } from '../types/deals';
const roles = ['decision_maker', 'economic_buyer', 'champion', 'influencer', 'technical', 'user', 'other'];
export function DealDetail({ customerId, id, onClose, onEdit, customerName, onOpenRecord, onChanged }: { customerId: number; id: number; customerName?: string; onChanged?: () => void; onOpenRecord?: (module: string, id: number) => void; onClose: () => void; onEdit?: (id: number) => void }) {
  const [deal, setDeal] = useState<Deal | null>(null);
  const [retry, setRetry] = useState(0);
  const [error, setError] = useState('');
  const [choices, setChoices] = useState<Record<string, { id: number; label: string }[]> | null>(null);
  const [links, setLinks] = useState<DealInput>({});
  const [vendorChoices, setVendorChoices] = useState<{ import_id: number; opportunity_number: string }[]>([]);
  const [busy, setBusy] = useState(false);
  const { data: actions } = useWorkspaceActions(customerId);
  useEffect(() => {
    let alive = true; setDeal(null); setError('');
    api.getDeal(id).then(row => {
      if (row.customer_id !== customerId) throw new Error('Deal unavailable');
      if (alive) { setDeal(row); setLinks({ contacts: row.contacts, task_ids: row.task_ids, activity_ids: row.activity_ids, note_ids: row.note_ids, technology_ids: row.technology_ids, vendor_evidence: row.vendor_evidence ?? [] }); }
    }).catch(() => { if (alive) setError('Deal unavailable or access was removed.'); });
    return () => { alive = false; };
  }, [customerId, id, retry]);
  const loadChoices = async () => {
    setError('');
    try {
      if (customerName) {
        const pipeline = await api.getCustomerPipeline(customerName);
        setVendorChoices(pipeline.import_id ? [...new Set(pipeline.rows.map(row => row.opportunity_number?.trim()).filter((number): number is string => !!number))].map(number => ({ import_id: pipeline.import_id!, opportunity_number: number })) : []);
      }
      const [contacts, tasks, activities, notes, technologies] = await Promise.all([api.listCustomerContacts(customerId, { includeArchived: true }), api.listTasks(customerId), api.listActivities(customerId), api.listCustomerSalesNotes(customerId), api.listCustomerTechnology(customerId)]);
      setChoices({ contacts: contacts.map(row => ({ id: row.id, label: row.display_name })), task_ids: tasks.map(row => ({ id: row.id, label: row.title })), activity_ids: activities.map(row => ({ id: row.id, label: `${row.type} · ${row.outcome ?? row.occurred_date ?? 'Undated'}` })), note_ids: notes.map(row => ({ id: row.id, label: row.title })), technology_ids: technologies.map(row => ({ id: row.id, label: row.name })) });
    } catch { setError('Related records unavailable. Retry editing links.'); }
  };
  const save = async () => {
    if (!deal) return;
    setBusy(true); setError('');
    try { const row = await api.updateDeal(id, { ...links, expected_version: deal.version }); setDeal(row); setChoices(null); onChanged?.(); }
    catch (error) { setError(error instanceof Error ? error.message : 'Links could not be saved.'); }
    finally { setBusy(false); }
  };
  if (!deal) return <section className="crm-surface crm-deal-detail" aria-label="Deal detail">{error ? <p role="alert">{error} <button onClick={() => setRetry(value => value + 1)}>Retry deal</button></p> : <p role="status">Loading deal…</p>}<button onClick={onClose}>Return to section</button></section>;
  return <section className="crm-surface crm-deal-detail" aria-label="Deal detail">
    <h2>{deal.name}</h2><p>{deal.stage.label} · {formatDealAmount(deal)} · Probability {probabilityText(deal)}</p>
    <p>Owner: {deal.owner_name ?? 'Unassigned'} · Close: {deal.close_date ?? 'Not recorded'}</p>
    <p>Next step: {deal.next_step ?? 'Not recorded'} {deal.next_step_date ?? ''}</p>
    {actions?.capabilities.deal && <><button onClick={() => onEdit?.(deal.id)}>Edit deal details</button> <button onClick={() => void loadChoices()}>Edit relationships</button></>}
    {error && <p role="alert">{error} <button onClick={() => setRetry(value => value + 1)}>Reload current deal</button></p>}
    <h3>Linked evidence and stakeholders</h3>
    {Object.entries({ Contacts: deal.contacts.map(row => `#${row.contact_id} (${row.role ?? 'role not recorded'})`), Tasks: deal.task_ids, Activities: deal.activity_ids, Notes: deal.note_ids, Technology: deal.technology_ids }).map(([label, values]) => <p key={label}>{label}: {values.length ? values.join(', ') : 'None linked'}</p>)}
    <div className="crm-actions">{[
      ...deal.contacts.map(link => ({ module: 'contact', id: link.contact_id })), ...deal.task_ids.map(id => ({ module: 'task', id })), ...deal.activity_ids.map(id => ({ module: 'activity', id })), ...deal.note_ids.map(id => ({ module: 'note', id })), ...deal.technology_ids.map(id => ({ module: 'technology', id })),
    ].map(link => <button key={`${link.module}-${link.id}`} onClick={() => onOpenRecord?.(link.module, link.id)}>Open {link.module} #{link.id}</button>)}</div>
    {(deal.vendor_evidence ?? []).map(row => <p key={`${row.import_id}-${row.opportunity_number}`}>Vendor opportunity {row.opportunity_number} · import #{row.import_id} · retained evidence only</p>)}
    {choices && <fieldset><legend>Edit relationships</legend>
      <label>Deal owner<select aria-label="Deal owner" value={links.owner_user_id === undefined ? deal.owner_user_id ?? '' : links.owner_user_id ?? ''} onChange={event => setLinks(previous => ({ ...previous, owner_user_id: event.target.value ? Number(event.target.value) : null }))}>
        <option value="">Unassigned</option>{deal.owner_user_id && !actions?.assignees.some(user => user.id === deal.owner_user_id) && <option value={deal.owner_user_id}>{deal.owner_name} (current owner)</option>}{actions?.assignees.filter(user => user.id !== undefined).map(user => <option key={user.id} value={user.id}>{user.display_name} ({user.username})</option>)}
      </select></label>
      <h4>Vendor opportunity evidence</h4>{[...new Map([...(deal.vendor_evidence ?? []), ...vendorChoices].map(item => [`${item.import_id}:${item.opportunity_number}`, item])).values()].map(item => <label key={`${item.import_id}:${item.opportunity_number}`} style={{ display: 'block' }}>
        <input type="checkbox" checked={(links.vendor_evidence ?? []).some(link => link.import_id === item.import_id && link.opportunity_number === item.opportunity_number)} onChange={event => setLinks(previous => ({ ...previous, vendor_evidence: event.target.checked ? [...(previous.vendor_evidence ?? []), item] : previous.vendor_evidence?.filter(link => link.import_id !== item.import_id || link.opportunity_number !== item.opportunity_number) }))} />{item.opportunity_number} · import #{item.import_id}
      </label>)}{Object.entries(choices).map(([field, rows]) => <section key={field}><h4>{field.replace(/_ids$/, '').replace(/_/g, ' ')}</h4>{rows.map(row => {
      const selected = field === 'contacts' ? (links.contacts ?? []).some(link => link.contact_id === row.id) : ((links[field as keyof DealInput] ?? []) as number[]).includes(row.id);
      return <div key={row.id}><label><input type="checkbox" checked={selected} onChange={event => {
        const checked = event.target.checked;
        setLinks(previous => field === 'contacts' ? { ...previous, contacts: checked ? [...(previous.contacts ?? []), { contact_id: row.id, role: null }] : previous.contacts?.filter(link => link.contact_id !== row.id) }
          : { ...previous, [field]: checked ? [...((previous[field as keyof DealInput] ?? []) as number[]), row.id] : ((previous[field as keyof DealInput] ?? []) as number[]).filter(id => id !== row.id) });
      }} />{row.label}</label>{field === 'contacts' && selected && <select aria-label={`Buying role for ${row.label}`} value={links.contacts?.find(link => link.contact_id === row.id)?.role ?? ''} onChange={event => setLinks(previous => ({ ...previous, contacts: previous.contacts?.map(link => link.contact_id === row.id ? { ...link, role: event.target.value || null } : link) }))}><option value="">Role not recorded</option>{roles.map(role => <option key={role} value={role}>{role.replace(/_/g, ' ')}</option>)}</select>}</div>;
    })}</section>)}<button disabled={busy} onClick={() => void save()}>Save relationships</button><button onClick={() => setChoices(null)}>Cancel relationship edit</button></fieldset>}
    <button onClick={onClose}>Return to section</button>
  </section>;
}
