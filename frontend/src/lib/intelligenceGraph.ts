/**
 * F4 — Customer Intelligence Constellation: graph data transformation +
 * centralized category styling.
 *
 * Pure, framework-agnostic helpers (no React) so they unit-test cleanly.
 * They map the deterministic backend graph projection
 * (`CustomerIntelligenceGraph` from `types/sail`) into the renderable
 * shape `react-force-graph-2d` consumes, and centralize the per-domain
 * visual language (color, size, shape) so the graph + legend + details
 * all read from ONE source of truth.
 *
 * Invariants (PLAN_FEATURE_ENHANCMENTS.md):
 * - Node identity is the backend's stable `id` (never display labels);
 * - `val` (size) encodes `importance` ONLY where a legitimate value exists
 *   (the backend sets it from criticality/score/severity) — otherwise a
 *   predictable hierarchy (customer > domain > entity);
 * - Directional pulses are only emitted for relationships with MEANINGFUL
 *   direction (dependency edges + risk-affects-tech); associations (note
 *   references, opportunity support, `associated_with`) render undirected;
 * - No node/link is invented here — the projection is consumed verbatim.
 */

import type {
  CustomerIntelligenceGraph,
  GraphLink,
  GraphNode,
} from '../types/sail';

export type CategoryKey =
  | 'customer'
  | 'domain'
  | 'technology'
  | 'use_case'
  | 'sales_note'
  | 'assessment'
  | 'assessment_generic'
  | 'sales_evaluation'
  | 'risk'
  | 'opportunity';

export interface CategoryStyle {
  key: CategoryKey;
  label: string;
  color: string;
  /** node shape: 'circle' (default) or 'diamond' / 'triangle' — risks and
   *  opportunities are distinguished by shape, not color alone. */
  shape: 'circle' | 'diamond' | 'triangle';
}

/** Centralized per-domain visual language. Colors use the S-A-I-L theme tokens
 *  where a semantic one exists; the rest are distinct categorical hues so
 *  domains never blur together (directive: "avoid colors blending together").
 *  Risk/Opportunity differ by shape (triangle/diamond) as well as color so
 *  they are distinguishable without relying on color alone. */
export const CATEGORY_STYLES: Record<CategoryKey, CategoryStyle> = {
  customer: { key: 'customer', label: 'Customer', color: 'var(--brand-700)', shape: 'circle' },
  domain: { key: 'domain', label: 'Domain', color: 'var(--neutral-500)', shape: 'circle' },
  technology: { key: 'technology', label: 'Technology', color: '#2563eb', shape: 'circle' },
  use_case: { key: 'use_case', label: 'Use Cases / Initiatives', color: '#7c3aed', shape: 'circle' },
  sales_note: { key: 'sales_note', label: 'Sales Notes', color: '#0d9488', shape: 'circle' },
  assessment: { key: 'assessment', label: 'AI Assessments', color: '#db2777', shape: 'circle' },
  // generic (non-AI) discovery rounds — their own legend
  // entry so the graph never presents them as AI assessments.
  assessment_generic: { key: 'assessment_generic', label: 'Generic Assessments', color: '#eab308', shape: 'circle' },
  sales_evaluation: { key: 'sales_evaluation', label: 'Sales Evaluations', color: '#ea580c', shape: 'circle' },
  risk: { key: 'risk', label: 'Risks / Gaps', color: '#dc2626', shape: 'triangle' },
  opportunity: { key: 'opportunity', label: 'Opportunities', color: '#16a34a', shape: 'diamond' },
};

/** Ordered domain list for the legend (customer/domain excluded — they are
 *  structural, not data domains). */
export const DATA_DOMAIN_ORDER: CategoryKey[] = [
  'technology',
  'use_case',
  'sales_note',
  'assessment',
  'assessment_generic',
  'sales_evaluation',
  'risk',
  'opportunity',
];

export function styleFor(category: string): CategoryStyle {
  const k = category as CategoryKey;
  return CATEGORY_STYLES[k] ?? CATEGORY_STYLES.domain;
}

// ── Renderable shapes ─────────────────────────────────────────────────────

export interface RenderNode extends GraphNode {
  /** force-graph size input (importance-bounded; fallback by kind). */
  val: number;
  /** runtime position (populated by the force engine; transient). */
  x?: number;
  y?: number;
  z?: number;
}

