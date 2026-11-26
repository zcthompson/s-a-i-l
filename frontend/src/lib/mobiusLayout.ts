/**
 * Mobius layout — pure, deterministic placement of the customer
 * intelligence projection on a Möbius strip (no three.js, no React, no
 * randomness, so it unit-tests without WebGL and is stable across mounts).
 *
 * Placement:
 * - customer core: logical (u, v) = (0, 0), rendered at the CENTRE of the
 *   ring (CORE_POSITION) — the account is the hub the strip of intelligence
 *   wraps around; its domain trunks are spokes (buildSpokePoints), and it
 *   never occupies (or crowds) a slot on the strip;
 * - the 7 data domains (DATA_DOMAIN_ORDER) evenly around u, hub at v = 0
 *   (hubs never move);
 * - each domain's entities are sorted by importance (`val` desc, id asc) and
 *   sweep a wide arc of their sector (hub u ± ARC_FRACTION * DOMAIN_ANGLE / 2)
 *   over 1–4 v-lanes (LANE_V; lane count adapts to domain size). v-adjacent lanes are
 *   offset by half a step in u (brick pattern) so no two nodes share a corner,
 *   and the most important entities take the u-slots nearest the hub;
 * - a bounded deterministic relaxation pass (<= RELAX_MAX_ITERATIONS) nudges
 *   the u of still-overlapping nodes apart, clamped to their sector.
 * Entities are grouped by `category` (== their data-domain key), so a
 * domain whose hub node is absent from the projection still places its
 * entities in the right sector. Non-finite results are impossible by
 * construction; unknown categories fall back to the customer sector rather
 * than producing NaN.
 */
import type { RenderGraph, RenderNode } from './intelligenceGraph';
import { DATA_DOMAIN_ORDER } from './intelligenceGraph';

export const STRIP_RADIUS = 2.6;
export const STRIP_HALF_WIDTH = 0.78;
export const ENTITY_ROW = 0.62;
export const DOMAIN_ANGLE = (Math.PI * 2) / DATA_DOMAIN_ORDER.length;
export const NORMAL_OFFSET_NODE = 0.15;
export const NORMAL_OFFSET_LINK = 0.08;
/** Cross-domain bridges arc this far above the surface at their midpoint. */
export const NORMAL_OFFSET_LINK_CROSS = 0.16;
/** Fraction of the half-sector that entity arcs sweep. */
export const ARC_FRACTION = 0.85;
/** Entity v-lanes, in fill order (|v| stays inside the strip). */
export const LANE_V = [0.3, -0.3, 0.85, -0.85];
/** Brick offset flag per lane: v-adjacent lanes (0.4/0.8, -0.4/-0.8) differ. */
const LANE_BRICK = [0, 1, 1, 0];
export const RELAX_MAX_ITERATIONS = 30;
const RELAX_SECTOR_FRACTION = 1.0;
const RELAX_MIN_DIST_FACTOR = 1.6;
/** Nearest entity slot to a hub, in u radians. */
const HUB_CLEARANCE_U = 0.235;
/** Non-anchor entities stay at least this far (u) from their hub, so the anchor is nearest. */
const HUB_FLOOR_U = 0.245;

/** Portion-group anchors: first group sits this far (u) from its hub, then GROUP_SPREAD_U apart. */
export const GROUP_OFFSET_U = 0.26;
export const GROUP_SPREAD_U = 0.18;
/** Empty-portion ring offset (u) from its hub. */
export const EMPTY_RING_U = 0.34;

export type Vec3 = [number, number, number];

/** The customer core sits at the centre of the ring, off the strip. */
export const CORE_POSITION: Vec3 = [0, 0, 0];
/** Core -> domain spokes bow this far above the ring plane at their midpoint. */
export const SPOKE_LIFT = 0.55;

/**
 * Spoke from the core (ring centre) to a point on the strip: a quadratic
 * Bezier whose control point is the chord midpoint raised by `lift`, so the
 * eight domain spokes read as a crown above the ring rather than a flat star.
 */
