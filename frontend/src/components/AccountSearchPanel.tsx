import { useEffect, useRef, useState } from 'react';
import { api } from '../lib/api';
import type { AccountSearchModule, AccountSearchResponse } from '../types/accountSearch';

const modules: AccountSearchModule[] = ['deal', 'use_case', 'note', 'contact', 'activity', 'task', 'technology', 'strategy', 'knowledge'];
const labels: Record<AccountSearchModule, string> = {
  deal: 'Deals', use_case: 'Use Cases', note: 'Notes', contact: 'Contacts', activity: 'Activities', task: 'Tasks',
  technology: 'Technology', strategy: 'Strategy', knowledge: 'Knowledge',
};

export default function AccountSearchPanel({ customerId, onSelect }: {
  customerId: number; onSelect?: (module: string, id: number) => void;
}) {
  const [query, setQuery] = useState('');
  const [retry, setRetry] = useState(0);
  const [result, setResult] = useState<AccountSearchResponse | null>(null);
  const [status, setStatus] = useState<'idle' | 'searching' | 'done' | 'error'>('idle');
  const sequence = useRef(0);
  useEffect(() => {
    const current = ++sequence.current;
    const q = query.trim();
    setResult(null);
    if (q.length < 2) { setStatus('idle'); return; }
    setStatus('searching');
    const timer = setTimeout(() => {
      api.searchAccount(customerId, q).then(data => {
        if (sequence.current === current) { setResult(data); setStatus('done'); }
      }).catch(() => {
        if (sequence.current === current) setStatus('error');
      });
    }, 300);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- pre-existing dependency list; change only with UI verification
    return () => { clearTimeout(timer); ++sequence.current; };
  }, [customerId, query, retry]);

  return <section aria-label="Account search" className="crm-account-search">
    <label style={{ display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap' }}>Search this account
      <input type="search" placeholder="Contacts, deals, notes and more…" value={query} maxLength={100} onChange={event => {
        ++sequence.current;
        setQuery(event.target.value);
      }} />
    </label>
    <div aria-live="polite">
      {status === 'idle' && query.length > 0 && <p>Enter at least 2 characters.</p>}
      {status === 'searching' && <p>Searching…</p>}
      {status === 'error' && <p>Search unavailable. Try again. <button onClick={() => setRetry(value => value + 1)}>Retry</button></p>}
      {result && <>
        {result.results.length === 0 && <p>No matches for '{result.query}'.</p>}
        {result.truncated && <p>Showing up to 10 matches per section. Counts show displayed matches; more matches may exist.</p>}
        {modules.filter(module => result.counts[module] > 0).map(module => <section key={module} aria-label={labels[module]}>
          <h3>{labels[module]} <span aria-label={`${labels[module]} count`}>{result.counts[module]}</span></h3>
          <ul>{result.results.filter(item => item.module === module).map(item => <li key={item.id}>
            <button onClick={() => onSelect?.(module, item.id)}>{item.title}</button>
            <p>{item.snippet}</p>
            {item.timestamp && <time dateTime={item.timestamp}>{item.timestamp}</time>}
          </li>)}</ul>
        </section>)}
      </>}
    </div>
  </section>;
}
