import { useEffect, useRef, useState } from 'react';
import { api } from '../../lib/api';
import type { RedHatOpportunityImportResult, RedHatOpportunityImportSummary } from '../../types/redhatOpportunity';

export function RedHatOpportunityPane() {
  const [file, setFile] = useState<File | null>(null);
  const [result, setResult] = useState<RedHatOpportunityImportResult | null>(null);
  const [history, setHistory] = useState<RedHatOpportunityImportSummary[]>([]);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [review, setReview] = useState<{ id: number; rows: RedHatOpportunityImportResult['skipped'] } | null>(null);
  const input = useRef<HTMLInputElement>(null);

  useEffect(() => {
    let active = true;
    api.listRedHatOpportunityImports().then(rows => { if (active) setHistory(rows); })
      .catch(err => { if (active) setError(err instanceof Error ? err.message : 'Unable to load imports.'); });
    return () => { active = false; };
  }, []);

  async function upload() {
    if (!file || busy) return;
    setBusy(true); setError(''); setResult(null);
    try {
      const imported = await api.uploadRedHatOpportunityImport(file);
      setResult(imported); setFile(null);
      setReview({ id: imported.import_id, rows: imported.skipped });
      if (input.current) input.current.value = '';
      setHistory(await api.listRedHatOpportunityImports());
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Import failed.');
    } finally { setBusy(false); }
  }

  async function reviewImport(id: number) {
    try { setError(''); setReview({ id, rows: await api.getRedHatOpportunityUnmatched(id) }); }
    catch (err) { setError(err instanceof Error ? err.message : 'Unable to load unmatched rows.'); }
  }

  return <section aria-label="Red Hat Opportunity Import">
    <h3>Red Hat Opportunity Import</h3>
    <p>Import a Red Hat account opportunity workbook. Accounts match existing customer names or aliases; no customers are created. The workbook’s account owner is shown as the Red Hat representative and does not change the S-A-I-L owner.</p>
    <label>Opportunity workbook (.xlsx) <input ref={input} type="file" accept=".xlsx" onChange={e => setFile(e.target.files?.[0] ?? null)} /></label>{' '}
    <button type="button" disabled={!file || busy} onClick={upload}>{busy ? 'Importing…' : 'Import workbook'}</button>
    {error && <p role="alert">{error}</p>}
    {result && <div role="status"><p>Imported {result.matched_rows} of {result.total_rows} rows for {result.matched_accounts} customers. {result.skipped.length} rows could not be matched to an accessible customer.</p>
      <p>To improve matching, review customer names and approved aliases, then import the workbook again.</p>
    </div>}
    <h4>Recent imports</h4>
    {history.length === 0 ? <p>No opportunity imports yet.</p> : <ul>{history.map(item => <li key={item.import_id}>
      {item.file_name} — {item.created_at.slice(0, 10)} — {item.matched_rows} of {item.total_rows} rows matched{' '}
      <button type="button" onClick={() => reviewImport(item.import_id)}>Review unmatched rows</button>
    </li>)}</ul>}
    {review && <section aria-label="Unmatched rows"><h4>Unmatched rows for import {review.id}</h4>
      {review.rows.length === 0 ? <p>All rows matched.</p> : <ul>{review.rows.map(row =>
        <li key={row.source_row}>{row.account} — {row.reason}
          {row.suggestion && <>. Possible match to review: {row.suggestion.customer_name}</>}</li>)}</ul>}
    </section>}
  </section>;
}