export function buildSpokePoints(to: Vec3, steps = 26, lift = SPOKE_LIFT): Vec3[] {
  const [x0, y0, z0] = CORE_POSITION;
  const c: Vec3 = [(x0 + to[0]) / 2, (y0 + to[1]) / 2 + (Number.isFinite(lift) ? lift : 0), (z0 + to[2]) / 2];
  const pts: Vec3[] = [];
  for (let i = 0; i <= steps; i++) {
    const t = i / steps;
    const a = (1 - t) * (1 - t);
    const b = 2 * (1 - t) * t;
    const d = t * t;
    pts.push([a * x0 + b * c[0] + d * to[0], a * y0 + b * c[1] + d * to[1], a * z0 + b * c[2] + d * to[2]]);
  }
  return pts;
}

export function mobiusPoint(u: number, v: number): Vec3 {
  const vv = v * STRIP_HALF_WIDTH;
  const cu2 = Math.cos(u / 2);
  const su2 = Math.sin(u / 2);
  const r = STRIP_RADIUS + vv * cu2;
  return [r * Math.cos(u), vv * su2, r * Math.sin(u)];
}

export function mobiusNormal(u: number, v: number): Vec3 {
  const eps = 0.001;
  const p0 = mobiusPoint(u, v);
  const pu = mobiusPoint(u + eps, v);
  const pv = mobiusPoint(u, v + eps);
  const a: Vec3 = [pu[0] - p0[0], pu[1] - p0[1], pu[2] - p0[2]];
  const b: Vec3 = [pv[0] - p0[0], pv[1] - p0[1], pv[2] - p0[2]];
  const c: Vec3 = [
    a[1] * b[2] - a[2] * b[1],
    a[2] * b[0] - a[0] * b[2],
    a[0] * b[1] - a[1] * b[0],
  ];
  const len = Math.hypot(c[0], c[1], c[2]) || 1;
  return [c[0] / len, c[1] / len, c[2] / len];
}

/** Point on the surface pushed `offset` along the surface normal. */
export function surfacePoint(u: number, v: number, offset: number): Vec3 {
  const p = mobiusPoint(u, v);
  const n = mobiusNormal(u, v);
  return [p[0] + n[0] * offset, p[1] + n[1] * offset, p[2] + n[2] * offset];
}

export function shortestDelta(a: number, b: number): number {
  const twoPi = Math.PI * 2;
  return ((((b - a) + Math.PI) % twoPi) + twoPi) % twoPi - Math.PI;
}

/**
 * Link polyline lying on the surface (offset by the normal). `lift` is the
 * normal offset reached at the link midpoint; the endpoints always sit at
 * NORMAL_OFFSET_LINK. The default reproduces the flat on-surface curve.
 */
export function buildCurvePoints(
  a: { u: number; v: number },
  b: { u: number; v: number },
  steps = 26,
  lift = NORMAL_OFFSET_LINK,
): Vec3[] {
  const du = shortestDelta(a.u, b.u);
  const extra = Number.isFinite(lift) ? lift - NORMAL_OFFSET_LINK : 0;
  const pts: Vec3[] = [];
  for (let i = 0; i <= steps; i++) {
    const t = i / steps;
    const off = NORMAL_OFFSET_LINK + (extra === 0 ? 0 : extra * Math.sin(Math.PI * t));
    pts.push(surfacePoint(a.u + du * t, a.v + (b.v - a.v) * t, off));
  }
  return pts;
}

/** Same as buildCurvePoints with an explicit midpoint lift. */
export function buildCurvePointsLifted(
  a: { u: number; v: number },
  b: { u: number; v: number },
  steps = 26,
  lift = NORMAL_OFFSET_LINK_CROSS,
): Vec3[] {
  return buildCurvePoints(a, b, steps, lift);
}

