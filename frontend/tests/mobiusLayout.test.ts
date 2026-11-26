/** Mobius layout: pure unit tests (no WebGL). */
import { describe, it, expect } from 'vitest';
import {
  DATA_DOMAIN_ORDER,
  RenderGraph,
  RenderNode,
} from '../src/lib/intelligenceGraph';
import {
  DOMAIN_ANGLE,
  EMPTY_RING_U,
  GROUP_OFFSET_U,
  GROUP_SPREAD_U,
  LANE_V,
  NORMAL_OFFSET_LINK,
  RELAX_MAX_ITERATIONS,
  Vec3,
  buildCurvePoints,
  buildCurvePointsLifted,
  buildMobiusLayout,
  isCrossDomainLink,
  relaxPlacement,
} from '../src/lib/mobiusLayout';

function node(id: string, type: string, category: string, importance: number | null = 0.5): RenderNode {
  return {
    id, type, label: id, category, entityId: 1, entityType: type, importance,
    status: null, confidence: null, verified: true, metadata: {}, route: '',
    val: importance == null ? 3.5 : 2 + importance * 10,
  } as RenderNode;
}

function synthetic(perDomain = 3): RenderGraph {
  const nodes: RenderNode[] = [node('customer-1', 'customer', 'customer', 1)];
  DATA_DOMAIN_ORDER.forEach((d) => {
    nodes.push(node(`${d}-domain`, 'domain', d, 0.6));
    for (let i = 0; i < perDomain; i++) nodes.push(node(`${d}-${i}`, d, d, i === 0 ? null : i / 10));
  });
  return { nodes, links: [] };
}