export interface RenderLink extends GraphLink {
  /** whether the relationship has meaningful direction (pulse direction). */
  directed: boolean;
}

export interface RenderGraph {
  nodes: RenderNode[];
  links: RenderLink[];
}

/** Relationship types whose direction is meaningful. `associated_with` is
 *  symmetric; the structural `domain:*` hub links are never pulsed. */
export function isDirected(relationshipType: string): boolean {
  if (relationshipType.startsWith('domain:')) return false;
  if (relationshipType.startsWith('tech_dependency:')) {
    return relationshipType !== 'tech_dependency:associated_with';
  }
  // Cross-domain: risk->technology is directional (a risk affects a tech).
  // note->technology (reference) and opportunity->use_case (support) are
  // associations without meaningful direction.
  return relationshipType === 'risk_affects_technology';
}

/** Bounded node size from a legitimate `importance` (0..1). Falls back to a
 *  predictable per-kind size when importance is absent (never fabricated). */
function nodeVal(node: GraphNode): number {
  const imp = node.importance;
  if (imp != null) return 2 + Math.max(0, Math.min(1, imp)) * 10;
  if (node.type === 'customer') return 14;
  if (node.type === 'domain') return 6;
  if (node.type === 'group') return 5;
  if (node.type === 'empty') return 3;
  return 3.5;
}

/** Map the backend projection to the renderable node/link arrays.
 *  Node ids are preserved verbatim (stable identity); link source/target are
 *  the node `id` strings (force-graph resolves them to node objects once the
 *  simulation starts, so `nodeId="id"` must be set on the component).
 *  Defensive: a malformed/empty payload (missing nodes/links) yields an
 *  empty graph rather than a crash. */
export function prepareGraphData(graph: CustomerIntelligenceGraph): RenderGraph {
  const srcNodes = Array.isArray(graph?.nodes) ? graph.nodes : [];
  const srcLinks = Array.isArray(graph?.links) ? graph.links : [];
  const nodes: RenderNode[] = srcNodes.map((n) => ({ ...n, val: nodeVal(n) }));
  const links: RenderLink[] = srcLinks.map((l) => ({
    ...l,
    directed: isDirected(l.relationshipType),
  }));
  return { nodes, links };
}

/** Nodes matching a case-insensitive search over label + key metadata.
 *  Used by the constellation search (locate a technology / note / use case). */
export function searchNodes(nodes: RenderNode[], query: string): RenderNode[] {
  const q = query.trim().toLowerCase();
  if (!q) return [];
  return nodes.filter((n) => {
    if (n.type === 'empty') return false;
    if (n.type === 'domain' || n.type === 'customer') {
      return n.label.toLowerCase().includes(q);
    }
    if (n.label.toLowerCase().includes(q)) return true;
    const md = n.metadata || {};
    return Object.values(md)
      .filter((v) => typeof v === 'string')
      .some((v) => v.toLowerCase().includes(q));
  });
}

/** Keep only nodes in the enabled domains (data domains; customer + domain
 *  hubs are always kept so the structural spine stays intact). Filtering is
 *  a VISUAL filter — the underlying projection is untouched. */
export function filterByDomains(
  data: RenderGraph,
  enabled: Set<string>,
): RenderGraph {
  const nodes = data.nodes.filter((n) => {
    const isDataEntity = n.type !== 'customer' && n.type !== 'domain';
    if (!isDataEntity) return true; // keep the structural spine
    return enabled.has(n.category);
  });
  const nodeIds = new Set(nodes.map((n) => n.id));
  const links = data.links.filter((l) => {
    const s = typeof l.source === 'string' ? l.source : (l.source as RenderNode).id;
    const t = typeof l.target === 'string' ? l.target : (l.target as RenderNode).id;
    return nodeIds.has(s) && nodeIds.has(t);
  });
  return { nodes, links };
}

/** Whether the projection is effectively "sparse" (the UI should offer
 *  guidance to add intelligence rather than a busy graph). */
export function isSparse(graph: CustomerIntelligenceGraph): boolean {
  const nodes = Array.isArray(graph?.nodes) ? graph.nodes : [];
  const dataEntities = nodes.filter(
    (n) => n.type !== 'customer' && n.type !== 'domain' && n.type !== 'group' && n.type !== 'empty',
  ).length;
  return dataEntities <= 3;
}