/**
 * True when a link bridges two different domain sectors. The customer core
 * and domain-internal links (`relationshipType` starting "domain:") are not
 * cross-domain.
 */
export function isCrossDomainLink(a: MobiusNode, b: MobiusNode, relationshipType?: string): boolean {
  if (relationshipType && relationshipType.startsWith('domain:')) return false;
  if (a.node.type === 'customer' || b.node.type === 'customer') return false;
  return a.node.category !== b.node.category;
}

export interface MobiusNode {
  node: RenderNode;
  u: number;
  v: number;
  pos3: Vec3;
  /** sphere/solid radius in scene units, from the existing `val` logic. */
  radius: number;
}

export function nodeRadius(n: RenderNode): number {
  if (n.type === 'customer') return 0.34;
  if (n.type === 'domain') return 0.2;
  if (n.type === 'group') return 0.15;
  if (n.type === 'empty') return 0.1;
  const val = Number.isFinite(n.val) ? n.val : 3.5;
  return Math.min(0.2, Math.max(0.09, 0.07 + val * 0.012));
}

/** Domain sector centre (u) for a data-domain key; null if not a domain. */
export function domainU(category: string): number | null {
  const i = DATA_DOMAIN_ORDER.findIndex((k) => k === category);
  return i < 0 ? null : (i + 0.5) * DOMAIN_ANGLE;
}

export interface RelaxItem {
  u: number;
  v: number;
  radius: number;
  /** fixed items (core, hubs) never move but still repel movers. */
  fixed: boolean;
  uMin: number;
  uMax: number;
  /** optional hub exclusion: movers keep |u - centre| >= minOffset. */
  centre?: number;
  minOffset?: number;
}

function clampMover(it: RelaxItem, u: number): number {
  let out = Math.min(it.uMax, Math.max(it.uMin, u));
  if (it.centre !== undefined && it.minOffset !== undefined && Math.abs(out - it.centre) < it.minOffset) {
    // stay on the side the node is already on (it.u), outside the hub zone.
    const side = it.u >= it.centre ? 1 : -1;
    out = it.centre + side * it.minOffset;
  }
  return out;
}

/**
 * Deterministic overlap relaxation. Visits pairs in array order and nudges
 * the u of movers apart until every pair is at least
 * (rA + rB) * RELAX_MIN_DIST_FACTOR apart in scene space, or `maxIterations`
 * (capped at RELAX_MAX_ITERATIONS) is reached. Pure: returns new items.
 */
export function relaxPlacement(items: RelaxItem[], maxIterations = RELAX_MAX_ITERATIONS): RelaxItem[] {
  const out = items.map((it) => ({ ...it }));
  const pos = out.map((it) => surfacePoint(it.u, it.v, NORMAL_OFFSET_NODE));
  const iters = Math.max(0, Math.min(RELAX_MAX_ITERATIONS, Math.floor(maxIterations)));
  for (let iter = 0; iter < iters; iter++) {
    let moved = false;
    for (let i = 0; i < out.length; i++) {
      for (let j = i + 1; j < out.length; j++) {
        const A = out[i];
        const B = out[j];
        if (A.fixed && B.fixed) continue;
        const d = Math.hypot(pos[i][0] - pos[j][0], pos[i][1] - pos[j][1], pos[i][2] - pos[j][2]);
        const minD = (A.radius + B.radius) * RELAX_MIN_DIST_FACTOR;
        if (!(d < minD)) continue;
        const gap = shortestDelta(A.u, B.u);
        const dir = gap > 0 ? 1 : gap < 0 ? -1 : 1; // A is "before" B on a tie
                // Only the along-strip component can be fixed by moving u, so size the
        // shift from the horizontal separation implied by the v gap.
        const dvs = Math.abs(A.v - B.v) * STRIP_HALF_WIDTH;
        const need = Math.sqrt(Math.max(0, minD * minD - dvs * dvs)) * 1.08;
        const have = Math.sqrt(Math.max(0, d * d - dvs * dvs));
        const shift = Math.max(0, need - have) / STRIP_RADIUS + 1e-4;
        const share = A.fixed || B.fixed ? 1 : 0.5;
        if (!A.fixed) A.u = clampMover(A, A.u - dir * shift * share);
        if (!B.fixed) B.u = clampMover(B, B.u + dir * shift * share);
        pos[i] = surfacePoint(A.u, A.v, NORMAL_OFFSET_NODE);
        pos[j] = surfacePoint(B.u, B.v, NORMAL_OFFSET_NODE);
        moved = true;
      }
    }
    if (!moved) break;
  }
  return out;
}

