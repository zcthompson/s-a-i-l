// Shared navigation model — single source of truth for the sidebar tree,
// section-root resolution, view normalization, and view labels.
//
// Consumed by:
//   - Sidebar.tsx: nav tree, active-state detection, breadcrumb
//   - Home.tsx:    view state ↔ ?view= URL sync (seed, back/forward, deep links)
//
// Keeping this here (rather than duplicated in each component) means adding
// or renaming a nav entry requires touching exactly one file.

// Recursive: a child may itself be a group with children (Global Intelligence
// ▸ Collaboration ▸ Comments).
export interface NavItem {
  id: string;
  label: string;
  icon: string;
  children?: NavItem[];
}

/** @deprecated alias kept for existing imports; children are NavItems. */
export type NavChildItem = NavItem;

export const NAV_ITEMS: NavItem[] = [
  { id: 'dashboard', label: 'Dashboard', icon: '🏠' },
  { id: 'customers', label: 'Customers', icon: '🏢', children: [
    { id: 'customers', label: 'My Customers', icon: '📋' },
    { id: 'customer-create', label: 'New Customer', icon: '➕' },
  ]},
  { id: 'global-intelligence', label: 'Global Intelligence', icon: '🧭', children: [
    { id: 'gi-import', label: 'Intelligence Import', icon: '📥' },
    { id: 'gi-collab', label: 'Collaboration', icon: '💬', children: [
      { id: 'collab-comments', label: 'Comments', icon: '📝' },
      { id: 'collab-notifications', label: 'Notifications', icon: '🔔' },
    ]},
    { id: 'export', label: 'Export', icon: '📤' },
  ]},
  { id: 'settings', label: 'Settings', icon: '⚙️', children: [
    { id: 'settings-appearance', label: 'Appearance', icon: '🎨' },
  ]},
  { id: 'admin', label: 'Admin', icon: '🛡️', children: [
    { id: 'admin-pending', label: 'Pending Approvals', icon: '📋' },
    { id: 'admin-users', label: 'All Users', icon: '👥' },
    { id: 'admin-integrations', label: 'Application Settings', icon: '🔗' },
    { id: 'admin-global', label: 'Global Admin Dashboard', icon: '📊' },
    { id: 'admin-ownership', label: 'Customer Ownership', icon: '🔑' },
  ]},
];

// Views that only render meaningful content when a use case is selected.
// Arriving at one of these with no selection (e.g. a shared ?view=detail
// link) lands on the assessment list instead of a dead-end page.
export const SELECTION_REQUIRED_VIEWS: ReadonlySet<string> = new Set([
  'detail',
  'scoring-dashboard',
  'scoring-history',
  'scoring-drilldown',
]);

// Section roots that Home does not render directly: navigating to them
// lands on the section's first child.
const SECTION_FALLBACKS: Record<string, string> = {
  'global-intelligence': 'gi-import',
  'gi-collab': 'collab-comments',
  // Legacy section id from the pre-Global-Intelligence nav (old deep links).
  collab: 'collab-comments',
  'my-dashboard': 'dashboard',
};

/** Map a section-root view id to a renderable view id. */
export function normalizeView(view: string): string {
  return SECTION_FALLBACKS[view] ?? view;
}

/** True when the view needs a selected use case to render. */
export function isSelectionRequiredView(view: string): boolean {
  return SELECTION_REQUIRED_VIEWS.has(view);
}

/** Find a nav node by id anywhere in the tree. */
export function findNavItem(id: string, items: NavItem[] = NAV_ITEMS): NavItem | null {
  for (const item of items) {
    if (item.id === id) return item;
    const hit = item.children ? findNavItem(id, item.children) : null;
    if (hit) return hit;
  }
  return null;
}

// Innermost group (a node with children) that contains the view as a
// descendant, walking the tree recursively. Child view ids may also share a
// child's prefix (e.g. 'admin-pending-x' under 'admin-pending').
function findSectionRoot(view: string, items: NavItem[]): string | null {
  for (const item of items) {
    if (!item.children) continue;
    const nested = findSectionRoot(view, item.children);
    if (nested) return nested;
    for (const child of item.children) {
      if (child.id === view || view.startsWith(child.id + '-')) return item.id;
    }
  }
  return null;
}

/** Parent section id for a view, or null when the view is outside sections.
 *  Returns the INNERMOST group containing the view
 *  (collab-comments → 'gi-collab'; export / gi-import → 'global-intelligence'). */
export function getSectionRoot(view: string): string | null {
  return findSectionRoot(view, NAV_ITEMS);
}

/** All group ids enclosing a view, outermost first (expand-on-arrival and
 *  active-state of every ancestor). */
export function getSectionPath(view: string): string[] {
  const walk = (items: NavItem[]): string[] | null => {
    for (const item of items) {
      if (!item.children) continue;
      const nested = walk(item.children);
      if (nested) return [item.id, ...nested];
      if (item.children.some(c => c.id === view || view.startsWith(c.id + '-'))) return [item.id];
    }
    return null;
  };
  return walk(NAV_ITEMS) ?? [];
}

/** First child id of a section — where breadcrumb-root and collapsed-rail
 *  clicks navigate. Leaf sections (no children) return their own id. A
 *  nested group resolves down to its first renderable leaf. */
export function firstChildOf(sectionId: string): string {
  const item = findNavItem(sectionId);
  return item ? firstLeafOf(item) : sectionId;
}

/** First renderable leaf under an item (the item's own id when it is a leaf).
 *  Operates on the given node so role-filtered copies (ps_admin's Admin)
 *  resolve against the children actually shown. */
export function firstLeafOf(item: NavItem): string {
  const first = item.children?.[0];
  return first ? firstLeafOf(first) : item.id;
}

/** Human label for a view id (breadcrumb / header). Falls back to a
 *  title-cased id for views without an explicit label. */
const VIEW_LABELS: Record<string, string> = {
  'dashboard': 'Dashboard',
  'my-dashboard': 'Dashboard',
  'customers': 'My Customers',
  'customer-create': 'New Customer',
  'global-intelligence': 'Global Intelligence',
  'gi-import': 'Intelligence Import',
  'export': 'Export',
  'export-pdf': 'Export PDF',
  'export-excel': 'Export Excel',
  'collab-comments': 'Comments',
  'collab-notifications': 'Notifications',
  'settings': 'Settings',
  'settings-appearance': 'Appearance',
  'admin': 'Admin',
  'admin-pending': 'Pending Approvals',
  'admin-users': 'All Users',
  'admin-integrations': 'Application Settings',
  'admin-global': 'Global Admin Dashboard',
  'admin-ownership': 'Customer Ownership',
  'assessment': 'Assessments',
  'assessment-list': 'Assessments',
  'assessment-create': 'New Assessment',
  'assessment-bulk': 'Bulk Scoring',
  'assessment-templates': 'Templates',
  'detail': 'Use Case Detail',
  'scoring-dashboard': 'Scoring Results',
  'scoring-history': 'Score History',
  'scoring-drilldown': 'Score Drill-Down',
  'analytics-matrix': 'Impact Matrix',
  'analytics-dept': 'Department Comparison',
  'analytics-correlation': 'Readiness Insights',
  'analytics-trends': 'Trends',
  'business-impact': 'Business Impact',
};

export function getViewLabel(view: string): string {
  if (VIEW_LABELS[view]) return VIEW_LABELS[view];
  return view.split('-').map(p => p.charAt(0).toUpperCase() + p.slice(1)).join(' ');
}
