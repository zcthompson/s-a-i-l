/**
 * workspace primitives + compact CustomerHeader tests.
 *
 * Covers the reusable control language for the redesigned customer
 * workspace: Breadcrumbs, SegmentedNav,
 * ActionMenu, SummaryCard,
 * EmptyState, and the compact persistent CustomerHeader
 * including the departments-as-count popover,
 * the emoji-free semantic role chip, the compact active-assessment status
 * element that replaces the full-width banner, and the + Add / More menus.
 */
import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen, fireEvent, cleanup, within } from '@testing-library/react';
import {
  Breadcrumbs, SegmentedNav, ActionMenu, SummaryCard, EmptyState,
} from '../src/components/workspacePrimitives';
import { CustomerHeader } from '../src/components/CustomerHeader';

afterEach(() => { cleanup(); });

describe('Breadcrumbs', () => {
  it('renders the Dashboard / Customers / {name} path with the last crumb current', () => {
    render(
      <Breadcrumbs
        onHome={() => {}}
        crumbs={[{ label: 'Customers', onCrumbClick: () => {} }, { label: 'Acme Manufacturing' }]}
      />,
    );
    expect(screen.getByText('Dashboard')).toBeTruthy();
    expect(screen.getByText('Customers')).toBeTruthy();
    expect(screen.getByText('Acme Manufacturing')).toBeTruthy();
    // The last crumb is the current page (not a link).
    const current = screen.getByText('Acme Manufacturing');
    expect(current.getAttribute('aria-current')).toBe('page');
  });
});

describe('SegmentedNav', () => {
  const items = [
    { id: 'summary', label: 'Summary' },
    { id: 'technology', label: 'Technology', hint: '8' },
    { id: 'knowledge', label: 'Knowledge' },
  ];

  it('marks the active tab with aria-selected and routes clicks', () => {
    const onChange = vi.fn();
    render(<SegmentedNav items={items} activeId="technology" onChange={onChange} ariaLabel="Intelligence sections" />);
    const tabs = screen.getAllByRole('tab');
    expect(tabs).toHaveLength(3);
    const techTab = tabs[1];
    expect(techTab.getAttribute('aria-selected')).toBe('true');
    expect(techTab.getAttribute('aria-current')).toBe('page');
    expect(within(techTab).getByText('8')).toBeTruthy(); // hint
    fireEvent.click(tabs[2]);
    expect(onChange).toHaveBeenCalledWith('knowledge');
  });
});

describe('ActionMenu', () => {
  it('opens on trigger click and runs items, closing after', () => {
    const onEdit = vi.fn();
    const onRemove = vi.fn();
    render(
      <ActionMenu
        label="More"
        ariaLabel="Customer settings"
        items={[
          { label: 'Team', onClick: () => {} },
          { label: 'Edit Customer', onClick: onEdit, divider: true },
          { label: 'Remove Customer', onClick: onRemove, destructive: true },
        ]}
      />,
    );
    // Menu is closed initially.
    expect(screen.queryByRole('menu')).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: 'Customer settings' }));
    expect(screen.getByRole('menu')).toBeTruthy();
    fireEvent.click(screen.getByRole('menuitem', { name: 'Edit Customer' }));
    expect(onEdit).toHaveBeenCalled();
    // Menu closed after the click.
    expect(screen.queryByRole('menu')).toBeNull();
    // Re-open and fire the destructive item.
    fireEvent.click(screen.getByRole('button', { name: 'Customer settings' }));
    fireEvent.click(screen.getByRole('menuitem', { name: 'Remove Customer' }));
    expect(onRemove).toHaveBeenCalled();
  });

  it('is disabled when every item is disabled', () => {
    render(
      <ActionMenu
        label="+ Add"
        ariaLabel="Add to customer"
        items={[{ label: 'Use Case', onClick: () => {}, disabled: true }]}
      />,
    );
    expect(screen.getByRole('button', { name: 'Add to customer' }).hasAttribute('disabled')).toBe(true);
  });

  it('closes on Escape', () => {
    render(
      <ActionMenu label="More" ariaLabel="Customer settings" items={[{ label: 'Team', onClick: () => {} }]} />,
    );
    fireEvent.click(screen.getByRole('button', { name: 'Customer settings' }));
    expect(screen.getByRole('menu')).toBeTruthy();
    fireEvent.keyDown(document, { key: 'Escape' });
    expect(screen.queryByRole('menu')).toBeNull();
  });

  it('portals an end-aligned menu and keeps it inside the viewport', () => {
    const originalRect = HTMLElement.prototype.getBoundingClientRect;
    HTMLElement.prototype.getBoundingClientRect = () => ({
      x: 960, y: 20, top: 20, left: 960, right: 1010, bottom: 50, width: 50, height: 30,
      toJSON: () => ({}),
    } as DOMRect);
    Object.defineProperty(window, 'innerWidth', { configurable: true, value: 1024 });
    render(<ActionMenu label="More" align="end" items={[{ label: 'Team', onClick: () => {} }]} />);
    fireEvent.click(screen.getByRole('button', { name: 'Open More menu' }));
    const menu = screen.getByRole('menu');
    expect(menu.parentElement).toBe(document.body);
    expect(menu.getAttribute('data-align')).toBe('end');
    expect(Number.parseFloat(menu.style.left)).toBeLessThanOrEqual(816);
    HTMLElement.prototype.getBoundingClientRect = originalRect;
  });
});

