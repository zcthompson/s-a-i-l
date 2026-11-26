import { SectionIcon } from './SectionIcon';
import { useEffect, useState } from 'react';
import {
  NAV_ITEMS,
  NavItem,
  getSectionRoot,
  getSectionPath,
  findNavItem,
  firstChildOf,
  firstLeafOf,
  getViewLabel,
} from '../lib/nav';
import { APP_VERSION } from '../lib/version';
import { useReducedMotion } from '../lib/theme';

interface SidebarProps {
  activeView: string;
  onNavigate: (view: string) => void;
  username: string;
  onLogout: () => void;
  isCollapsed: boolean;
  onToggle: () => void;
  is_admin?: boolean;
  userRole?: string;
  /** Non-admin sales managers create admin-reviewed prospect accounts. */
  canCreateProspects?: boolean;
}

// No class attributes / scoped CSS here: the app is 100% inline-style and
// CI hard-fails on class usage in components/pages. Keyboard focus on the
// tabindex=0 nav rows/chevrons uses the browser's native :focus-visible
// outline — the same default every other control in the app relies on.

export function Sidebar({ activeView, onNavigate, username, onLogout, isCollapsed, onToggle, is_admin, userRole, canCreateProspects }: SidebarProps) {
  const reducedMotion = useReducedMotion();
  const [expandedSections, setExpandedSections] = useState<Record<string, boolean>>({
    'customers': true,
    'global-intelligence': false,
    'gi-collab': false,
    'settings': false,
    'admin': false,
  });

  const visibleNavItems: NavItem[] = NAV_ITEMS.flatMap((item) => {
    if (item.id === 'admin') {
      if (is_admin) return [item];
      if (userRole === 'ps_admin') {
        return [{ ...item, children: item.children?.filter((child) => child.id === 'admin-global') }];
      }
      return [];
    }
    if (item.id === 'customers' && !is_admin) {
      // F19: account creation is admin-only on the server (POST /api/customers/)
      // Except prospects for sales managers — no other role sees an entry
      // that would 403 on submit.
      if (canCreateProspects) {
        return [{ ...item, children: item.children?.map((child) => (
          child.id === 'customer-create' ? { ...child, label: 'New Prospect' } : child)) }];
      }
      return [{ ...item, children: item.children?.filter((child) => child.id !== 'customer-create') }];
    }
    return [item];
  });

  // Keep the section containing the active view expanded so the active
  // child is always visible — deep links (?view=admin-global) and
  // back/forward arrivals otherwise land with their section collapsed.
  useEffect(() => {
    const path = getSectionPath(activeView);
    if (path.length === 0) return;
    setExpandedSections(prev => (path.every(id => prev[id]) ? prev : { ...prev, ...Object.fromEntries(path.map(id => [id, true])) }));
  }, [activeView]);

  const toggleSection = (section: string) => {
    setExpandedSections(prev => ({ ...prev, [section]: !prev[section] }));
  };

  const handleNavigate = (view: string) => {
    onNavigate(view);
  };

  // Section header click: navigate to the section's first child. Expansion
  // is only ever ENFORCED, never toggled — re-clicking an already-expanded
  // section must not collapse the child list while the user is in it.
  // (Collapse is the chevron's job.)
  const handleSectionClick = (section: NavItem) => {
    if (section.children && section.children.length > 0) {
      setExpandedSections(prev => ({ ...prev, [section.id]: true }));
      onNavigate(firstLeafOf(section));
    } else {
      onNavigate(section.id);
    }
  };

  const isActive = (viewId: string) => {
    // Exact match for leaf views (avoids prefix collisions like
    // 'admin-pending' vs 'admin' or future 'dashboard-*' views).
    if (activeView === viewId) return true;
    // Section roots highlight when one of their child views is active
    // (child view ids share the section prefix, e.g. 'admin-pending').
    return activeView.startsWith(viewId + '-');
  };

  const hasActiveChild = (section: NavItem): boolean => {
    if (!section.children) return isActive(section.id);
    // Recursive: a nested leaf (collab-comments) lights every ancestor group.
    return section.children.some(child => hasActiveChild(child));
  };

  const renderNavButton = (item: NavItem, depth: number = 0) => {
    const hasChildren = item.children && item.children.length > 0;
    const isActiveSection = hasActiveChild(item);
    const isExpanded = expandedSections[item.id];

    const activate = () => {
      if (hasChildren) handleSectionClick(item);
      else handleNavigate(item.id);
    };

    return (
      <div key={item.id}>
        <div
          role="button"
          tabIndex={0}
          aria-label={item.label}
          onClick={activate}
          onKeyDown={(e) => {
            // The chevron is a separately focusable control; when it is the
            // focus target it handles Enter/Space itself (stopPropagation).
            if (e.target !== e.currentTarget) return;
            if (e.key === 'Enter' || e.key === ' ') {
              e.preventDefault();
              activate();
            }
          }}
          style={{
            width: '100%',
            display: 'flex',
            alignItems: 'center',
            gap: '10px',
            padding: `${8 + depth * 4}px ${20 - depth * 4}px`,
            background: isActiveSection ? 'var(--sidebar-selected)' : 'transparent',
            border: 'none',
            borderRadius: hasChildren ? '0' : 'var(--radius)',
            cursor: 'pointer',
            fontSize: `${0.9 - depth * 0.05}rem`,
            color: isActiveSection ? 'var(--sidebar-accent)' : 'var(--sidebar-muted)',
            transition: reducedMotion ? 'none' : 'all 0.2s',
            fontWeight: isActiveSection ? 600 : 400,
            justifyContent: 'flex-start',
            paddingLeft: `${20 + depth * 12}px`,
          }}
          onMouseEnter={e => {
            if (!isActiveSection) e.currentTarget.style.background = 'rgba(255,255,255,0.05)';
          }}
          onMouseLeave={e => {
            if (!isActiveSection) e.currentTarget.style.background = 'transparent';
          }}
        >
          <SectionIcon name={item.icon} />
          <span style={{ flex: 1, textAlign: 'left' }}>{item.label}</span>
          {hasChildren && (
            <span
              role="button"
              tabIndex={0}
              aria-label={isExpanded ? `Collapse ${item.label}` : `Expand ${item.label}`}
              onClick={(e) => {
                // Independent toggle: expand/collapse WITHOUT navigating.
                e.stopPropagation();
                toggleSection(item.id);
              }}
              onKeyDown={(e) => {
                if (e.key === 'Enter' || e.key === ' ') {
                  e.preventDefault();
                  e.stopPropagation();
                  toggleSection(item.id);
                }
              }}
              style={{ fontSize: '0.7rem', transition: reducedMotion ? 'none' : 'transform 0.2s', transform: isExpanded ? 'rotate(90deg)' : 'rotate(0deg)', cursor: 'pointer' }}
            >
              ▶
            </span>
          )}
        </div>

        {hasChildren && isExpanded && (
          <div style={{ padding: '2px 0 2px 8px' }}>
            {item.children!.map(child => renderNavButton(child, depth + 1))}
          </div>
        )}
      </div>
    );
  };

  if (isCollapsed) {
    return (
      <aside style={{
        width: '60px',
        flexShrink: 0,
        background: 'var(--sidebar-surface)',
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        padding: '12px 0',
        overflow: 'hidden',
        borderRight: '1px solid rgba(255,255,255,0.1)',
        height: 'var(--full-viewport, 100vh)',
        position: 'sticky',
        top: 0,
      }}>
        <div role="button" tabIndex={0} aria-label="Expand navigation" style={{ fontSize: '1.5rem', marginBottom: '1rem', cursor: 'pointer' }} onClick={onToggle} onKeyDown={(event) => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); onToggle(); } }}>
          <span aria-hidden="true">🚀</span>
        </div>
        <nav style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: '4px', width: '100%', alignItems: 'center' }} aria-label="Primary">
          {visibleNavItems.map(item => (
            <button role="button" aria-label={item.label}
              key={item.id}
              onClick={() => item.children && item.children.length > 0 ? handleNavigate(firstLeafOf(item)) : handleNavigate(item.id)}
              title={item.label}
              style={{
                width: '44px',
                height: '44px',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                background: hasActiveChild(item) ? 'var(--sidebar-selected)' : 'transparent',
                border: 'none',
                borderRadius: 'var(--radius)',
                cursor: 'pointer',
                fontSize: '1.2rem',
                color: hasActiveChild(item) ? 'var(--sidebar-accent)' : 'var(--sidebar-muted)',
                transition: reducedMotion ? 'none' : 'all 0.2s',
              }}
            >
              <SectionIcon name={item.icon} size={18} />
            </button>
          ))}
        </nav>
        <div style={{ borderTop: '1px solid rgba(255,255,255,0.1)', width: '100%', padding: '12px 0' }}>
          <button role="button" aria-label="Logout"
            onClick={onLogout}
            title="Logout"
            style={{
              width: '44px',
              height: '44px',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              background: 'transparent',
              border: 'none',
              borderRadius: 'var(--radius)',
              cursor: 'pointer',
              fontSize: '1.2rem',
              color: 'var(--sidebar-muted)',
            }}
          >
            <span aria-hidden="true">🚪</span>
          </button>
        </div>
      </aside>
    );
  }

  const breadcrumb = getViewLabel(activeView);
  const sectionRoot = getSectionRoot(activeView);

  return (
    <aside style={{
      width: '280px',
      flexShrink: 0,
      background: 'var(--sidebar-surface)',
      display: 'flex',
      flexDirection: 'column',
      borderRight: '1px solid rgba(255,255,255,0.1)',
      height: 'var(--full-viewport, 100vh)',
      position: 'sticky',
      top: 0,
      overflow: 'auto',
    }}>

      {/* Header */}
      <div style={{ padding: '16px 20px', borderBottom: '1px solid rgba(255,255,255,0.1)' }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <div>
            <div style={{ fontSize: '1.1rem', fontWeight: 'bold', color: 'var(--sidebar-ink)', letterSpacing: '-0.5px' }}>
              S-A-I-L
            </div>
            <div style={{ fontSize: '0.65rem', color: 'var(--sidebar-accent)', marginTop: '2px', letterSpacing: '1px', textTransform: 'uppercase' }}>
              Sales Analytics and Intelligence Launchpad
            </div>
          </div>
          <button role="button" aria-label="Collapse sidebar"
            onClick={onToggle}
            style={{
              background: 'rgba(90, 107, 194, 0.2)',
              border: 'none',
              borderRadius: 'var(--radius-sm)',
              color: 'var(--sidebar-accent)',
              cursor: 'pointer',
              padding: '4px 6px',
              fontSize: '0.7rem',
            }}
            title="Collapse sidebar"
          >
            ◀
          </button>
        </div>
      </div>

      {/* User Info */}
      <div style={{ padding: '12px 20px', borderBottom: '1px solid rgba(255,255,255,0.05)' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
          <div style={{
            width: '32px',
            height: '32px',
            borderRadius: '50%',
            background: 'var(--gradient-brand)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            fontSize: '0.85rem',
            color: 'white',
            fontWeight: 'bold',
          }}>
            {username ? username[0].toUpperCase() : 'U'}
          </div>
          <div>
            <div style={{ fontSize: '0.85rem', color: 'var(--sidebar-ink)', fontWeight: 500 }}>{username || 'User'}</div>
            <div style={{ fontSize: '0.7rem', color: 'var(--sidebar-accent)' }}>{is_admin ? 'Administrator' : 'Member'}</div>
          </div>
          <button role="button" aria-label="Logout" onClick={onLogout} style={{ marginLeft: 'auto', background: 'none', border: 'none', color: 'var(--sidebar-accent)', cursor: 'pointer', fontSize: '0.75rem', fontWeight: 500, textTransform: 'uppercase', letterSpacing: '0.5px' }}>
            LOGOUT
          </button>
        </div>
      </div>

      {/* Breadcrumb Navigation */}
      {sectionRoot && (
        <div style={{ padding: '8px 20px', borderBottom: '1px solid rgba(255,255,255,0.05)' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px', fontSize: '0.75rem', color: 'var(--sidebar-muted)' }}>
            {/* Root click goes to the section's first CHILD — the raw
                section id (e.g. 'collab') is not a renderable view. */}
            <button role="button" aria-label={`Go to ${findNavItem(sectionRoot)?.label || ''}`}
              onClick={() => onNavigate(firstChildOf(sectionRoot))}
              style={{
                background: 'none',
                border: 'none',
                color: 'var(--sidebar-accent)',
                cursor: 'pointer',
                fontSize: '0.75rem',
                padding: '0',
              }}
            >
              {findNavItem(sectionRoot)?.label || ''}
            </button>
            <span aria-hidden="true">/</span>
            <span style={{ color: 'var(--sidebar-ink)', fontWeight: 500 }}>{breadcrumb}</span>
          </div>
        </div>
      )}

      {/* Navigation */}
      <nav style={{ flex: 1, padding: '8px 0' }} aria-label="Primary">
        {visibleNavItems.map(item => renderNavButton(item))}
      </nav>

      {/* Footer */}
      <div style={{ padding: '12px 20px', borderTop: '1px solid rgba(255,255,255,0.1)' }}>
        <div style={{ fontSize: '0.65rem', color: 'var(--sidebar-muted)', textAlign: 'center' }}>
          {/* UX audit #15: version came from a hardcoded literal here; now the
              single frontend source of truth (package.json) so it can't drift
              from the backend /health on the next bump. */}
          v{APP_VERSION} — S-A-I-L
        </div>
      </div>
    </aside>
  );
}
