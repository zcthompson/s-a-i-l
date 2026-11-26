// Regression tests for the shared navigation model (lib/nav.ts) — the
// decision logic behind sidebar structure, section roots, deep-link
// normalization, and breadcrumb labels.
import { describe, it, expect } from 'vitest';
import {
  NAV_ITEMS,
  getSectionRoot,
  firstChildOf,
  normalizeView,
  isSelectionRequiredView,
  getViewLabel,
  getSectionPath,
  firstLeafOf,
  findNavItem,
} from '../src/lib/nav';

describe('nav model', () => {
  it('resolves section roots for child views', () => {
    // Innermost containing group: collab views live in the nested
    // Collaboration group under Global Intelligence.
    expect(getSectionRoot('collab-comments')).toBe('gi-collab');
    expect(getSectionRoot('collab-notifications')).toBe('gi-collab');
    expect(getSectionRoot('export')).toBe('global-intelligence');
    expect(getSectionRoot('gi-import')).toBe('global-intelligence');
    expect(getSectionRoot('gi-collab')).toBe('global-intelligence');
    expect(getSectionRoot('customer-create')).toBe('customers');
    expect(getSectionRoot('customers')).toBe('customers');
    expect(getSectionRoot('admin-global')).toBe('admin');
    expect(getSectionRoot('admin-pending')).toBe('admin');
    expect(getSectionRoot('settings-appearance')).toBe('settings');
  });

  it('returns null for views outside sections', () => {
    expect(getSectionRoot('dashboard')).toBeNull();
    expect(getSectionRoot('detail')).toBeNull();
    expect(getSectionRoot('scoring-dashboard')).toBeNull();
    // 'export-pdf' prefix-matches the Export leaf, so it stays inside the section.
    expect(getSectionRoot('export-pdf')).toBe('global-intelligence');
    expect(getSectionRoot('totally-unknown')).toBeNull();
  });

  it('does not confuse the customers section with customer-* views', () => {
    // 'customer-create' must not be mistaken for a 'customers-' prefix.
    expect(getSectionRoot('customer-create')).toBe('customers');
    expect('customer-create'.startsWith('customers-')).toBe(false);
  });

  it('maps section roots to their first child', () => {
    expect(firstChildOf('global-intelligence')).toBe('gi-import');
    expect(firstChildOf('gi-collab')).toBe('collab-comments');
    expect(firstChildOf('customers')).toBe('customers');
    expect(firstChildOf('admin')).toBe('admin-pending');
    expect(firstChildOf('settings')).toBe('settings-appearance');
    // Leaf sections (no children) navigate to themselves.
    expect(firstChildOf('export')).toBe('export');
    expect(firstLeafOf({ id: 'a', label: 'A', icon: '', children: [{ id: 'b', label: 'B', icon: '', children: [{ id: 'c', label: 'C', icon: '' }] }] })).toBe('c');
    expect(firstChildOf('unknown-section')).toBe('unknown-section');
  });

  it('normalizes section-root views to a renderable view', () => {
    // 'collab' is not a renderable view — it must land on its first child.
    expect(normalizeView('collab')).toBe('collab-comments'); // legacy deep link
    expect(normalizeView('global-intelligence')).toBe('gi-import');
    expect(normalizeView('gi-collab')).toBe('collab-comments');
    expect(normalizeView('customers')).toBe('customers');
    expect(normalizeView('dashboard')).toBe('dashboard');
    expect(normalizeView('my-dashboard')).toBe('dashboard');
    expect(findNavItem('my-dashboard')).toBeNull();
    expect(normalizeView('detail')).toBe('detail');
  });

  it('flags selection-required views', () => {
    expect(isSelectionRequiredView('detail')).toBe(true);
    expect(isSelectionRequiredView('scoring-dashboard')).toBe(true);
    expect(isSelectionRequiredView('scoring-history')).toBe(true);
    expect(isSelectionRequiredView('scoring-drilldown')).toBe(true);
    // collab-comments auto-selects its own use case — NOT selection-
    // required (redirecting it would skip its honest empty state).
    expect(isSelectionRequiredView('collab-comments')).toBe(false);
    expect(isSelectionRequiredView('dashboard')).toBe(false);
    expect(isSelectionRequiredView('assessment-list')).toBe(false);
  });

  it('labels breadcrumb views with human names', () => {
    expect(getViewLabel('collab-comments')).toBe('Comments');
    expect(getViewLabel('collab-notifications')).toBe('Notifications');
    expect(getViewLabel('global-intelligence')).toBe('Global Intelligence');
    expect(getViewLabel('gi-import')).toBe('Intelligence Import');
    expect(getViewLabel('customer-create')).toBe('New Customer');
    expect(getViewLabel('admin-pending')).toBe('Pending Approvals');
    expect(getViewLabel('admin-global')).toBe('Global Admin Dashboard');
    expect(getViewLabel('customers')).toBe('My Customers');
    // Unknown views fall back to a title-cased id.
    expect(getViewLabel('some-unknown-view')).toBe('Some Unknown View');
  });

  it('models Global Intelligence as a recursive tree and drops the old top-level entries', () => {
    const topIds = NAV_ITEMS.map(i => i.id);
    expect(topIds).not.toContain('export');
    expect(topIds).not.toContain('collab');
    expect(topIds.indexOf('global-intelligence')).toBe(topIds.indexOf('customers') + 1);
    expect(topIds.indexOf('settings')).toBe(topIds.indexOf('global-intelligence') + 1);
    const gi = findNavItem('global-intelligence')!;
    expect(gi.children!.map(c => c.id)).toEqual(['gi-import', 'gi-collab', 'export']);
    expect(findNavItem('gi-collab')!.children!.map(c => c.id)).toEqual(['collab-comments', 'collab-notifications']);
    expect(getSectionPath('collab-comments')).toEqual(['global-intelligence', 'gi-collab']);
    expect(getSectionPath('gi-import')).toEqual(['global-intelligence']);
    expect(getSectionPath('dashboard')).toEqual([]);
  });

  it('keeps NAV_ITEMS consistent with the section roots it declares', () => {
    // Every node must resolve to its innermost parent group; every group's
    // first leaf must exist in the tree. Recursive.
    const walk = (items: typeof NAV_ITEMS) => {
      for (const item of items) {
        if (!item.children) continue;
        for (const child of item.children) {
          if (child.id !== item.id) expect(getSectionRoot(child.id)).toBe(item.id);
        }
        expect(findNavItem(firstLeafOf(item))).not.toBeNull();
        walk(item.children);
      }
    };
    walk(NAV_ITEMS);
  });
});