describe('SummaryCard', () => {
  it('renders label + value + sub, and is a button when clickable', () => {
    const onClick = vi.fn();
    const { rerender } = render(
      <SummaryCard label="Business Impact" value="$5,450,000" sub="Savings $4.7M · Revenue $0.75M" tone="accent" tooltip="Deterministic aggregation" onCardClick={onClick} />,
    );
    const card = screen.getByRole('button', { name: /Business Impact/ });
    expect(card.getAttribute('title')).toBe('Deterministic aggregation');
    expect(within(card).getByText('$5,450,000')).toBeTruthy();
    expect(within(card).getByText('Savings $4.7M · Revenue $0.75M')).toBeTruthy();
    fireEvent.click(card);
    expect(onClick).toHaveBeenCalled();
    rerender(<SummaryCard label="Static" value={42} />);
    expect(screen.queryByRole('button')).toBeNull();
  });
});

describe('EmptyState', () => {
  it('explains what is missing and offers one next action', () => {
    const onAdd = vi.fn();
    render(
      <EmptyState
        title="No technology inventory yet"
        explanation="Run a discovery session to capture this customer's technology estate."
        actionLabel="Add Technology"
        onAction={onAdd}
      />,
    );
    expect(screen.getByText('No technology inventory yet')).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: 'Add Technology' }));
    expect(onAdd).toHaveBeenCalled();
  });
});

describe('CustomerHeader', () => {
  const base = {
    name: 'Acme Manufacturing',
    description: 'Mid-size discrete manufacturer refreshing its VMware estate.',
    vertical: 'Manufacturing',
    branch: 'BR20 - Sample Branch E',
    primaryRep: 'Jane Doe',
    managerName: 'Manager McMan',
    insideSales: ['Sam Inside', 'Lee Inside'],
    userRole: 'owner',
    canManageCustomer: true,
    canAddUseCase: true,
  };

  it('renders the primary title, vertical, description, and the sales-portfolio line (branch / primary rep / manager / inside sales — no use-case or department counts)', () => {
    render(<CustomerHeader {...base} />);
    const h1 = screen.getByRole('heading', { level: 1, name: 'Acme Manufacturing' });
    expect(h1).toBeTruthy();
    expect(screen.getByText('Manufacturing')).toBeTruthy();
    expect(screen.getByText('Mid-size discrete manufacturer refreshing its VMware estate.')).toBeTruthy();
    expect(screen.getByText('BR20 - Sample Branch E')).toBeTruthy();
    expect(screen.getByText('Primary rep:')).toBeTruthy();
    expect(screen.getByText('Jane Doe')).toBeTruthy();
    expect(screen.getByText('Manager:')).toBeTruthy();
    expect(screen.getByText('Manager McMan')).toBeTruthy();
    expect(screen.getByText(/Sam Inside · Lee Inside/)).toBeTruthy();
    // The customer panel no longer carries use-case or department counts.
    expect(screen.queryByText(/use cases/i)).toBeNull();
    expect(screen.queryByText(/departments/i)).toBeNull();
  });

  it('omits the whole sales-portfolio line when no branch/rep/manager/inside-sales is set', () => {
    render(<CustomerHeader {...base} branch={null} primaryRep={null} managerName={null} insideSales={[]} />);
    expect(screen.queryByText('Primary rep:')).toBeNull();
    expect(screen.queryByText('Manager:')).toBeNull();
    // role chip + assessment status still render
    expect(screen.getByText('You: Owner')).toBeTruthy();
  });

  it('renders a clean role chip (no emoji) and a compact active-assessment status', () => {
    render(
      <CustomerHeader
        {...base}
        userRole="member"
        activeRound={{ name: 'Assessment 1', total: 14, scored: 5 }}
        onManageRounds={() => {}}
      />,
    );
    expect(screen.getByText('You: Member')).toBeTruthy();
    // The compact status element (replaces the full-width banner).
    expect(screen.getByText(/Active assessment:/)).toBeTruthy();
    // scored/total is split across text nodes (scored + "/" + total) — match
    // the whole line instead of a substring.
    expect(screen.getByText(/5\/14 AI use cases scored/)).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: 'Manage assessment rounds' }));
  });

  it('exposes + Add items routed by target (Use Case / Technology / ...)', () => {
    const onAdd = vi.fn();
    render(<CustomerHeader {...base} onAdd={onAdd} />);
    fireEvent.click(screen.getByRole('button', { name: 'Add to customer' }));
    const menu = screen.getByRole('menu');
    fireEvent.click(within(menu).getByRole('menuitem', { name: 'Technology' }));
    expect(onAdd).toHaveBeenCalledWith('technology');
    // Re-open and pick a different target.
    fireEvent.click(screen.getByRole('button', { name: 'Add to customer' }));
    fireEvent.click(within(screen.getByRole('menu')).getByRole('menuitem', { name: 'Sales Note' }));
    expect(onAdd).toHaveBeenCalledWith('sales-note');
  });

  it('hides destructive administration from the overflow menu for non-managers (role-gated)', () => {
    const onSettings = vi.fn();
    render(<CustomerHeader {...base} userRole="member" canManageCustomer={false} onOpenSettings={onSettings} />);
    // The More menu still exists (Team is visible to everyone) but the
    // destructive/management entries are gated by role.
    fireEvent.click(screen.getByRole('button', { name: 'Customer settings' }));
    const menu = screen.getByRole('menu');
    expect(within(menu).queryByRole('menuitem', { name: 'Remove Customer' })).toBeNull();
    expect(within(menu).queryByRole('menuitem', { name: 'Edit Customer' })).toBeNull();
    expect(within(menu).getByRole('menuitem', { name: 'Team' })).toBeTruthy();
  });

  it('surfaces Edit / Departments / Remove for managers via the settings menu', () => {
    const onSettings = vi.fn();
    render(<CustomerHeader {...base} onOpenSettings={onSettings} />);
    fireEvent.click(screen.getByRole('button', { name: 'Customer settings' }));
    const menu = screen.getByRole('menu');
    fireEvent.click(within(menu).getByRole('menuitem', { name: 'Remove Customer' }));
    expect(onSettings).toHaveBeenCalledWith('remove');
  });
});