/** u offset from its hub at which an entity on lane `v` clears the hub node. */
function hubExclusionU(v: number, radius: number): number {
  const minD = (nodeRadius({ type: 'domain' } as RenderNode) + radius) * RELAX_MIN_DIST_FACTOR;
  const dvs = Math.abs(v) * STRIP_HALF_WIDTH;
  return Math.sqrt(Math.max(0, minD * minD - dvs * dvs)) / STRIP_RADIUS;
}

function sortVal(n: RenderNode): number {
  return Number.isFinite(n.val) ? n.val : 3.5;
}

function laneCount(n: number): number {
  return n <= 2 ? 1 : n <= 4 ? 2 : n <= 6 ? 3 : 4;
}

/** Initial (u,v) for one domain's entities, in importance order. */
function placeDomain(centre: number, sorted: RenderNode[]): Map<string, { u: number; v: number }> {
  const n = sorted.length;
  const lanes = laneCount(n);
  const half = (ARC_FRACTION * DOMAIN_ANGLE) / 2;
  const perLane = Math.ceil(n / lanes);
  // Keep the nearest slot clear of the hub node, then pack outward.
  const clear = Math.min(HUB_CLEARANCE_U, half * 0.75);
  const levels = Math.ceil(perLane / 2);
  const step = (half - clear) / (levels - 0.5);
  const members: RenderNode[][] = Array.from({ length: lanes }, () => []);
  sorted.forEach((leaf, k) => members[k % lanes].push(leaf));
  const out = new Map<string, { u: number; v: number }>();
  members.forEach((lane, li) => {
    // brick: v-adjacent lanes differ by half a step (LANE_BRICK); rank 0 (most important)
    // takes the slot nearest the hub, ranks alternate sides.
    const brick = LANE_BRICK[li] * (step / 2);
    lane.forEach((leaf, r) => {
      const side = (r + li) % 2 === 0 ? -1 : 1;
      const mag = clear + Math.floor(r / 2) * step + brick;
      out.set(leaf.id, { u: centre + side * mag, v: LANE_V[li] });
    });
  });
  return out;
}

function byId(a: RenderNode, b: RenderNode): number {
  return a.id < b.id ? -1 : a.id > b.id ? 1 : 0;
}

function groupKeyOf(n: RenderNode): string | null {
  if (typeof n.groupKey === 'string' && n.groupKey) return n.groupKey;
  const md = n.metadata?.group_key;
  return typeof md === 'string' && md ? md : null;
}

