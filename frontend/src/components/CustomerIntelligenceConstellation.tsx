/**
 * F4 — CustomerIntelligenceConstellation: the Customer Intelligence
 * Constellation (PLAN_FEATURE_ENHANCMENTS.md), the principal analytical
 * visualization of Intelligence → Summary.
 *
 * Consumes the deterministic backend graph projection
 * (`api.getCustomerIntelligenceGraph`) and renders it on a Möbius strip via
 * `MobiusGraphCanvas` (three.js), with the surrounding affordances: legend
 * (shape + color, not color alone), domain filters, search (locate + select),
 * a selection card with deep links (the graph is an exploration/navigation
 * layer, not a CRUD interface), Reset view, sparse-state guidance, a
 * visually-hidden node list (the 3D surface is an enhancement), and
 * reduced-motion support. Pointer orbit is mouse/touch driven; Escape
 * clears the selection.
 *
 * The Customer is the selected-customer context boundary — the projection
 * is always for ONE customer; on customer change the graph + selection +
 * hover all reset. This component owns NO second copy of the graph: the
 * Overview never renders it (a lightweight Summary teaser lives elsewhere).
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { api } from '../lib/api';
import type { CustomerIntelligenceGraph as GraphType } from '../types/sail';
import {
  CATEGORY_STYLES,
  DATA_DOMAIN_ORDER,
  isSparse,
  prepareGraphData,
  searchNodes,
  filterByDomains,
  RenderGraph,
  RenderNode,
  styleFor,
} from '../lib/intelligenceGraph';
import { useReducedMotion } from '../lib/theme';
import { MOBIUS_SURFACE, mobiusColor } from '../lib/mobiusPalette';
import MobiusGraphCanvas, { MobiusCanvasHandle } from './MobiusGraphCanvas';
import ConstellationCanvasFrame from './ConstellationCanvasFrame';
import ConstellationErrorBoundary from './ConstellationErrorBoundary';

interface Props {
  customerId: number;
  customerName: string;
  /** Deep link from a node selection (entity type + id), when navigating
   *  from the constellation into an underlying customer area. */
  onNavigate?: (target: string) => void;
}

type DeepLink = { target: string; label: string };

/** Customer-area deep link per data domain (the established rail ids in
 *  CustomerDashboard). Risks and opportunities are synthesis cards — they
 *  live in Sales → Opportunities & Attention. */
const AREA_FOR_DOMAIN: Record<string, DeepLink> = {
  technology: { target: 'technology-inventory', label: 'Open in Technology Inventory' },
  use_case: { target: 'use-cases', label: 'Open in Use Cases' },
  sales_note: { target: 'sales-notes', label: 'Open in Sales Notes' },
  assessment: { target: 'assessments', label: 'Open in Assessments' },
  assessment_generic: { target: 'assessments', label: 'Open in Assessments' },
  sales_evaluation: { target: 'sales-evaluations', label: 'Open in Sales Evaluations' },
  risk: { target: 'sales-opportunities', label: 'Open in Attention' },
  opportunity: { target: 'sales-opportunities', label: 'Open in Attention' },
};

/** Where a risk/opportunity card's evidence record lives (its `evidence.source`). */
const AREA_FOR_EVIDENCE: Record<string, DeepLink & { name: string }> = {
  technology: { name: 'Technology', target: 'technology-inventory', label: 'Open evidence in Technology Inventory' },
  use_case: { name: 'Use case', target: 'use-cases', label: 'Open evidence in Use Cases' },
  sales_note: { name: 'Sales note', target: 'sales-notes', label: 'Open evidence in Sales Notes' },
  sales_notes: { name: 'Sales notes', target: 'sales-notes', label: 'Open evidence in Sales Notes' },
  sales_evaluation: { name: 'Sales evaluation', target: 'sales-evaluations', label: 'Open evidence in Sales Evaluations' },
  customer_knowledge: { name: 'Customer knowledge', target: 'customer-knowledge', label: 'Open evidence in Knowledge' },
  customer_contacts: { name: 'Contacts', target: 'contacts', label: 'Open evidence in Contacts' },
  partner_pipeline: { name: 'Partner pipeline', target: 'sales-opportunities', label: 'Open in Attention' },
};

function evidenceOf(node: RenderNode): { source?: string; source_name?: string | null } | null {
  const ev = node.metadata?.evidence;
  return ev && typeof ev === 'object' ? (ev as { source?: string; source_name?: string | null }) : null;
}