describe('buildMobiusLayout', () => {
  it('gives every node finite (u,v) and a finite 3D position', () => {
    for (const per of [0, 1, 3, 8]) {
      const layout = buildMobiusLayout(synthetic(per));
      expect(layout.length).toBe(1 + DATA_DOMAIN_ORDER.length * (1 + per));
      layout.forEach((l) => {
        expect(Number.isFinite(l.u)).toBe(true);
        expect(Number.isFinite(l.v)).toBe(true);
        l.pos3.forEach((c) => expect(Number.isFinite(c)).toBe(true));
        expect(Number.isFinite(l.radius)).toBe(true);
      });
    }
  });

  it('places the customer at the origin of (u,v) and the data domains evenly around u', () => {
    const layout = buildMobiusLayout(synthetic());
    const core = layout.find((l) => l.node.type === 'customer')!;
    expect([core.u, core.v]).toEqual([0, 0]);
    const hubs = DATA_DOMAIN_ORDER.map((d) => layout.find((l) => l.node.id === `${d}-domain`)!);
    expect(hubs.length).toBe(DATA_DOMAIN_ORDER.length);
    hubs.forEach((h, i) => {
      expect(h.v).toBe(0);
      expect(h.u).toBeCloseTo((i + 0.5) * DOMAIN_ANGLE, 10);
    });
    for (let i = 1; i < hubs.length; i++) expect(hubs[i].u - hubs[i - 1].u).toBeCloseTo(Math.PI * 2 / hubs.length, 10);
  });

  // INTENTIONAL CHANGE (0.2.14 item C): the old ±ENTITY_ROW (0.62) two-lane
  // assertion is replaced by membership in the new multi-lane set / strip.
  it('keeps entities on the v-lanes, in their domain sector, deterministically', () => {
    const g = synthetic(5);
    const a = buildMobiusLayout(g);
    const b = buildMobiusLayout(g);
    expect(b.map((l) => [l.u, l.v])).toEqual(a.map((l) => [l.u, l.v]));
    a.filter((l) => l.node.type !== 'customer' && l.node.type !== 'domain').forEach((l) => {
      expect(LANE_V.some((lv) => Math.abs(l.v - lv) < 1e-9)).toBe(true);
      expect(Math.abs(l.v)).toBeLessThanOrEqual(0.95);
      const hub = a.find((h) => h.node.id === `${l.node.category}-domain`)!;
      expect(Math.abs(l.u - hub.u)).toBeLessThan(DOMAIN_ANGLE / 2);
    });
  });

  it('adapts lane count to domain size and never shares a (u,v) corner', () => {
    const lanesFor = (per: number) => {
      const l = buildMobiusLayout(synthetic(per)).filter((x) => x.node.category === 'risk' && x.node.type === 'risk');
      return new Set(l.map((x) => x.v)).size;
    };
    expect(lanesFor(1)).toBe(1);
    expect(lanesFor(2)).toBe(1);
    expect(lanesFor(4)).toBe(2);
    expect(lanesFor(6)).toBe(3);
    expect(lanesFor(8)).toBe(4);
    const all = buildMobiusLayout(synthetic(8));
    const keys = new Set(all.map((l) => `${l.u.toFixed(6)}|${l.v.toFixed(6)}`));
    expect(keys.size).toBe(all.length);
  });

  it('sweeps a wide arc of the sector for dense domains', () => {
    const l = buildMobiusLayout(synthetic(8)).filter((x) => x.node.category === DATA_DOMAIN_ORDER[3] && x.node.type !== 'domain');
    const hubU = (3 + 0.5) * DOMAIN_ANGLE;
    const span = Math.max(...l.map((x) => x.u)) - Math.min(...l.map((x) => x.u));
    expect(span).toBeGreaterThan(0.5 * DOMAIN_ANGLE);
    expect(Math.max(...l.map((x) => Math.abs(x.u - hubU)))).toBeLessThan(DOMAIN_ANGLE / 2);
  });

  it('keeps entities at least their min distance apart after relaxation (dense)', () => {
    // 8 data domains now — synthetic(7) keeps the pre-WS5
    // per-sector entity density (the 8th domain narrows every sector).
    const layout = buildMobiusLayout(synthetic(7));
    const core = layout.find((l) => l.node.type === 'customer')!;
    const dist = (a: Vec3, b: Vec3) => Math.hypot(a[0] - b[0], a[1] - b[1], a[2] - b[2]);
    // The core and hubs are pinned, so entities in the two sectors flanking the
    // core can be squeezed between the core and a neighbour; those pairs are
    // exempt (everything else must be fully resolved).
    const squeezed = (e: (typeof layout)[number]) => dist(e.pos3, core.pos3) < (e.radius + core.radius) * 1.6 + 0.3;
    const ents = layout.filter((l) => l.node.type !== 'customer' && l.node.type !== 'domain');
    let checked = 0;
    for (let i = 0; i < ents.length; i++) {
      for (let j = i + 1; j < ents.length; j++) {
        if (squeezed(ents[i]) || squeezed(ents[j])) continue;
        checked++;
        expect(dist(ents[i].pos3, ents[j].pos3)).toBeGreaterThanOrEqual((ents[i].radius + ents[j].radius) * 1.6 - 1e-6);
      }
    }
    expect(checked).toBeGreaterThan(1000);
    // squeezed pairs still stay clearly separated (never stacked)
    for (let i = 0; i < ents.length; i++) {
      for (let j = i + 1; j < ents.length; j++) {
        expect(dist(ents[i].pos3, ents[j].pos3)).toBeGreaterThan((ents[i].radius + ents[j].radius) * 1.2);
      }
    }
  });

  it('places the most important entity nearest the hub in u', () => {
    const g = synthetic(8);
    // make one entity per domain clearly the most important
    g.nodes.forEach((n) => { if (n.id.endsWith('-5')) n.val = 20; });
    const layout = buildMobiusLayout(g);
    DATA_DOMAIN_ORDER.forEach((d) => {
      const hub = layout.find((l) => l.node.id === `${d}-domain`)!;
      const ents = layout.filter((l) => l.node.category === d && l.node.type !== 'domain');
      const top = ents.find((l) => l.node.id === `${d}-5`)!;
      const dTop = Math.abs(top.u - hub.u);
      ents.forEach((e) => expect(dTop).toBeLessThanOrEqual(Math.abs(e.u - hub.u) + 1e-9));
    });
  });

  it('relaxation is bounded, finite and stable when re-run', () => {
    const layout = buildMobiusLayout(synthetic(8));
    const items = layout.map((l) => ({
      u: l.u, v: l.v, radius: l.radius,
      fixed: l.node.type === 'customer' || l.node.type === 'domain',
      uMin: l.u - 0.05, uMax: l.u + 0.05,
    }));
    const once = relaxPlacement(items, 1000);
    const twice = relaxPlacement(once, 1000);
    once.forEach((it, i) => {
      expect(Number.isFinite(it.u)).toBe(true);
      expect(Math.abs(it.u - items[i].u)).toBeLessThanOrEqual(0.05 + 1e-12);
      expect(Math.abs(twice[i].u - it.u)).toBeLessThan(0.05);
    });
    expect(relaxPlacement(items, 1000)).toEqual(once);
    expect(RELAX_MAX_ITERATIONS).toBeLessThanOrEqual(30);
  });

  it('survives unknown categories, missing hubs, null importance and NaN val', () => {
    const g: RenderGraph = {
      nodes: [node('customer-1', 'customer', 'customer'), node('x', 'mystery', 'mystery', null), { ...node('y', 'risk', 'risk'), val: NaN }],
      links: [],
    };
    buildMobiusLayout(g).forEach((l) => {
      expect(Number.isFinite(l.u + l.v + l.radius)).toBe(true);
      l.pos3.forEach((c) => expect(Number.isFinite(c)).toBe(true));
    });
  });

  it('link curves are finite polylines across the u wrap', () => {
    const pts = buildCurvePoints({ u: 0.1, v: 0.6 }, { u: Math.PI * 2 - 0.1, v: -0.6 });
    expect(pts.length).toBe(27);
    pts.forEach((p) => p.forEach((c) => expect(Number.isFinite(c)).toBe(true)));
  });

  it('keeps the 2-arg curve identical to the default lift', () => {
    const a = { u: 0.3, v: 0.32 };
    const b = { u: 1.2, v: -0.72 };
    expect(buildCurvePoints(a, b)).toEqual(buildCurvePoints(a, b, 26, NORMAL_OFFSET_LINK));
  });

  it('lifted curves keep length and rise above the flat curve at the midpoint', () => {
    const a = { u: 0.3, v: 0.32 };
    const b = { u: 1.2, v: 0.32 };
    const flat = buildCurvePoints(a, b);
    const lifted = buildCurvePointsLifted(a, b, 26, 0.16);
    expect(lifted.length).toBe(27);
    expect(lifted[0]).toEqual(flat[0]);
    const gap = Math.hypot(...[0, 1, 2].map((k) => lifted[13][k] - flat[13][k]));
    expect(gap).toBeGreaterThan(0.05);
    lifted.forEach((p) => p.forEach((c) => expect(Number.isFinite(c)).toBe(true)));
  });

  it('detects cross-domain links', () => {
    const l = buildMobiusLayout(synthetic(2));
    const f = (id: string) => l.find((x) => x.node.id === id)!;
    const r0 = f(`${DATA_DOMAIN_ORDER[0]}-0`);
    const r1 = f(`${DATA_DOMAIN_ORDER[0]}-1`);
    const t0 = f(`${DATA_DOMAIN_ORDER[1]}-0`);
    expect(isCrossDomainLink(r0, t0)).toBe(true);
    expect(isCrossDomainLink(r0, t0, 'domain:foo')).toBe(false);
    expect(isCrossDomainLink(r0, r1)).toBe(false);
    expect(isCrossDomainLink(f('customer-1'), t0)).toBe(false);
  });
});

