/**
 * CHANGELOG 0.1.0 U3 — shared customer-workspace primitives.
 *
 * Reusable presentation primitives for the redesigned Customer workspace
 * (CHANGELOG 0.1.0 directives 6-15, 33-38, 60): a real tab control with a proper
 * active state (not buttons-as-pseudo-tabs), a consistent secondary-nav
 * shape for Intelligence/Assessments/Sales (directive 50-53), an overflow
 * action menu (destructive actions live here, never as primary buttons —
 * directive 35), a semantic summary card (directive 21), and a
 * single-next-action empty state (directive 56).
 *
 * No data fetching in here — these are pure presentational components so
 * every workspace surface (header, secondary nav, intelligence cards,
 * tables) reuses the same control language instead of re-implementing it.
 * All colors come from the theme tokens; semantic use only
 * (red = destructive, amber = attention, green = healthy, accent =
 * primary action/navigation — directives 43-44).
 */
import { useEffect, useId, useRef, useState } from 'react';
import type { CSSProperties, ReactNode } from 'react';
import { createPortal } from 'react-dom';

/* ── Breadcrumbs (directive 12) ─────────────────────────────────────────── */
/** Standard breadcrumb: Dashboard / Customers / {customer}. Replaces the
 *  "Back to Dashboard" + "My Customers" button pair (directives 11-12). */
export interface Crumb {
  label: string;
  /** Click target (e.g. a navigate callback). Omitted on the last crumb. */
  onCrumbClick?: () => void;
}

export function Breadcrumbs({ crumbs, homeLabel = 'Dashboard', onHome }: { crumbs: Crumb[]; homeLabel?: string; onHome?: () => void }) {
  const all = [{ label: homeLabel, onCrumbClick: onHome }, ...crumbs];
  return (
    <nav aria-label="Breadcrumb" style={{ marginBottom: '16px' }}>
      <ol style={{ listStyle: 'none', display: 'flex', alignItems: 'center', gap: '6px', margin: 0, padding: 0, flexWrap: 'wrap' }}>
        {all.map((c, i) => {
          const last = i === all.length - 1;
          return (
            <li key={c.label + i} style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
              {c.onCrumbClick && !last ? (
                <button
                  role="link"
                  aria-label={`Navigate to ${c.label}`}
                  onClick={c.onCrumbClick}
                  style={{
                    padding: '2px 4px', margin: 0, background: 'none', border: 'none',
                    color: 'var(--brand-700)', cursor: 'pointer', fontSize: '0.85rem',
                    font: 'inherit',
                  }}
                >
                  {c.label}
                </button>
              ) : (
                <span
                  aria-current={last ? 'page' : undefined}
                  style={{ padding: '2px 4px', color: last ? 'var(--ink)' : 'var(--neutral-500)', fontSize: '0.85rem', fontWeight: last ? 600 : 400 }}
                >
                  {c.label}
                </span>
              )}
              {!last && <span aria-hidden="true" style={{ color: 'var(--neutral-500)', fontSize: '0.8rem' }}>/</span>}
            </li>
          );
        })}
      </ol>
    </nav>
  );
}

/* ── SegmentedNav (directives 14, 50) ───────────────────────────────────── */
export interface SegmentedNavItem {
  id: string;
  label: string;
  /** Optional secondary text under the label (counts, progress, etc.). */
  hint?: string;
}

interface SegmentedNavProps {
  items: SegmentedNavItem[];
  panelId?: string;
  activeId: string;
  onChange: (id: string) => void;
  /** 'primary' = the ~5-area customer navigation; 'secondary' = the
   *  Summary | Technology | Knowledge | Sales Notes style rail beneath an
   *  area. Distinct visual weight for the two levels (directive 13). */
  variant?: 'primary' | 'secondary';
  ariaLabel?: string;
}

/** A proper tab component: buttons carry `aria-current="page"` for the
 *  active item, restrained inactive styling, consistent spacing.
 *  Replaces the rounded-button pseudo-tabs. */