/** Map a selected node to a customer-area deep link: a record opens its
 *  area; a risk/opportunity opens the area holding its evidence record
 *  (else Opportunities & Attention); a domain hub or portion group opens
 *  its domain's area. The account itself has no link. */
export function deepLinkFor(node: RenderNode): DeepLink | null {
  if (node.metadata?.source === 'rep_deal') return { target: `deal:${node.metadata.deal_id}`, label: 'Open in Deals' };
  if (node.type === 'customer') return null;
  if (node.type === 'risk' || node.type === 'opportunity') {
    const ev = evidenceOf(node);
    const area = ev?.source ? AREA_FOR_EVIDENCE[ev.source] : undefined;
    return area ? { target: area.target, label: area.label } : AREA_FOR_DOMAIN[node.type];
  }
  if (node.type === 'domain' || node.type === 'group' || node.type === 'empty') {
    return AREA_FOR_DOMAIN[node.category] ?? null;
  }
  return AREA_FOR_DOMAIN[node.type] ?? null;
}

/** Metadata keys that are structural plumbing, not account information. */
const HIDDEN_METADATA = new Set(['group_key', 'empty', 'domain']);
const humanize = (v: string) => v.replace(/_/g, ' ');

/** Selection-card rows: readable values only — the evidence object becomes
 *  "Technology · RHEL 7" (never "[object Object]"), snake_case values read
 *  as words, other nested objects are skipped. */
export function metadataRows(node: RenderNode): Array<[string, string]> {
  const rows: Array<[string, string]> = [];
  Object.entries(node.metadata || {}).forEach(([k, v]) => {
    if (v == null || v === '' || HIDDEN_METADATA.has(k)) return;
    if (k === 'evidence') {
      const ev = evidenceOf(node);
      if (!ev?.source) return;
      const name = AREA_FOR_EVIDENCE[ev.source]?.name ?? humanize(ev.source);
      rows.push(['Evidence', ev.source_name ? `${name} · ${ev.source_name}` : name]);
      return;
    }
    if (typeof v === 'object') return;
    const text = typeof v === 'string' && /^[a-z0-9_]+$/.test(v) ? humanize(v) : String(v);
    rows.push([humanize(k), text]);
  });
  return rows;
}

/** Search-result kind: the domain's label for records, else the structure. */
function kindLabel(node: RenderNode): string {
  if (node.type === 'customer') return 'Account';
  if (node.type === 'domain') return 'Domain';
  if (node.type === 'group') return `Group in ${styleFor(node.category).label}`;
  return styleFor(node.category).label;
}

function useConstellationGraph(customerId: number) {
  const [graph, setGraph] = useState<GraphType | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    let alive = true;
    setGraph(null);
    setError(null);
    api
      .getCustomerIntelligenceGraph(customerId)
      .then((g) => { if (alive) setGraph(g); })
      .catch((e: any) => { if (alive) setError(e?.message || 'Failed to load customer intelligence'); });
    return () => { alive = false; };
  }, [customerId]);
  return { graph, error };
}

export function CustomerIntelligenceConstellation(props: Props) {
  return (
    <ConstellationErrorBoundary>
      <CustomerIntelligenceConstellationInner {...props} />
    </ConstellationErrorBoundary>
  );
}

const srOnly: React.CSSProperties = {
  position: 'absolute', width: 1, height: 1, margin: -1, padding: 0,
  overflow: 'hidden', clip: 'rect(0 0 0 0)', whiteSpace: 'nowrap', border: 0,
};