describe('hierarchy-aware placement (Section H)', () => {
  const tech = 'technology';
  const centre = 0.5 * DOMAIN_ANGLE;

  function grp(id: string, key: string, category = tech): RenderNode {
    return { ...node(id, 'group', category, 0.5), groupKey: key, metadata: { group_key: key } } as RenderNode;
  }
  function leaf(id: string, key: string | null, importance: number): RenderNode {
    return { ...node(id, tech, tech, importance), groupKey: key } as RenderNode;
  }
  function hier(): RenderGraph {
    return {
      nodes: [
        node('customer-1', 'customer', 'customer', 1),
        node('technology-domain', 'domain', tech, 0.6),
        grp('portion-technology-b', 'b'),
        grp('portion-technology-a', 'a'),
        leaf('t1', 'a', 0.9), leaf('t2', 'b', 0.8), leaf('t3', 'a', 0.7), leaf('t4', 'b', 0.6),
        leaf('t5', 'a', 0.5), leaf('t6', 'b', 0.4),
      ],
      links: [],
    };
  }

  it('places groups at fixed deterministic slots sorted by (groupKey, id)', () => {
    const l1 = buildMobiusLayout(hier());
    const l2 = buildMobiusLayout(hier());
    const a = l1.find((x) => x.node.id === 'portion-technology-a')!;
    const b = l1.find((x) => x.node.id === 'portion-technology-b')!;
    expect(a.u).toBeCloseTo(centre + GROUP_OFFSET_U, 10);
    expect(b.u).toBeCloseTo(centre + GROUP_OFFSET_U + GROUP_SPREAD_U, 10);
    expect(a.v).toBe(0);
    expect(a.radius).toBe(0.15);
    expect(l2.map((x) => [x.node.id, x.u, x.v])).toEqual(l1.map((x) => [x.node.id, x.u, x.v]));
  });

  it('sorts leaves group-rank first so same-group leaves take consecutive slots', () => {
    const l = buildMobiusLayout(hier());
    const plain = buildMobiusLayout({ ...hier(), nodes: hier().nodes.filter((x) => x.type !== 'group') });
    const lane = (g: typeof l, id: string) => g.find((x) => x.node.id === id)!.v;
    // 6 leaves => 3 lanes, round-robin over the sorted order.
    // grouped order: t1,t3,t5 (group a) then t2,t4,t6 (group b)
    expect(['t1', 't3', 't5', 't2', 't4', 't6'].map((id) => lane(l, id)))
      .toEqual([LANE_V[0], LANE_V[1], LANE_V[2], LANE_V[0], LANE_V[1], LANE_V[2]]);
    // without groups the order is by importance: t1,t2,t3,... so t2 sits in lane 1
    expect(lane(plain, 't2')).toBe(LANE_V[1]);
    expect(lane(l, 't2')).toBe(LANE_V[0]);
  });

  it('places the empty ring at centre + EMPTY_RING_U, v=0, radius 0.10', () => {
    const g = hier();
    g.nodes.push(node('portion-empty-risk', 'empty', 'risk', 0.1));
    const l = buildMobiusLayout(g);
    const e = l.find((x) => x.node.id === 'portion-empty-risk')!;
    // risk is the 7th entry in the (now 8-domain) DATA_DOMAIN_ORDER → index 6
    expect(e.u).toBeCloseTo(6.5 * DOMAIN_ANGLE + EMPTY_RING_U, 10);
    expect(e.v).toBe(0);
    expect(e.radius).toBe(0.1);
  });

  it('is identical to the pre-hierarchy layout when hierarchy fields are absent or inert', () => {
    const plain = synthetic(5);
    const decorated: RenderGraph = {
      ...plain,
      nodes: plain.nodes.map((n) => ({ ...n, level: 3, parentId: null, groupKey: null, empty: false } as RenderNode)),
    };
    const a = buildMobiusLayout(plain).map((x) => [x.node.id, x.u, x.v, x.radius]);
    const b = buildMobiusLayout(decorated).map((x) => [x.node.id, x.u, x.v, x.radius]);
    expect(b).toEqual(a);
  });
});

