// Regression tests for Sidebar navigation behavior (fluid nav):
//   - section header click navigates to the first child WITHOUT collapsing
//   - the active section auto-expands on arrival (deep links / back-forward)
//   - breadcrumb root click goes to the section's first child (never the
//     dead section id, e.g. 'collab')
//   - chevron toggles expansion without navigating
//   - admin gating + collapsed-rail active state for child views
import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen, fireEvent, within, cleanup } from '@testing-library/react';
import { Sidebar } from '../src/components/Sidebar';

// Explicit cleanup: vitest runs without globals, so RTL's auto-cleanup
// (which hooks the global afterEach) never registers.
afterEach(cleanup);

const baseProps = {
  activeView: 'dashboard',
  onNavigate: () => {},
  username: 'tester',
  onLogout: () => {},
  isCollapsed: false,
  onToggle: () => {},
  is_admin: true,
};

describe('Sidebar navigation behavior', () => {
  it('navigates to a leaf view when a leaf row is clicked', () => {
    const onNavigate = vi.fn();
    render(<Sidebar {...baseProps} onNavigate={onNavigate} />);
    fireEvent.click(screen.getByRole('button', { name: 'Dashboard' }));
    expect(onNavigate).toHaveBeenCalledTimes(1);
    expect(onNavigate).toHaveBeenCalledWith('dashboard');
  });

  it('section header click navigates to the first child and keeps children visible', () => {
    const onNavigate = vi.fn();
    const { rerender } = render(
      <Sidebar {...baseProps} onNavigate={onNavigate} activeView="collab-comments" />
    );
    const navArea = screen.getByRole('navigation', { name: 'Primary' });
    // Auto-expand on arrival: both Collaboration children are visible.
    expect(within(navArea).getByText('Comments')).toBeTruthy();
    expect(within(navArea).getByText('Notifications')).toBeTruthy();

    // Re-click the section header while a child is active. Old behavior
    // TOGGLED the section — collapsing the child list while the user was
    // re-anchoring in it (context loss). It must navigate + stay expanded.
    fireEvent.click(screen.getByRole('button', { name: 'Collaboration' }));
    expect(onNavigate).toHaveBeenCalledTimes(1);
    expect(onNavigate).toHaveBeenCalledWith('collab-comments');

    rerender(<Sidebar {...baseProps} onNavigate={onNavigate} activeView="collab-comments" />);
    const navAreaAfter = screen.getByRole('navigation', { name: 'Primary' });
    expect(within(navAreaAfter).getByText('Comments')).toBeTruthy();
    expect(within(navAreaAfter).getByText('Notifications')).toBeTruthy();
  });

  it('auto-expands the section containing the active view on arrival', () => {
    // Admin is collapsed by default; arriving on admin-global (deep link /
    // back button) must expand it so the active child is visible.
    const onNavigate = vi.fn();
    render(<Sidebar {...baseProps} onNavigate={onNavigate} activeView="admin-global" />);
    const navArea = screen.getByRole('navigation', { name: 'Primary' });
    expect(within(navArea).getByText('Global Admin Dashboard')).toBeTruthy();
    expect(within(navArea).getByText('Pending Approvals')).toBeTruthy();
  });

  it('breadcrumb root click navigates to the first child, not the dead section id', () => {
    // Old behavior: onNavigate('collab') — a view Home does not render
    // (dead-end "Select a section from the sidebar").
    const onNavigate = vi.fn();
    render(<Sidebar {...baseProps} onNavigate={onNavigate} activeView="collab-comments" />);
    fireEvent.click(screen.getByRole('button', { name: 'Go to Collaboration' }));
    expect(onNavigate).toHaveBeenCalledTimes(1);
    expect(onNavigate).toHaveBeenCalledWith('collab-comments');
  });

  it('chevron toggle expands/collapses without navigating, and sticks', () => {
    const onNavigate = vi.fn();
    const { rerender } = render(
      <Sidebar {...baseProps} onNavigate={onNavigate} activeView="customers" />
    );
    const navArea = screen.getByRole('navigation', { name: 'Primary' });
    // Arriving on the customers section: expanded (initial + active root).
    expect(within(navArea).getByText('My Customers')).toBeTruthy();

    // Collapse via the chevron: children hidden, no navigation fired.
    fireEvent.click(screen.getByRole('button', { name: 'Collapse Customers' }));
    expect(onNavigate).not.toHaveBeenCalled();

    // A re-render with the same activeView must NOT re-expand (the user's
    // manual collapse sticks; auto-expand is keyed on activeView changes).
    rerender(<Sidebar {...baseProps} onNavigate={onNavigate} activeView="customers" />);
    const navAreaAfter = screen.getByRole('navigation', { name: 'Primary' });
    expect(within(navAreaAfter).queryByText('My Customers')).toBeNull();
  });

  it('hides the Admin section from non-admin users', () => {
    const onNavigate = vi.fn();
    render(<Sidebar {...baseProps} onNavigate={onNavigate} is_admin={false} activeView="dashboard" />);
    const navArea = screen.getByRole('navigation', { name: 'Primary' });
    expect(within(navArea).queryByRole('button', { name: 'Admin' })).toBeNull();
    expect(within(navArea).queryByRole('button', { name: 'Pending Approvals' })).toBeNull();
    // Non-admin sections still work.
    expect(within(navArea).getByRole('button', { name: 'Customers' })).toBeTruthy();
  });

  it('shows only the global dashboard admin destination to ps_admin', () => {
    const onNavigate = vi.fn();
    render(<Sidebar {...baseProps} onNavigate={onNavigate} is_admin={false} userRole="ps_admin" activeView="admin-global" />);
    const navArea = screen.getByRole('navigation', { name: 'Primary' });
    expect(within(navArea).getByRole('button', { name: 'Admin' })).toBeTruthy();
    expect(within(navArea).getByText('Global Admin Dashboard')).toBeTruthy();
    expect(within(navArea).queryByText('Pending Approvals')).toBeNull();
    expect(within(navArea).queryByText('All Users')).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: 'Admin' }));
    expect(onNavigate).toHaveBeenCalledWith('admin-global');
  });

  it('lights the active section icon in the collapsed rail for child views', () => {
    // Collapsed rail on a child view: the Customers icon must show its
    // active state (old behavior only matched exact/prefix ids on the
    // section, missing child views like 'customer-create').
    const onNavigate = vi.fn();
    render(
      <Sidebar {...baseProps} onNavigate={onNavigate} isCollapsed activeView="customer-create" />
    );
    const icon = screen.getByRole('button', { name: 'Customers' });
    expect(icon.style.background).toBe('var(--sidebar-selected)');
    // jsdom does not resolve var() from stylesheets, so the active color
    // assertion checks the token reference itself (the token system replaced the
    // former #6fbfc8 literal into --brand-300).
    expect(icon.style.color).toBe('var(--sidebar-accent)');
  });

  it('shows human breadcrumb labels, not title-cased ids', () => {
    render(<Sidebar {...baseProps} activeView="collab-comments" />);
    // Breadcrumb reads "Collaboration / Comments" (old behavior rendered
    // the title-cased id: "Collab Comments").
    const root = screen.getByRole('button', { name: 'Go to Collaboration' });
    const crumbRow = root.parentElement!;
    expect(crumbRow.textContent).toContain('/Comments');
    expect(crumbRow.textContent).not.toContain('Collab Comments');
  });

  it('renders the 3-level Global Intelligence tree with nested active state', () => {
    render(<Sidebar {...baseProps} activeView="collab-comments" />);
    const navArea = screen.getByRole('navigation', { name: 'Primary' });
    // Section header, nested group, leaves — all visible via expand-on-arrival.
    expect(within(navArea).getByRole('button', { name: 'Global Intelligence' })).toBeTruthy();
    expect(within(navArea).getByRole('button', { name: 'Intelligence Import' })).toBeTruthy();
    expect(within(navArea).getByRole('button', { name: 'Export' })).toBeTruthy();
    expect(within(navArea).getByRole('button', { name: 'Collaboration' })).toBeTruthy();
    expect(within(navArea).getByRole('button', { name: 'Comments' })).toBeTruthy();
    expect(within(navArea).getByRole('button', { name: 'Notifications' })).toBeTruthy();
    // Both the nested group and the outer section read active; Import does not.
    expect(within(navArea).getByRole('button', { name: 'Collaboration' }).style.fontWeight).toBe('600');
    expect(within(navArea).getByRole('button', { name: 'Global Intelligence' }).style.fontWeight).toBe('600');
    expect(within(navArea).getByRole('button', { name: 'Intelligence Import' }).style.fontWeight).toBe('400');
  });

  it('keeps export reachable and navigates section header to Intelligence Import', () => {
    const onNavigate = vi.fn();
    render(<Sidebar {...baseProps} onNavigate={onNavigate} activeView="dashboard" />);
    fireEvent.click(screen.getByRole('button', { name: 'Global Intelligence' }));
    expect(onNavigate).toHaveBeenCalledWith('gi-import');
    fireEvent.click(screen.getByRole('button', { name: 'Export' }));
    expect(onNavigate).toHaveBeenCalledWith('export');
    fireEvent.click(screen.getByRole('button', { name: 'Collaboration' }));
    expect(onNavigate).toHaveBeenCalledWith('collab-comments');
  });
});