function CustomerIntelligenceConstellationInner({
  customerId,
  customerName,
  onNavigate,
}: Props) {
  // Motion comes from the OS media query (see lib/theme.ts). The 3D surface
  // is a theme-independent dark surface (the frame applies the dark-mode
  // counter-invert), so only reduced-motion is passed down.
  const reducedMotion = useReducedMotion();
  const { graph, error } = useConstellationGraph(customerId);
  const canvasRef = useRef<MobiusCanvasHandle>(null);
  const [hoveredId, setHoveredId] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [unavailable, setUnavailable] = useState(false);
  const [enabled, setEnabled] = useState<Set<string>>(
    () => new Set(DATA_DOMAIN_ORDER.map((k) => k)),
  );
  const [query, setQuery] = useState('');

  // Base renderable projection (memoized on the customer data only — the
  // scene is NOT rebuilt by hover/selection/filter UI state).
  const base = useMemo<RenderGraph | null>(
    () => (graph ? prepareGraphData(graph) : null),
    [graph],
  );
  // Visual filter over the base projection (customer + domain hubs stay;
  // entities are kept only when their domain is enabled).
  const data = useMemo<RenderGraph | null>(
    () => (base ? filterByDomains(base, enabled) : null),
    [base, enabled],
  );
  const visibleIds = useMemo(() => new Set((data?.nodes ?? []).map((n) => n.id)), [data]);
  const nodesById = useMemo(() => {
    const m = new Map<string, RenderNode>();
    (base?.nodes ?? []).forEach((n) => m.set(n.id, n));
    return m;
  }, [base]);

  // Reset transient state when the customer changes (customer-boundary rule).
  useEffect(() => {
    setHoveredId(null);
    setSelectedId(null);
    setQuery('');
    setUnavailable(false);
  }, [customerId]);

  const results = useMemo(
    () => (data ? searchNodes(data.nodes, query) : []),
    [data, query],
  );
  const selected = selectedId ? nodesById.get(selectedId) ?? null : null;
  const connectedCount = useMemo(() => {
    if (!selectedId || !data) return 0;
    const ids = new Set<string>();
    data.links.forEach((l) => {
      const s = String(l.source);
      const t = String(l.target);
      if (s === selectedId) ids.add(t);
      if (t === selectedId) ids.add(s);
    });
    return ids.size;
  }, [selectedId, data]);

  const toggleDomain = (key: string) => {
    setEnabled((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  };

  // A filtered-out node cannot stay selected.
  useEffect(() => {
    if (selectedId && !visibleIds.has(selectedId)) setSelectedId(null);
  }, [visibleIds, selectedId]);

  const onUnavailable = useCallback(() => setUnavailable(true), []);

  if (error) {
    return (
      <div role="alert" style={{ padding: '10px 14px', background: 'var(--status-negative-soft)', color: 'var(--status-negative)', borderRadius: 'var(--radius)', fontSize: '0.85rem' }}>
        {error}
      </div>
    );
  }

  if (!graph || !base || !data) {
    return (
      <div role="status" aria-live="polite" style={{ padding: '24px', textAlign: 'center', color: 'var(--neutral-500)', fontSize: '0.9rem' }}>
        Loading customer intelligence…
      </div>
    );
  }

  const sparse = isSparse(graph);
  const sel = selected;
  const selStyle = sel ? styleFor(sel.category) : null;
  const selLink = sel ? deepLinkFor(sel) : null;
  // Data records only: structural hierarchy nodes (group/empty) are not counted.
  const entityNodes = data.nodes.filter(
    (n) => n.type !== 'customer' && n.type !== 'domain' && n.type !== 'group' && n.type !== 'empty',
  );

  return (
    <div onKeyDown={(e) => { if (e.key === 'Escape') { setSelectedId(null); setHoveredId(null); } }}>
      <h2 style={{ margin: '0 0 4px 0', fontSize: '1.3rem', color: 'var(--ink)' }}>
        Customer Intelligence Network
      </h2>
      <p style={{ margin: '0 0 14px 0', color: 'var(--neutral-500)', fontSize: '0.9rem' }}>
        {customerName} — how this account's technologies, use cases, notes,
        assessments, and opportunities connect. Drag to rotate, scroll to zoom,
        hover to trace a neighborhood; click a node for details and a deep
        link. Deterministic projection of authorized S-A-I-L records (no
        fabricated nodes).
      </p>

      {/* Toolbar: search, domain filters, view controls. */}
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: '8px 14px', alignItems: 'center', marginBottom: '12px' }}>
        <div style={{ position: 'relative', minWidth: '220px', flex: '1 1 240px', maxWidth: '360px' }}>
          <input
            type="search"
            role="searchbox"
            aria-label="Search the constellation"
            placeholder="Search technologies, notes, use cases…"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            style={{ width: '100%', padding: '6px 10px', fontSize: '0.85rem', border: '1px solid var(--divider)', borderRadius: 'var(--radius)', background: 'var(--neutral-0)', color: 'var(--ink)' }}
          />
          {query && results.length > 0 && (
            <ul role="listbox" aria-label="Search results" style={{ position: 'absolute', top: '100%', left: 0, right: 0, margin: '4px 0 0', padding: '4px', listStyle: 'none', background: 'var(--neutral-0)', border: '1px solid var(--divider)', borderRadius: 'var(--radius)', boxShadow: 'var(--shadow-card)', zIndex: 10, maxHeight: '220px', overflow: 'auto' }}>
              {results.slice(0, 12).map((n) => (
                <li key={n.id} role="option" aria-selected={selectedId === n.id}>
                  <button
                    role="button"
                    onClick={() => { setSelectedId(n.id); setHoveredId(null); }}
                    style={{ width: '100%', textAlign: 'left', padding: '6px 8px', background: 'none', border: 'none', cursor: 'pointer', fontSize: '0.82rem', color: 'var(--ink)', borderRadius: '4px' }}
                  >
                    <span style={{ display: 'inline-block', width: 8, height: 8, borderRadius: 99, background: mobiusColor(n.category), marginRight: 6 }} />
                    {n.label} <span style={{ color: 'var(--neutral-500)' }}>· {kindLabel(n)}</span>
                  </button>
                </li>
              ))}
            </ul>
          )}
          {query && results.length === 0 && (
            <div style={{ position: 'absolute', top: '100%', left: 0, right: 0, margin: '4px 0 0', padding: '6px 10px', background: 'var(--neutral-0)', border: '1px solid var(--divider)', borderRadius: 'var(--radius)', fontSize: '0.8rem', color: 'var(--neutral-500)' }}>
              No matches in this customer's graph.
            </div>
          )}
        </div>

        <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px' }} role="group" aria-label="Domain filters">
          {DATA_DOMAIN_ORDER.map((k) => {
            const s = CATEGORY_STYLES[k];
            const on = enabled.has(k);
            const hex = mobiusColor(k);
            return (
              <button
                key={k}
                role="switch"
                aria-checked={on}
                onClick={() => toggleDomain(k)}
                style={{
                  display: 'inline-flex', alignItems: 'center', gap: '6px',
                  padding: '4px 10px', fontSize: '0.75rem', fontWeight: 600,
                  border: `1px solid ${on ? hex : 'var(--divider)'}`,
                  borderRadius: '999px', cursor: 'pointer',
                  background: on ? `${hex}18` : 'var(--neutral-0)',
                  color: on ? 'var(--ink)' : 'var(--neutral-500)',
                }}
              >
                <span aria-hidden style={{ display: 'inline-block', width: 8, height: 8, borderRadius: 99, background: hex }} />
                {s.label}
              </button>
            );
          })}
        </div>

        <div style={{ display: 'flex', gap: '6px' }} role="group" aria-label="View controls">
          <button role="button" aria-label="Reset view" onClick={() => canvasRef.current?.resetView()}
            style={{ padding: '4px 12px', fontSize: '0.78rem', fontWeight: 600, background: 'var(--neutral-0)', border: '1px solid var(--divider)', borderRadius: 'var(--radius)', cursor: 'pointer', color: 'var(--neutral-600)' }}>
            Reset
          </button>
          {(selectedId || hoveredId) && (
            <button role="button" aria-label="Clear focus" onClick={() => { setSelectedId(null); setHoveredId(null); }}
              style={{ padding: '4px 12px', fontSize: '0.78rem', fontWeight: 600, background: 'var(--neutral-0)', border: '1px solid var(--divider)', borderRadius: 'var(--radius)', cursor: 'pointer', color: 'var(--neutral-600)' }}>
              Clear Focus
            </button>
          )}
        </div>
      </div>

      <div>
        {/* Visualization surface: layout-driven height (aspect-ratio + floor);
            the renderer fills it and follows it via its own ResizeObserver. */}
        {unavailable ? (
          <div
            role="alert"
            style={{ border: '1px solid var(--divider)', borderRadius: 'var(--radius)', padding: '18px 20px', background: 'var(--neutral-50)', color: 'var(--neutral-700)', fontSize: '0.9rem' }}
          >
            <strong style={{ color: 'var(--ink)' }}>Visualization unavailable</strong>
            <p style={{ margin: '8px 0 0', fontSize: '0.82rem', color: 'var(--neutral-600)' }}>
              The 3D view could not start (WebGL is unavailable in this browser). The customer's
              intelligence is still listed below and in the customer areas.
            </p>
          </div>
        ) : (
          <div style={{ position: 'relative', maxWidth: 900, margin: '0 auto', aspectRatio: '3 / 2', minHeight: 280, display: 'grid' }}>
            <ConstellationCanvasFrame aria-label="Customer intelligence constellation canvas">
              <div style={{ position: 'absolute', inset: 0 }}>
                <MobiusGraphCanvas
                  ref={canvasRef}
                  graph={base}
                  visibleIds={visibleIds}
                  hoveredId={hoveredId}
                  selectedId={selectedId}
                  reducedMotion={reducedMotion}
                  onHover={setHoveredId}
                  onSelect={setSelectedId}
                  onUnavailable={onUnavailable}
                />
                <div style={{ position: 'absolute', top: 16, left: 16, pointerEvents: 'none', userSelect: 'none' }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                    <div style={{ color: MOBIUS_SURFACE.textPrimary, fontSize: 14, fontWeight: 500 }}>Customer intelligence network</div>
                    <div
                      data-testid="mobius-node-count"
                      aria-label={`${entityNodes.length} intelligence nodes`}
                      style={{ marginLeft: 4, padding: '1px 8px', borderRadius: 999, fontSize: 11, fontWeight: 600, color: MOBIUS_SURFACE.textMuted, background: 'rgba(148,163,184,0.14)', border: '1px solid rgba(148,163,184,0.20)' }}
                    >
                      {entityNodes.length} nodes
                    </div>
                  </div>
                  <div style={{ color: MOBIUS_SURFACE.textMuted, fontSize: 12, marginTop: 2 }}>Drag to rotate, scroll to zoom.</div>
                </div>
                {sel && (
                  <div
                    data-testid="mobius-selection-panel"
                    role="complementary"
                    aria-label="Selected node details"
                    style={{ position: 'absolute', top: 16, right: 16, width: 240, maxHeight: 'calc(100% - 32px)', overflow: 'auto', padding: 16, borderRadius: 12, background: MOBIUS_SURFACE.panelBg, border: `1px solid ${MOBIUS_SURFACE.panelBorder}`, backdropFilter: 'blur(6px)' }}
                  >
                    <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 8 }}>
                      <div>
                        <div style={{ fontSize: 12, color: MOBIUS_SURFACE.textMuted }}>
                          {sel.type === 'customer' ? 'Account' : sel.type === 'domain' ? 'Domain' : sel.type === 'group' ? 'Portion group' : sel.type === 'empty' ? 'Empty portion' : selStyle?.label}
                          {sel.verified === false && ' · inferred'}
                        </div>
                        <div style={{ fontSize: 14, fontWeight: 500, marginTop: 2, color: MOBIUS_SURFACE.textPrimary }}>{sel.label}</div>
                      </div>
                      <button
                        role="button"
                        aria-label="Close details"
                        onClick={() => setSelectedId(null)}
                        style={{ background: 'none', border: 'none', cursor: 'pointer', color: MOBIUS_SURFACE.textMuted, fontSize: 16, lineHeight: 1, padding: 0 }}
                      >
                        ×
                      </button>
                    </div>
                    {sel.importance != null && (
                      <div style={{ marginTop: 12 }}>
                        <div style={{ fontSize: 12, color: MOBIUS_SURFACE.textMuted, marginBottom: 4 }}>
                          Importance · {Math.round(sel.importance * 100)}%
                        </div>
                        <div style={{ height: 6, borderRadius: 99, background: 'rgba(148,163,184,0.15)' }}>
                          <div style={{ height: 6, borderRadius: 99, width: `${Math.min(100, Math.max(0, sel.importance * 100))}%`, background: sel.type === 'customer' ? MOBIUS_SURFACE.coreGlow : mobiusColor(sel.category) }} />
                        </div>
                      </div>
                    )}
                    <div style={{ fontSize: 12, marginTop: 12, color: MOBIUS_SURFACE.textMuted }}>
                      {connectedCount} connected node{connectedCount === 1 ? '' : 's'}
                    </div>
                    <dl style={{ margin: '10px 0 0', display: 'grid', gridTemplateColumns: 'auto 1fr', gap: '4px 10px', fontSize: 12 }}>
                      {metadataRows(sel).map(([k, v]) => (
                        <div key={k} style={{ display: 'contents' }}>
                          <dt style={{ color: MOBIUS_SURFACE.textMuted, textTransform: 'capitalize' }}>{k}</dt>
                          <dd style={{ margin: 0, color: MOBIUS_SURFACE.textPrimary, textAlign: 'right' }}>{v.length > 60 ? `${v.slice(0, 60)}…` : v}</dd>
                        </div>
                      ))}
                    </dl>
                    {selLink && onNavigate && (
                      <button
                        role="button"
                        onClick={() => onNavigate(selLink.target)}
                        style={{ marginTop: 14, width: '100%', padding: '8px 12px', fontSize: '0.82rem', fontWeight: 600, background: 'var(--brand-500)', color: 'var(--neutral-0)', border: 'none', borderRadius: 'var(--radius)', cursor: 'pointer' }}
                      >
                        {selLink.label}
                      </button>
                    )}
                  </div>
                )}
              </div>
            </ConstellationCanvasFrame>
          </div>
        )}

        {/* Legend: shape + color (risk/opportunity differ by shape, not color alone). */}
        <ul aria-label="Constellation legend" style={{ listStyle: 'none', display: 'flex', flexWrap: 'wrap', justifyContent: 'center', gap: '8px 14px', padding: '12px 2px 0', margin: '0 0 24px', fontSize: '0.74rem', color: 'var(--neutral-600)' }}>
          {DATA_DOMAIN_ORDER.map((k) => {
            const s = CATEGORY_STYLES[k];
            const hex = mobiusColor(k);
            return (
              <li key={k} style={{ display: 'inline-flex', alignItems: 'center', gap: '5px' }}>
                <svg width="12" height="12" viewBox="0 0 12 12" aria-hidden>
                  {s.shape === 'circle' && <circle cx="6" cy="6" r="5" fill={hex} />}
                  {s.shape === 'diamond' && <rect x="2" y="2" width="8" height="8" rx="1.5" transform="rotate(45 6 6)" fill={hex} />}
                  {s.shape === 'triangle' && <polygon points="6,1.5 11,10.5 1,10.5" fill={hex} />}
                </svg>
                {s.label}
              </li>
            );
          })}
          <li style={{ display: 'inline-flex', alignItems: 'center', gap: '5px', color: 'var(--neutral-500)' }}>
            <svg width="18" height="8" viewBox="0 0 18 8" aria-hidden><line x1="0" y1="4" x2="14" y2="4" stroke="#9ca3af" strokeWidth="1.5" /><polygon points="14,1 18,4 14,7" fill="#9ca3af" /></svg>
            directed relationship (pulse)
          </li>
        </ul>

        {/* Accessible equivalent of the 3D surface: domain counts + node list. */}
        <div style={srOnly}>
          <h3>Customer intelligence summary</h3>
          <ul aria-label="Intelligence by domain">
            {DATA_DOMAIN_ORDER.map((k) => (
              <li key={k}>
                {CATEGORY_STYLES[k].label}: {entityNodes.filter((n) => n.category === k).length}
              </li>
            ))}
          </ul>
          <ul aria-label="Intelligence nodes">
            {entityNodes.map((n) => (
              <li key={n.id}>{styleFor(n.category).label}: {n.label}</li>
            ))}
          </ul>
        </div>

        {sparse && (
          <p style={{ margin: '10px 0 0', fontSize: '0.82rem', color: 'var(--neutral-600)', background: 'var(--neutral-50)', border: '1px solid var(--divider)', borderRadius: 'var(--radius)', padding: '10px 12px' }}>
            This account has little recorded intelligence yet, so the constellation is intentionally sparse — it never invents nodes to fill space.
            Add to it from the customer areas: <button role="button" onClick={() => onNavigate?.('technology-inventory')} style={{ padding: 0, background: 'none', border: 'none', color: 'var(--brand-700)', fontWeight: 600, cursor: 'pointer', fontSize: '0.82rem' }}>Technology Inventory</button>
            {' · '}<button role="button" onClick={() => onNavigate?.('sales-notes')} style={{ padding: 0, background: 'none', border: 'none', color: 'var(--brand-700)', fontWeight: 600, cursor: 'pointer', fontSize: '0.82rem' }}>Sales Notes</button>
            {' · '}<button role="button" onClick={() => onNavigate?.('use-cases')} style={{ padding: 0, background: 'none', border: 'none', color: 'var(--brand-700)', fontWeight: 600, cursor: 'pointer', fontSize: '0.82rem' }}>Use Cases</button>.
          </p>
        )}
      </div>
    </div>
  );
}
