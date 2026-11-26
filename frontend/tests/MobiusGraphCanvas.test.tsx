/**
 * MobiusGraphCanvas lifecycle (jsdom, three's WebGLRenderer faked — no real
 * WebGL): unavailable marker + callback, and cleanup of rAF / listeners /
 * ResizeObserver / renderer on unmount.
 */
import { describe, it, expect, vi, afterEach, beforeEach } from 'vitest';
import { render, cleanup } from '@testing-library/react';
import type { RenderGraph, RenderNode } from '../src/lib/intelligenceGraph';

const fake = vi.hoisted(() => ({ mode: 'ok' as 'ok' | 'throw', disposed: 0, renders: 0 }));

vi.mock('three', async (orig) => {
  const actual = await orig<typeof import('three')>();
  class FakeRenderer {
    domElement = document.createElement('canvas');
    constructor() {
      if (fake.mode === 'throw') throw new Error('Error creating WebGL context.');
    }
    setPixelRatio() {}
    setSize() {}
    render() { fake.renders++; }
    dispose() { fake.disposed++; }
  }
  return { ...actual, WebGLRenderer: FakeRenderer };
});

import {
  MAX_LIVE_PULSES,
  MobiusGraphCanvas,
  MOBIUS_WEBGL_MARKER,
  drawnLinkIndexes,
  emptySectorNotes,
  isNodeInferred,
  planPulseLinks,
  topEntityLabelIds,
} from '../src/components/MobiusGraphCanvas';
import { buildMobiusLayout } from '../src/lib/mobiusLayout';
import { isDirected, prepareGraphData } from '../src/lib/intelligenceGraph';

function n(id: string, type: string, category: string): RenderNode {
  return { id, type, label: id, category, entityId: 1, entityType: type, importance: 0.5, status: null, confidence: null, verified: true, metadata: {}, route: '', val: 5 } as RenderNode;
}
const graph: RenderGraph = {
  nodes: [n('c', 'customer', 'customer'), n('technology-domain', 'domain', 'technology'), n('t1', 'technology', 'technology'), n('r1', 'risk', 'risk')],
  links: [
    { id: 'a', source: 'c', target: 'technology-domain', relationship: '', relationshipType: 'domain:technology', directed: false } as any,
    { id: 'b', source: 'r1', target: 't1', relationship: '', relationshipType: 'risk_affects_technology', directed: true } as any,
  ],
};
const ids = new Set(graph.nodes.map((x) => x.id));

function props(over: Record<string, unknown> = {}) {
  return { graph, visibleIds: ids, hoveredId: null, selectedId: null, reducedMotion: false, onHover: vi.fn(), onSelect: vi.fn(), onUnavailable: vi.fn(), ...over };
}