export function buildMobiusLayout(graph: RenderGraph): MobiusNode[] {
  const leaves = new Map<string, RenderNode[]>();
  const groups = new Map<string, RenderNode[]>();
  const empties = new Map<string, RenderNode>();
  for (const n of graph.nodes) {
    if (n.type === 'customer' || n.type === 'domain') continue;
    if (n.type === 'group') {
      const list = groups.get(n.category) ?? [];
      list.push(n);
      groups.set(n.category, list);
      continue;
    }
    if (n.type === 'empty') {
      const cur = empties.get(n.category);
      if (!cur || byId(n, cur) < 0) empties.set(n.category, n);
      continue;
    }
    const list = leaves.get(n.category) ?? [];
    list.push(n);
    leaves.set(n.category, list);
  }
  const leafPos = new Map<string, { u: number; v: number }>();
  const leafBounds = new Map<string, [number, number]>();
  const anchors = new Set<string>();
  const structPos = new Map<string, { u: number; v: number }>();
  const groupRank = new Map<string, Map<string, number>>();
  groups.forEach((list, category) => {
    const centre = domainU(category) ?? 0;
    const sortedGroups = [...list].sort((a, b) => {
      const ka = groupKeyOf(a) ?? '';
      const kb = groupKeyOf(b) ?? '';
      return ka < kb ? -1 : ka > kb ? 1 : byId(a, b);
    });
    const ranks = new Map<string, number>();
    sortedGroups.forEach((g, i) => {
      structPos.set(g.id, { u: centre + GROUP_OFFSET_U + i * GROUP_SPREAD_U, v: 0 });
      const key = groupKeyOf(g);
      if (key !== null && !ranks.has(key)) ranks.set(key, i);
    });
    groupRank.set(category, ranks);
  });
  empties.forEach((n, category) => {
    structPos.set(n.id, { u: (domainU(category) ?? 0) + EMPTY_RING_U, v: 0 });
  });
  leaves.forEach((list, category) => {
    const centre = domainU(category) ?? 0;
    const ranks = groupRank.get(category);
    const rankOf = (n: RenderNode): number => {
      const key = groupKeyOf(n);
      const r = ranks && key !== null ? ranks.get(key) : undefined;
      return r === undefined ? Number.POSITIVE_INFINITY : r;
    };
    const sorted = [...list].sort((a, b) => {
      const ra = rankOf(a);
      const rb = rankOf(b);
      if (ra !== rb) return ra < rb ? -1 : 1; // finite ranks first; equal (incl. both unranked) falls through
      return sortVal(b) - sortVal(a) || byId(a, b);
    });
    if (sorted.length > 0) anchors.add(sorted[0].id); // most important stays put
    const bound = (RELAX_SECTOR_FRACTION * DOMAIN_ANGLE) / 2;
    placeDomain(centre, sorted).forEach((p, id) => {
      leafPos.set(id, p);
      leafBounds.set(id, [centre - bound, centre + bound]);
    });
  });

  const base = graph.nodes.map((node) => {
    let u = 0;
    let v = 0;
    if (node.type === 'customer') {
      u = 0;
    } else if (node.type === 'domain') {
      u = domainU(node.category) ?? 0;
    } else {
      const p = leafPos.get(node.id) ?? structPos.get(node.id);
      if (p) ({ u, v } = p);
    }
    return { node, u, v, radius: nodeRadius(node) };
  });

  // The core is not on the strip, so it never takes part in the strip's
  // overlap relaxation (it would otherwise pin a phantom obstacle at u = 0
  // and squeeze the two flanking sectors).
  const onStrip = base.filter((b) => b.node.type !== 'customer');
  const relaxedOnStrip = relaxPlacement(
    onStrip.map((b) => {
      const bounds = leafBounds.get(b.node.id);
      return {
        u: b.u,
        v: b.v,
        radius: b.radius,
        fixed: !bounds || anchors.has(b.node.id),
        uMin: bounds ? bounds[0] : b.u,
        uMax: bounds ? bounds[1] : b.u,
        centre: bounds ? (bounds[0] + bounds[1]) / 2 : undefined,
        minOffset: bounds ? Math.max(HUB_FLOOR_U, hubExclusionU(b.v, b.radius)) : undefined,
      };
    }),
  );

  const relaxedU = new Map(onStrip.map((b, i) => [b.node.id, relaxedOnStrip[i].u]));
  return base.map((b) => {
    if (b.node.type === 'customer') {
      return { node: b.node, u: b.u, v: b.v, pos3: [...CORE_POSITION] as Vec3, radius: b.radius };
    }
    const u = relaxedU.get(b.node.id) ?? b.u;
    return { node: b.node, u, v: b.v, pos3: surfacePoint(u, b.v, NORMAL_OFFSET_NODE), radius: b.radius };
  });
}
