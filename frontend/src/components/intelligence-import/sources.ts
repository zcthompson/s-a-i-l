/**
 * Typed registry of Intelligence Import sources — the single source of truth
 * for the page's grouped selector. A future importer is one entry here plus a
 * pane component rendered by the page.
 */
export interface ImportSource {
  id: 'redhat' | 'redhat-opportunity' | 'vmware' | 'rep' | 'netsuite';
  /** optgroup label */
  group: string;
  /** option label */
  label: string;
  /** accepted file types (display) */
  formats: string;
  /** pane offers a template download */
  template: boolean;
}

export const IMPORT_SOURCES: readonly ImportSource[] = [
  { id: 'redhat', group: 'Vendor/Distributor Provided',
    label: 'Red Hat Partner Pipeline Import', formats: '.csv', template: false },
  { id: 'redhat-opportunity', group: 'Vendor/Distributor Provided',
    label: 'Red Hat Opportunity Import', formats: '.xlsx', template: false },
  { id: 'vmware', group: 'Customer Provided Accepted Imports',
    label: 'VMware RVTools Import', formats: '.xlsx, .xlsm', template: false },
  { id: 'rep', group: 'Rep Provided',
    label: 'Generic Account Intelligence Import (CSV)', formats: '.csv', template: true },
  { id: 'netsuite', group: 'NetSuite',
    label: 'NetSuite Intelligence Import', formats: '.csv, .xlsx', template: false },
] as const;

export type ImportSourceId = ImportSource['id'];
export const DEFAULT_IMPORT_SOURCE: ImportSourceId = 'redhat';

export function isImportSourceId(value: string | null | undefined): value is ImportSourceId {
  return IMPORT_SOURCES.some((s) => s.id === value);
}

/** Registry groups in first-seen order, each with its sources. */
export function groupImportSources(): { group: string; sources: ImportSource[] }[] {
  const groups: { group: string; sources: ImportSource[] }[] = [];
  for (const s of IMPORT_SOURCES) {
    const existing = groups.find((g) => g.group === s.group);
    if (existing) existing.sources.push(s);
    else groups.push({ group: s.group, sources: [s] });
  }
  return groups;
}