export function SegmentedNav({ items, activeId, onChange, variant = 'secondary', ariaLabel, panelId }: SegmentedNavProps) {
  const primary = variant === 'primary';
  const navId = useId();
  const container = useRef<HTMLDivElement>(null);
  useEffect(() => {
    container.current?.querySelector<HTMLElement>('[aria-selected="true"]')?.scrollIntoView?.({ block: 'nearest', inline: 'nearest' });
  }, [activeId]);
  return (
    <div
      ref={container}
      role="tablist"
      aria-label={ariaLabel}
      style={{
        display: 'flex', gap: 'var(--space-1)',
        flexWrap: 'nowrap',
        overflowY: 'hidden',
        overflowX: 'auto',
        scrollbarWidth: 'thin',
        borderBottom: '2px solid var(--divider)', marginBottom: primary ? 'var(--space-5)' : 'var(--space-4)',
      }}
    >
      {items.map((item) => {
        const active = item.id === activeId;
        return (
          <button
            key={item.id}
            id={`${navId}-${item.id}`}
            role="tab"
            tabIndex={active ? 0 : -1}
            aria-controls={panelId}
            onKeyDown={(event) => {
              const index = items.findIndex(candidate => candidate.id === item.id);
              const next = event.key === 'Home' ? 0 : event.key === 'End' ? items.length - 1
                : event.key === 'ArrowRight' ? (index + 1) % items.length
                : event.key === 'ArrowLeft' ? (index + items.length - 1) % items.length : null;
              if (next === null) return;
              event.preventDefault();
              onChange(items[next].id);
              container.current?.querySelectorAll<HTMLButtonElement>('[role="tab"]')[next]?.focus();
            }}
            aria-selected={active}
            aria-current={active ? 'page' : undefined}
            aria-label={`Navigate to ${item.label}`}
            onClick={() => onChange(item.id)}
            style={{
              padding: primary ? 'var(--space-3) var(--space-4)' : 'var(--space-2) var(--space-3)',
              margin: 0,
              background: 'none',
              border: 'none',
              borderRight: '2px solid transparent',
              borderRadius: 0,
              cursor: 'pointer',
              fontSize: primary ? '0.95rem' : '0.85rem',
              fontWeight: active ? 600 : 400,
              color: active ? 'var(--brand-700)' : 'var(--neutral-500)',
              borderBottom: active ? '2px solid var(--brand-500)' : '2px solid transparent',
              marginBottom: '-2px',
              transition: 'color 0.15s, border-color 0.15s',
              display: 'flex', flexDirection: 'column', alignItems: 'flex-start',
              gap: 'var(--space-1)',
              minHeight: 0,
              whiteSpace: 'nowrap',
              flexShrink: 0,
            }}
          >
            <span>{item.label}</span>
            {item.hint && (
              <span style={{ fontSize: '0.7rem', color: active ? 'var(--brand-700)' : 'var(--neutral-500)', fontWeight: 500 }}>
                {item.hint}
              </span>
            )}
          </button>
        );
      })}
    </div>
  );
}

/* ── ActionMenu (directives 33-38, 42) ──────────────────────────────────── */
export interface ActionMenuItem {
  label: string;
  onClick: () => void;
  /** Semantic tinting for destructive items (red text) — the action itself
   *  still runs its own confirmation flow (directive 35). */
  destructive?: boolean;
  disabled?: boolean;
  /** Insert a divider after this item. */
  divider?: boolean;
}

interface ActionMenuProps {
  /** Trigger button label, e.g. "+ Add" or "More". */
  label: string;
  items: ActionMenuItem[];
  variant?: 'primary' | 'ghost';
  ariaLabel?: string;
  title?: string;
  disabled?: boolean;
  align?: 'start' | 'end';
}

/** A compact secondary-action overflow menu (one primary action + a
 *  "More"/"+ Add" menu instead of a row of equal buttons). Closes on
 *  outside click and Escape. */