describe('SegmentedNav keyboard access', () => {
  it('moves focus and selection with arrows, Home and End, wrapping at the edges', () => {
    const change = vi.fn();
    render(<SegmentedNav items={[{ id: 'a', label: 'Overview' }, { id: 'b', label: 'Sales' }, { id: 'c', label: 'Discovery & Value' }]} activeId="a" onChange={change} panelId="account-panel" />);
    const tabs = screen.getAllByRole('tab');
    expect(tabs.map(tab => tab.tabIndex)).toEqual([0, -1, -1]);
    expect(tabs[0].getAttribute('aria-controls')).toBe('account-panel');
    fireEvent.keyDown(tabs[0], { key: 'ArrowLeft' });
    expect(change).toHaveBeenLastCalledWith('c');
    expect(document.activeElement).toBe(tabs[2]);
    fireEvent.keyDown(tabs[2], { key: 'Home' });
    expect(document.activeElement).toBe(tabs[0]);
    fireEvent.keyDown(tabs[0], { key: 'End' });
    expect(document.activeElement).toBe(tabs[2]);
    fireEvent.keyDown(tabs[2], { key: 'ArrowRight' });
    expect(change).toHaveBeenLastCalledWith('a');
  });
});

it('describes generic discovery progress without an AI scoring requirement', () => {
  render(<CustomerHeader name="Discovery customer" userRole="owner" canManageCustomer canAddUseCase activeRound={{ name: 'Discovery', generic: true, total: 4, scored: 0, completed: 2 }} />);
  expect(screen.getByText(/2\/4 use cases completed/)).toBeTruthy();
  expect(screen.queryByText(/0\/4.*scored/)).toBeNull();
});

it('shows only permitted CRM quick actions as enabled', () => {
  render(<CustomerHeader name="Scoped customer" userRole="member" canManageCustomer={false} canAddUseCase createPermissions={{ contact: true, task: false, deal: false, activity: false }} onAdd={vi.fn()} />);
  fireEvent.click(screen.getByLabelText('Add to customer'));
  expect((screen.getByRole('menuitem', { name: 'Contact' }) as HTMLButtonElement).disabled).toBe(false);
  expect((screen.getByRole('menuitem', { name: 'Task' }) as HTMLButtonElement).disabled).toBe(true);
});
