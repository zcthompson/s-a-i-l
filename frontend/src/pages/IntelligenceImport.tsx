/**
 * Intelligence Import (Global Intelligence) — source-selectable surface. Each
 * source pane is self-contained (form + history + detail). The selector is a
 * native grouped <select> driven by the typed registry in
 * components/intelligence-import/sources.ts (single source of truth); add a
 * future importer as a registry entry + pane. The selection lives in
 * ?source=<id> (router replace — never pushes entries, preserves ?view=
 * and other params). Manager-gated panes render their own access-denied state
 * when the API 403s; the Rep Provided pane is open to every authenticated user.
 */
import { useState } from 'react';
import { useInRouterContext, useSearchParams } from 'react-router-dom';
import { RedHatPipelinePane } from '../components/intelligence-import/RedHatPipelinePane';
import { RedHatOpportunityPane } from '../components/intelligence-import/RedHatOpportunityPane';
import { VMwareRvToolsPane } from '../components/intelligence-import/VMwareRvToolsPane';
import { GenericRepIntelligencePane } from '../components/intelligence-import/GenericRepIntelligencePane';
import { NetSuiteImportPane } from '../components/intelligence-import/NetSuiteImportPane';
import {
  DEFAULT_IMPORT_SOURCE,
  IMPORT_SOURCES,
  groupImportSources,
  isImportSourceId,
  type ImportSourceId,
} from '../components/intelligence-import/sources';

interface IntelligenceImportProps {
  /** Open a customer's dashboard (sets the selected customer + view). */
  onOpenCustomer?: (name: string) => void;
}

function readSourceFromUrl(): ImportSourceId {
  if (typeof window === 'undefined') return DEFAULT_IMPORT_SOURCE;
  const raw = new URLSearchParams(window.location.search).get('source');
  return isImportSourceId(raw) ? raw : DEFAULT_IMPORT_SOURCE;
}

function useRoutedSource(): [ImportSourceId, (next: string) => void] {
  const [params, setParams] = useSearchParams();
  const raw = params.get('source');
  const source = isImportSourceId(raw) ? raw : DEFAULT_IMPORT_SOURCE;
  const change = (next: string) => {
    if (!isImportSourceId(next)) return;
    setParams((previous) => {
      const updated = new URLSearchParams(previous);
      updated.set('source', next);
      updated.delete('import');
      return updated;
    }, { replace: true });
  };
  return [source, change];
}

function useLocalSource(): [ImportSourceId, (next: string) => void] {
  const [source, setSource] = useState<ImportSourceId>(readSourceFromUrl);
  const change = (next: string) => {
    if (!isImportSourceId(next)) return;
    setSource(next);
    const url = new URL(window.location.href);
    url.searchParams.set('source', next);
    url.searchParams.delete('import');
    window.history.replaceState(window.history.state, '', `${url.pathname}${url.search}${url.hash}`);
  };
  return [source, change];
}

export function IntelligenceImport({ onOpenCustomer }: IntelligenceImportProps = {}) {
  const inRouter = useInRouterContext();
  // Router context remains stable for the lifetime of this mounted page.
  // eslint-disable-next-line react-hooks/rules-of-hooks
  const [source, changeSource] = inRouter ? useRoutedSource() : useLocalSource();
  const current = IMPORT_SOURCES.find((s) => s.id === source) ?? IMPORT_SOURCES[0];

  return (
    <div style={{ padding: '2rem', maxWidth: '1100px', margin: '0 auto' }} data-testid="intelligence-import">
      <h2 style={{ color: 'var(--ink)', marginBottom: '8px', fontSize: '1.4rem' }}>Intelligence Import</h2>
      <p style={{ color: 'var(--neutral-500)', fontSize: '0.85rem' }}>Refreshing or leaving this page clears any unsubmitted file and form entries. Select the file again to import it.</p>
      <div style={{ margin: '0 0 16px' }}>
        <label htmlFor="intelligence-import-source" style={{ display: 'block', fontSize: '0.8rem', fontWeight: 600, color: 'var(--neutral-500)', marginBottom: '4px' }}>
          Import source
        </label>
        <select
          id="intelligence-import-source"
          data-testid="intelligence-import-source-select"
          value={source}
          onChange={(e) => changeSource(e.target.value)}
          style={{ width: '100%', maxWidth: '420px', padding: '8px 12px', borderRadius: 'var(--radius)', border: '1px solid var(--divider)', background: 'var(--neutral-0)', color: 'var(--neutral-700)', fontSize: '0.9rem' }}
        >
          {groupImportSources().map((g) => (
            <optgroup key={g.group} label={g.group}>
              {g.sources.map((s) => (
                <option key={s.id} value={s.id}>{s.label}</option>
              ))}
            </optgroup>
          ))}
        </select>
        <div data-testid="intelligence-import-source-formats" style={{ marginTop: '4px', fontSize: '0.8rem', color: 'var(--neutral-500)' }}>
          Accepted: {current.formats}
        </div>
      </div>
      {source === 'redhat' && <RedHatPipelinePane onOpenCustomer={onOpenCustomer} />}
      {source === 'redhat-opportunity' && <RedHatOpportunityPane />}
      {source === 'vmware' && <VMwareRvToolsPane onOpenCustomer={onOpenCustomer} />}
      {source === 'rep' && <GenericRepIntelligencePane onOpenCustomer={onOpenCustomer} />}
      {source === 'netsuite' && <NetSuiteImportPane />}
    </div>
  );
}

export default IntelligenceImport;