// Möbius visual review (2026-11-01): the account is the hub at the ring
// centre; its domain trunks are spokes.
import { CORE_POSITION, SPOKE_LIFT, buildSpokePoints } from '../src/lib/mobiusLayout';

describe('customer core at the ring centre', () => {
  it('renders the core at CORE_POSITION while its logical (u, v) stays (0, 0)', () => {
    const core = buildMobiusLayout(synthetic()).find((l) => l.node.type === 'customer')!;
    expect(core.pos3).toEqual(CORE_POSITION);
    expect([core.u, core.v]).toEqual([0, 0]);
  });

  it('no strip entity is placed near the core (it no longer occupies a strip slot)', () => {
    const layout = buildMobiusLayout(synthetic(7));
    const ents = layout.filter((l) => l.node.type !== 'customer');
    ents.forEach((e) => expect(Math.hypot(...e.pos3)).toBeGreaterThan(1.5));
  });

  it('spokes start at the core, end at the target and bow upward by SPOKE_LIFT / 2 at the midpoint', () => {
    const to: [number, number, number] = [2.6, 0, 0];
    const pts = buildSpokePoints(to, 20);
    expect(pts[0]).toEqual(CORE_POSITION);
    pts[20].forEach((c, i) => expect(c).toBeCloseTo(to[i], 10));
    expect(pts[10][1]).toBeCloseTo(SPOKE_LIFT / 2, 10);
    pts.forEach((p) => p.forEach((c) => expect(Number.isFinite(c)).toBe(true)));
  });
});