export function ActionMenu({ label, items, variant = 'ghost', ariaLabel, title, disabled, align = 'start' }: ActionMenuProps) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);
  const [menuPosition, setMenuPosition] = useState({ top: 0, left: 0 });

  const positionMenu = () => {
    const trigger = triggerRef.current;
    if (!trigger) return;
    // Compact mode sets `zoom: 0.85` on #root (theme.css). Modern Chrome
    // reports getBoundingClientRect in post-zoom viewport pixels (the portal
    // menu is fixed-positioned in that same space), so the raw rect is the
    // correct anchor. Legacy-Chrome pre-zoom rects were considered — the
    // real-browser pass must re-check menu placement in compact mode.
    const rect = trigger.getBoundingClientRect();
    const menuWidth = Math.max(200, menuRef.current?.offsetWidth || 0);
    const menuHeight = menuRef.current?.offsetHeight || 0;
    const preferredLeft = align === 'end' ? rect.right - menuWidth : rect.left;
    const left = Math.min(Math.max(8, preferredLeft), Math.max(8, window.innerWidth - menuWidth - 8));
    const openUpward = menuHeight > 0 && rect.bottom + 4 + menuHeight > window.innerHeight - 8;
    setMenuPosition({
      top: openUpward ? Math.max(8, rect.top - menuHeight - 4) : rect.bottom + 4,
      left,
    });
  };

  useEffect(() => {
    if (!open) return;
    positionMenu();
    const frame = window.requestAnimationFrame(() => {
      positionMenu();
      menuRef.current?.querySelector<HTMLButtonElement>('button:not(:disabled)')?.focus();
    });
    const onDown = (e: MouseEvent) => {
      const target = e.target as Node;
      if (!ref.current?.contains(target) && !menuRef.current?.contains(target)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        setOpen(false);
        triggerRef.current?.focus();
        return;
      }
      if (e.key !== 'ArrowDown' && e.key !== 'ArrowUp') return;
      const enabledItems = Array.from(menuRef.current?.querySelectorAll<HTMLButtonElement>('button:not(:disabled)') || []);
      if (!enabledItems.length) return;
      e.preventDefault();
      const current = enabledItems.indexOf(document.activeElement as HTMLButtonElement);
      const delta = e.key === 'ArrowDown' ? 1 : -1;
      enabledItems[(current + delta + enabledItems.length) % enabledItems.length].focus();
    };
    const closeOnViewportChange = () => setOpen(false);
    document.addEventListener('mousedown', onDown);
    document.addEventListener('keydown', onKey);
    window.addEventListener('resize', closeOnViewportChange);
    window.addEventListener('scroll', closeOnViewportChange, true);
    return () => {
      window.cancelAnimationFrame(frame);
      document.removeEventListener('mousedown', onDown);
      document.removeEventListener('keydown', onKey);
      window.removeEventListener('resize', closeOnViewportChange);
      window.removeEventListener('scroll', closeOnViewportChange, true);
    };
  // eslint-disable-next-line react-hooks/exhaustive-deps -- pre-existing dependency list; change only with UI verification
  }, [open, align]);

  const enabledCount = items.filter((i) => !i.disabled).length;
  const triggerDisabled = disabled || enabledCount === 0;

  return (
    <div ref={ref} style={{ position: 'relative', display: 'inline-block' }}>
      <button
        ref={triggerRef}
        role="button"
        aria-label={ariaLabel || `Open ${label} menu`}
        aria-haspopup="menu"
        aria-expanded={open}
        title={title}
        disabled={triggerDisabled}
        onClick={() => setOpen((v) => !v)}
        style={{
          padding: '8px 14px',
          background: variant === 'primary' ? (triggerDisabled ? 'var(--neutral-400)' : 'var(--brand-500)') : 'var(--neutral-0)',
          color: variant === 'primary' ? 'var(--neutral-0)' : triggerDisabled ? 'var(--neutral-500)' : 'var(--brand-500)',
          border: variant === 'primary' ? 'none' : '1px solid ' + (open ? 'var(--brand-500)' : 'var(--divider)'),
          borderRadius: 'var(--radius)',
          cursor: triggerDisabled ? 'not-allowed' : 'pointer',
          fontSize: '0.85rem',
          fontWeight: 600,
        }}
      >
        {label}
      </button>
      {open && createPortal(
        <div
          ref={menuRef}
          role="menu"
          data-align={align}
          style={{
            position: 'fixed', top: menuPosition.top, left: menuPosition.left, zIndex: 1000,
            minWidth: '200px', background: 'var(--neutral-0)', border: '1px solid var(--divider)',
            borderRadius: 'var(--radius)', boxShadow: 'var(--shadow-card)', overflow: 'hidden',
          }}
        >
          {items.map((item, i) => (
            <div key={item.label + i}>
              <button
                role="menuitem"
                disabled={item.disabled}
                onClick={() => { setOpen(false); item.onClick(); }}
                style={{
                  display: 'block', width: '100%', padding: '10px 14px', margin: 0,
                  background: 'none', border: 'none', textAlign: 'left',
                  cursor: item.disabled ? 'not-allowed' : 'pointer',
                  fontSize: '0.85rem',
                  color: item.disabled ? 'var(--neutral-500)' : item.destructive ? 'var(--status-negative)' : 'var(--neutral-700)',
                  fontWeight: item.destructive ? 600 : 400,
                }}
              >
                {item.label}
              </button>
              {item.divider && <div style={{ height: '1px', background: 'var(--divider)', margin: '2px 0' }} />}
            </div>
          ))}
        </div>,
        document.body,
      )}
    </div>
  );
}

/* ── RowActions (directive 42) ──────────────────────────────────────────── */
/** A compact per-row overflow menu for table/row-level actions (directive
 *  42): replaces the repetitive per-row Delete buttons. Destructive items
 *  are red-tinted and still run their own confirmation flow (directive 35).
 *
 *  Wrapped in a <span> that stops click/keydown propagation so a RowActions
 *  trigger inside a clickable row (role="button") does NOT also open the
 *  row — opening the menu is the only intended effect. */