describe('MobiusGraphCanvas', () => {
  beforeEach(() => {
    fake.mode = 'ok'; fake.disposed = 0; fake.renders = 0;
    vi.stubGlobal('ResizeObserver', class { observe = vi.fn(); disconnect = vi.fn(); });
    vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue({
      createRadialGradient: () => ({ addColorStop: vi.fn() }),
      fillRect: vi.fn(),
      fillStyle: '',
    } as any);
  });
  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it('logs the stable marker and calls onUnavailable when WebGL cannot start', () => {
    fake.mode = 'throw';
    const err = vi.spyOn(console, 'error').mockImplementation(() => {});
    const p = props();
    render(<MobiusGraphCanvas {...p} />);
    expect(MOBIUS_WEBGL_MARKER).toBe('[mobius] webgl unavailable');
    expect(err.mock.calls.some((c) => c[0] === '[mobius] webgl unavailable')).toBe(true);
    expect(p.onUnavailable).toHaveBeenCalledTimes(1);
  });

  it('exposes the canvas host test id and renders labels for every node', () => {
    const { getByTestId, container } = render(<MobiusGraphCanvas {...props()} />);
    expect(getByTestId('mobius-graph-canvas')).toBeTruthy();
    expect(container.textContent).toContain('technology-domain');
  });

  it('cancels rAF, removes listeners, disconnects the observer and disposes the renderer on unmount', () => {
    const cancel = vi.spyOn(window, 'cancelAnimationFrame');
    const removeWin = vi.spyOn(window, 'removeEventListener');
    const disconnect = vi.fn();
    vi.stubGlobal('ResizeObserver', class { observe = vi.fn(); disconnect = disconnect; });
    const { unmount } = render(<MobiusGraphCanvas {...props()} />);
    unmount();
    expect(cancel).toHaveBeenCalled();
    const removed = removeWin.mock.calls.map((c) => c[0]);
    expect(removed).toContain('pointermove');
    expect(removed).toContain('pointerup');
    expect(disconnect).toHaveBeenCalled();
    expect(fake.disposed).toBe(1);
  });

  it('reduced motion keeps rendering statically (no throw, renderer still painted)', async () => {
    const raf = vi.spyOn(window, 'requestAnimationFrame').mockImplementation(() => 1);
    render(<MobiusGraphCanvas {...props({ reducedMotion: true })} />);
    expect(raf).toHaveBeenCalled();
    expect(fake.renders).toBe(1);
  });

  it('plans directional pulses first, then deterministic ambient trunk pulses within the cap', () => {
    const links = Array.from({ length: 130 }, (_, i) => ({
      id: `trunk-${String(i).padStart(3, '0')}`,
      source: 'c',
      target: 'technology-domain',
      relationship: '',
      relationshipType: 'domain:technology',
      directed: false,
    })) as any;
    links.push({ id: 'signal-b', relationshipType: 'risk_affects_technology', directed: true });
    links.push({ id: 'signal-a', relationshipType: 'risk_affects_technology', directed: true });
    const plan = planPulseLinks(links);
    expect(plan).toHaveLength(MAX_LIVE_PULSES);
    expect(plan.slice(0, 2).map((pulse) => [pulse.id, pulse.kind])).toEqual([
      ['signal-a', 'directional'],
      ['signal-b', 'directional'],
    ]);
    expect(plan.slice(2).every((pulse) => pulse.kind === 'ambient')).toBe(true);
  });

  it('keeps only the top three resting entity labels per domain with stable tie order', () => {
    const entities = [5, 9, 9, 7].map((val, i) => ({ ...n(`t${i}`, 'technology', 'technology'), val }));
    const labelGraph = { nodes: [n('c', 'customer', 'customer'), ...entities], links: [] } as RenderGraph;
    expect([...topEntityLabelIds(buildMobiusLayout(labelGraph))]).toEqual(['t1', 't2', 't3']);
  });

  it('renders top-three resting entity labels as dark pills and leaves lower-ranked labels hidden', () => {
    vi.spyOn(window, 'requestAnimationFrame').mockImplementation(() => 1);
    const entities = [5, 9, 9, 7].map((val, i) => ({ ...n(`label-${i}`, 'technology', 'technology'), val }));
    const labelGraph = { nodes: [n('c', 'customer', 'customer'), ...entities], links: [] } as RenderGraph;
    const { getByText } = render(<MobiusGraphCanvas {...props({
      graph: labelGraph,
      visibleIds: new Set(labelGraph.nodes.map((node) => node.id)),
      reducedMotion: true,
    })} />);
    expect(getByText('label-1').style.background).toBe('rgba(5, 8, 16, 0.72)');
    expect(getByText('label-3').style.opacity).toBe('0.95');
    expect(getByText('label-0').style.opacity).toBe('0');
  });

  it('dims only explicitly inferred nodes (unknown remains normal)', () => {
    expect(isNodeInferred({ ...n('inferred', 'risk', 'risk'), verified: false })).toBe(true);
    expect(isNodeInferred({ ...n('unknown', 'risk', 'risk'), verified: null })).toBe(false);
    expect(isNodeInferred(n('verified', 'risk', 'risk'))).toBe(false);
  });
});

describe('hierarchy nodes (Section H)', () => {
  const hier: RenderGraph = {
    nodes: [
      n('c', 'customer', 'customer'),
      n('technology-domain', 'domain', 'technology'),
      { ...n('portion-technology-a', 'group', 'technology'), val: 99 } as RenderNode,
      { ...n('portion-empty-risk', 'empty', 'risk'), val: 99 } as RenderNode,
      n('t1', 'technology', 'technology'),
    ],
    links: [
      { id: 's', source: 't1', target: 'portion-technology-a', relationship: '', relationshipType: 'supports:technology', directed: false } as any,
      { id: 'p', source: 'technology-domain', target: 'portion-technology-a', relationship: '', relationshipType: 'portion:technology', directed: false } as any,
      { id: 'p2', source: 'technology-domain', target: 'portion-empty-risk', relationship: '', relationshipType: 'portion:risk', directed: false } as any,
      { id: 'd', source: 'c', target: 'technology-domain', relationship: '', relationshipType: 'domain:technology', directed: false } as any,
    ],
  };

  it('supports:/portion: links are undirected and never pulsed', () => {
    expect(isDirected('supports:technology')).toBe(false);
    expect(isDirected('portion:risk')).toBe(false);
    const prepared = prepareGraphData({ nodes: [], links: hier.links as any, limits: {} } as any);
    expect(prepared.links.every((l) => !l.directed)).toBe(true);
    expect(planPulseLinks(hier.links).map((p) => p.id)).toEqual(['d']);
  });

  it('topEntityLabelIds excludes group and empty nodes', () => {
    const ids = topEntityLabelIds(buildMobiusLayout(hier));
    expect(ids.has('t1')).toBe(true);
    expect(ids.has('portion-technology-a')).toBe(false);
    expect(ids.has('portion-empty-risk')).toBe(false);
  });

  it('shows empty ring labels at rest but not group labels', () => {
    vi.spyOn(window, 'requestAnimationFrame').mockImplementation(() => 1);
    const { getByText } = render(<MobiusGraphCanvas {...props({
      graph: hier, visibleIds: new Set(hier.nodes.map((x) => x.id)), reducedMotion: true,
    })} />);
    expect(getByText('portion-empty-risk').style.opacity).not.toBe('0');
    expect(getByText('portion-technology-a').style.opacity).toBe('0');
  });
});

describe('Möbius visual review (2026-11-01)', () => {
  beforeEach(() => {
    vi.stubGlobal('ResizeObserver', class { observe = vi.fn(); disconnect = vi.fn(); });
    vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue({
      createRadialGradient: () => ({ addColorStop: vi.fn() }), fillRect: vi.fn(), fillStyle: '',
    } as any);
  });
  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it('skips the hub trunk of an entity drawn through its portion group; keeps spokes and ungrouped trunks', () => {
    const g: RenderGraph = {
      nodes: [
        n('c', 'customer', 'customer'), n('technology-domain', 'domain', 'technology'),
        n('portion-technology-a', 'group', 'technology'),
        { ...n('t1', 'technology', 'technology'), parentId: 'portion-technology-a' } as RenderNode,
        n('t2', 'technology', 'technology'),
      ],
      links: [
        { id: '0', source: 'c', target: 'technology-domain', relationship: '', relationshipType: 'domain:technology', directed: false } as any,
        { id: '1', source: 'technology-domain', target: 't1', relationship: '', relationshipType: 'domain:technology', directed: false } as any,
        { id: '2', source: 'technology-domain', target: 't2', relationship: '', relationshipType: 'domain:technology', directed: false } as any,
        { id: '3', source: 't1', target: 'portion-technology-a', relationship: '', relationshipType: 'supports:technology', directed: false } as any,
      ],
    };
    expect([...drawnLinkIndexes(g)].sort()).toEqual([0, 2, 3]);
  });

  it('lists one empty-sector note per data domain absent from the projection', () => {
    const notes = emptySectorNotes(new Set(['technology', 'use_case', 'sales_note', 'assessment', 'sales_evaluation', 'risk', 'opportunity']));
    expect(notes.map((x) => [x.id, x.text])).toEqual([['sector-empty-assessment_generic', 'Generic Assessments · none']]);
    notes[0].pos3.forEach((c) => expect(Number.isFinite(c)).toBe(true));
  });

  it('domain hub labels carry the record count; empty sectors render their note', () => {
    vi.spyOn(window, 'requestAnimationFrame').mockImplementation(() => 1);
    const { getByText, getByTestId } = render(<MobiusGraphCanvas {...props()} />);
    expect(getByText('technology-domain').textContent).toBe('technology-domain1');
    expect(getByTestId('sector-empty-use_case').textContent).toBe('Use Cases / Initiatives · none');
  });
});