export function RowActions({ ariaLabel, items }: { ariaLabel: string; items: ActionMenuItem[] }) {
  const enabledCount = items.filter((i) => !i.disabled).length;
  if (enabledCount === 0) return null;
  return (
    <span
      onClick={(e) => e.stopPropagation()}
      onKeyDown={(e) => e.stopPropagation()}
      style={{ display: 'inline-block' }}
    >
      <ActionMenu
        label="⋯"
        ariaLabel={ariaLabel}
        title="Row actions"
        items={items}
        align="end"
      />
    </span>
  );
}

/* ── SummaryCard (directives 19-21, 43) ─────────────────────────────────── */
export type SummaryTone = 'neutral' | 'positive' | 'warning' | 'negative' | 'accent';

const TONE_COLOR: Record<SummaryTone, string> = {
  neutral: 'var(--ink)',
  positive: 'var(--status-positive)',
  warning: 'var(--status-warning)',
  negative: 'var(--status-negative)',
  accent: 'var(--brand-700)',
};

interface SummaryCardProps {
  label: string;
  value: ReactNode;
  /** Supporting text beneath the value (sub-metrics, context). */
  sub?: ReactNode;
  tone?: SummaryTone;
  /** Clickable drill-down (directive 55). */
  onCardClick?: () => void;
  /** Provenance tooltip text (directive 21): derived metrics expose HOW via
   *  a tooltip instead of a "Derived — deterministic aggregation" label. */
  tooltip?: string;
  style?: CSSProperties;
}

/** A semantic summary card: label subordinate to value, tone reserved for
 *  state (not decoration), provenance via `title` tooltip. */
export function SummaryCard({ label, value, sub, tone = 'neutral', onCardClick, tooltip, style }: SummaryCardProps) {
  const content = (
    <>
      <div style={{ fontSize: '0.78rem', color: 'var(--neutral-500)', marginBottom: '6px', fontWeight: 500 }}>{label}</div>
      <div style={{ fontSize: '1.6rem', fontWeight: 700, color: TONE_COLOR[tone], lineHeight: 1.2 }}>{value}</div>
      {sub && <div style={{ fontSize: '0.8rem', color: 'var(--neutral-500)', marginTop: '6px' }}>{sub}</div>}
    </>
  );
  const baseStyle: CSSProperties = {
    background: 'var(--neutral-0)', borderRadius: 'var(--radius)', padding: '16px',
    border: '1px solid var(--divider)', textAlign: 'left',
  };
  if (onCardClick) {
    return (
      <button
        role="button"
        data-ui="summary-action"
        aria-label={`${label}: ${typeof value === 'string' || typeof value === 'number' ? value : 'details'} — open details`}
        onClick={onCardClick}
        title={tooltip}
        style={{ ...baseStyle, ...style, border: '1px solid var(--divider)', cursor: 'pointer', width: '100%', font: 'inherit' }}
      >
        {content}
        <span aria-hidden="true" style={{ display: 'block', marginTop: 12, fontSize: '1rem', color: 'var(--brand-700)' }}>→</span>
      </button>
    );
  }
  return (
    <div title={tooltip} style={{ ...baseStyle, ...style }}>
      {content}
    </div>
  );
}

/* ── EmptyState (directive 56) ───────────────────────────────────────────── */
interface EmptyStateProps {
  title: string;
  /** What is missing / why (one clear explanation, not zero-values). */
  explanation: string;
  /** The single obvious next action. */
  actionLabel?: string;
  onAction?: () => void;
  actionDisabled?: boolean;
  compact?: boolean;
}

/** Consistent empty state: explain what is missing + one next action
 *  (instead of a wall of zeros). */
export function EmptyState({ title, explanation, actionLabel, onAction, actionDisabled, compact }: EmptyStateProps) {
  return (
    <div
      style={{
        padding: compact ? '16px' : '32px',
        textAlign: 'center',
        background: 'var(--neutral-0)',
        border: '1px dashed var(--neutral-300)',
        borderRadius: 'var(--radius)',
      }}
    >
      <div style={{ fontSize: compact ? '0.9rem' : '1rem', fontWeight: 600, color: 'var(--neutral-700)', marginBottom: '6px' }}>{title}</div>
      <p style={{ margin: '0 auto', maxWidth: '420px', color: 'var(--neutral-500)', fontSize: '0.85rem', lineHeight: 1.5 }}>{explanation}</p>
      {actionLabel && onAction && (
        <button
          role="button"
          aria-label={actionLabel}
          disabled={actionDisabled}
          onClick={onAction}
          style={{
            marginTop: '14px', padding: '8px 18px',
            background: actionDisabled ? 'var(--neutral-400)' : 'var(--brand-500)',
            color: 'var(--neutral-0)', border: 'none', borderRadius: 'var(--radius)',
            cursor: actionDisabled ? 'not-allowed' : 'pointer',
            fontSize: '0.85rem', fontWeight: 600,
          }}
        >
          {actionLabel}
        </button>
      )}
    </div>
  );
}
