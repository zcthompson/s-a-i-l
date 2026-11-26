/**
 * Customer Intelligence Constellation tests (Mobius 3D renderer).
 *
 * Covers:
 * - the pure graph transformation helpers (lib/intelligenceGraph);
 * - the ConstellationCanvasFrame (theme-independent surface);
 * - the CustomerIntelligenceConstellation component with api mocked and the
 *   three.js canvas stubbed (jsdom has no WebGL): loading, legend + domain
 *   filter chips, sparse guidance, selection panel + deep link, search,
 *   Escape-to-clear, accessible node list, WebGL-unavailable card + marker.
 *
 * Removed with the force-graph renderer (react-force-graph-2d): the
 * 2D star-field/palette tests (constellationStars/constellationPalette were
 * deleted — covered now by mobiusPalette.test.ts) and the "measured tile
 * width reaches the renderer" test (the three.js canvas owns its own
 * ResizeObserver; no width/height props exist any more).
 */
import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen, cleanup, fireEvent, waitFor } from '@testing-library/react';
import {
  CATEGORY_STYLES,
  prepareGraphData,
  filterByDomains,
  searchNodes,
  isSparse,
} from '../src/lib/intelligenceGraph';
import { ConstellationCanvasFrame } from '../src/components/ConstellationCanvasFrame';
import type { CustomerIntelligenceGraph } from '../src/types/sail';

// ── Fixtures ─────────────────────────────────────────────────────────────

function graphFixture(): CustomerIntelligenceGraph {
  return {
    customer_id: 1,
    generated_at: '2026-09-10T00:00:00Z',
    method: 'deterministic_graph_projection',
    customer_label: 'Acme Manufacturing',
    nodes: [
      { id: 'customer-1', type: 'customer', label: 'Acme Manufacturing', category: 'customer', entityId: 1, entityType: 'customer', importance: 1, status: null, confidence: null, verified: true, metadata: {}, route: '' },
      { id: 'technology-domain', type: 'domain', label: 'Technology', category: 'technology', entityId: 1, entityType: 'domain', importance: 0.6, status: null, confidence: null, verified: true, metadata: { domain: 'technology' }, route: '' },
      { id: 'technology-10', type: 'technology', label: 'VMware vSphere 6.5', category: 'technology', entityId: 10, entityType: 'technology', importance: 0.9, status: 'no_support', confidence: 1, verified: true, metadata: { vendor: 'VMware', category: 'virtualization', business_criticality: 'critical', lifecycle_state: 'eol' }, route: '' },
      { id: 'technology-11', type: 'technology', label: 'Cisco UCS C240', category: 'technology', entityId: 11, entityType: 'technology', importance: 0.7, status: null, confidence: 1, verified: true, metadata: { vendor: 'Cisco', category: 'hardware' }, route: '' },
      { id: 'sales_note-3', type: 'sales_note', label: 'Discovery call', category: 'sales_note', entityId: 3, entityType: 'sales_note', importance: 0.5, status: null, confidence: null, verified: true, metadata: { excerpt: 'Discussed vSphere renewal', note_date: '2026-09-01', author: 'Dana' }, route: '' },
      { id: 'risk-0', type: 'risk', label: 'vSphere EOL exposure', category: 'risk', entityId: 0, entityType: 'risk', importance: 0.8, status: null, confidence: null, verified: true, metadata: { severity: 'high' }, route: '' },
      { id: 'opportunity-0', type: 'opportunity', label: 'Renewal upsell', category: 'opportunity', entityId: 0, entityType: 'opportunity', importance: 0.6, status: null, confidence: null, verified: true, metadata: { type: 'growth_opportunity' }, route: '' },
    ],
    links: [
      { id: 'customer-1|technology-domain|domain:technology', source: 'customer-1', target: 'technology-domain', relationship: 'technology', relationshipType: 'domain:technology', strength: null, verified: true, confidence: null, provenance: 'graph structure' },
      { id: 'technology-domain|technology-10|domain:technology', source: 'technology-domain', target: 'technology-10', relationship: 'technology', relationshipType: 'domain:technology', strength: null, verified: true, confidence: null, provenance: 'graph structure' },
      { id: 'technology-domain|technology-11|domain:technology', source: 'technology-domain', target: 'technology-11', relationship: 'technology', relationshipType: 'domain:technology', strength: null, verified: true, confidence: null, provenance: 'graph structure' },
      { id: 'technology-10|technology-11|tech_dependency:runs_on', source: 'technology-10', target: 'technology-11', relationship: 'VMware vSphere 6.5 runs_on Cisco UCS C240', relationshipType: 'tech_dependency:runs_on', strength: 1, verified: true, confidence: null, provenance: 'technology dependency' },
      { id: 'sales_note-3|technology-10|note_references_technology', source: 'sales_note-3', target: 'technology-10', relationship: 'Discovery call references VMware vSphere 6.5', relationshipType: 'note_references_technology', strength: null, verified: true, confidence: null, provenance: 'sales note junction' },
      { id: 'risk-0|technology-10|risk_affects_technology', source: 'risk-0', target: 'technology-10', relationship: 'vSphere EOL exposure affects VMware vSphere 6.5', relationshipType: 'risk_affects_technology', strength: null, verified: true, confidence: null, provenance: 'opportunity synthesis' },
      { id: 'opportunity-0|technology-10|opportunity_supported_by_use_case', source: 'opportunity-0', target: 'technology-10', relationship: 'Renewal upsell supported by VMware vSphere 6.5', relationshipType: 'opportunity_supported_by_use_case', strength: null, verified: true, confidence: null, provenance: 'opportunity synthesis' },
    ],
    limits: { max_per_domain: 8, technology_total: 2, technology_shown: 2, use_case_total: 0, use_case_shown: 0, sales_note_total: 1, sales_note_shown: 1, dependencies_total: 1, dependencies_shown: 1, opportunities_total: 2 },
  };
}

function sparseFixture(): CustomerIntelligenceGraph {
  const g = graphFixture();
  return {
    ...g,
    nodes: [g.nodes[0], g.nodes[1], g.nodes[2], g.nodes[5]],
    links: [g.links[0], g.links[2], g.links[5]],
    limits: { ...g.limits, opportunities_total: 1 },
  };
}

// ── Pure transform tests ─────────────────────────────────────────────────

describe('intelligenceGraph transforms', () => {
  it('prepareGraphData preserves stable node ids and link ids verbatim', () => {
    const g = graphFixture();
    const data = prepareGraphData(g);
    expect(data.nodes.map((n) => n.id)).toEqual(g.nodes.map((n) => n.id));
    expect(data.links.map((l) => l.id)).toEqual(g.links.map((l) => l.id));
    // Node sizes come from legitimate importance values (bounded).
    const vsphere = data.nodes.find((n) => n.id === 'technology-10')!;
    expect(vsphere.val).toBeGreaterThanOrEqual(2);
    expect(vsphere.val).toBeLessThanOrEqual(12);
  });

  it('classifies direction: dependencies + risk→tech are directed; associations + hub links are not', () => {
    const data = prepareGraphData(graphFixture());
    const byType = (rt: string) => data.links.filter((l) => l.relationshipType === rt);
    expect(byType('tech_dependency:runs_on')[0].directed).toBe(true);
    expect(byType('risk_affects_technology')[0].directed).toBe(true);
    expect(byType('note_references_technology')[0].directed).toBe(false);
    expect(byType('opportunity_supported_by_use_case')[0].directed).toBe(false);
    expect(byType('domain:technology')[0].directed).toBe(false);
  });

  it('treats tech_dependency:associated_with as undirected (symmetric)', () => {
    const g = graphFixture();
    g.links.push({
      id: 'technology-10|technology-11|tech_dependency:associated_with',
      source: 'technology-10',
      target: 'technology-11',
      relationship: 'a associates b',
      relationshipType: 'tech_dependency:associated_with',
      strength: null,
      verified: true,
      confidence: null,
      provenance: 'technology dependency',
    });
    const data = prepareGraphData(g);
    expect(data.links.find((l) => l.relationshipType === 'tech_dependency:associated_with')!.directed).toBe(false);
  });

  it('filterByDomains removes disabled-domain entities + their links but keeps the spine', () => {
    const data = prepareGraphData(graphFixture());
    const filtered = filterByDomains(data, new Set(['technology']));
    const types = new Set(filtered.nodes.map((n) => n.type));
    expect(types.has('customer')).toBe(true);
    expect(types.has('domain')).toBe(true); // spine stays
    expect(types.has('technology')).toBe(true);
    expect(types.has('sales_note')).toBe(false);
    expect(types.has('risk')).toBe(false);
    // The note→tech link has a dead endpoint and is dropped.
    expect(filtered.links.every((l) => !l.id.includes('sales_note-3'))).toBe(true);
    // The tech↔tech dependency link survives (both endpoints kept).
    expect(filtered.links.some((l) => l.id === 'technology-10|technology-11|tech_dependency:runs_on')).toBe(true);
  });

  it('searchNodes matches labels and string metadata case-insensitively, skipping the spine', () => {
    const data = prepareGraphData(graphFixture());
    // 'cisco ucs' matches ONLY the UCS node (label + vendor metadata).
    expect(searchNodes(data.nodes, 'Cisco UCS').map((n) => n.id)).toEqual(['technology-11']);
    // Author metadata is searchable too.
    expect(searchNodes(data.nodes, 'dana').map((n) => n.id)).toEqual(['sales_note-3']);
    // "vsphere" legitimately matches every node that mentions it — the
    // search never fabricates, it finds every real reference.
    expect(searchNodes(data.nodes, 'vsphere').length).toBeGreaterThanOrEqual(2);
    expect(searchNodes(data.nodes, '  ').length).toBe(0);
    expect(searchNodes(data.nodes, 'zzzz-no-such-thing').length).toBe(0);
  });

  it('isSparse flags ≤3 data entities and does not flag the rich fixture', () => {
    expect(isSparse(sparseFixture())).toBe(true);
    expect(isSparse(graphFixture())).toBe(false);
  });

  it('risk and opportunity are distinguished by shape, not color alone', () => {
    const r = CATEGORY_STYLES.risk;
    const o = CATEGORY_STYLES.opportunity;
    expect(r.shape).not.toBe(o.shape);
    expect(r.color).not.toBe(o.color);
    expect(CATEGORY_STYLES.technology.shape).toBe('circle');
  });
});

function hierarchyFixture(): CustomerIntelligenceGraph {
  const g = graphFixture();
  const base = { entityId: 0, importance: 0.5, status: null, confidence: null, verified: true, route: '' };
  g.nodes.push(
    { ...base, id: 'portion-technology-cloud', type: 'group', label: 'Cloud Platform', category: 'technology', entityType: 'group', metadata: { member_count: 2, group_key: 'cloud' }, level: 2, parentId: 'technology-domain', groupKey: 'cloud', empty: false },
    { ...base, id: 'portion-empty-use_case', type: 'empty', label: 'No use case shown', category: 'use_case', entityType: 'empty', metadata: { empty: true }, level: 2, parentId: 'use_case-domain', groupKey: null, empty: true },
  );
  return g;
}

describe('hierarchy nodes in transforms (Section H)', () => {
  it('prepareGraphData passes level/parentId/groupKey/empty through verbatim and sizes group/empty', () => {
    const data = prepareGraphData(hierarchyFixture());
    const grp = data.nodes.find((n) => n.type === 'group')!;
    expect(grp.level).toBe(2);
    expect(grp.parentId).toBe('technology-domain');
    expect(grp.groupKey).toBe('cloud');
    expect(grp.val).toBe(7); // 2 + 0.5 * 10
    expect(data.nodes.find((n) => n.type === 'empty')!.empty).toBe(true);
  });

  it('isSparse ignores group/empty; searchNodes skips empty but finds groups', () => {
    const sparse = sparseFixture();
    sparse.nodes.push(...hierarchyFixture().nodes.filter((n) => n.type === 'group' || n.type === 'empty'));
    expect(isSparse(sparse)).toBe(true);
    const data = prepareGraphData(hierarchyFixture());
    expect(searchNodes(data.nodes, 'no use case').length).toBe(0);
    expect(searchNodes(data.nodes, 'cloud platform').map((n) => n.id)).toEqual(['portion-technology-cloud']);
  });
});

describe('ConstellationCanvasFrame', () => {
  it('the frame is theme-independent black: no filter in either theme (dark uses tokens, not inversion)', async () => {
    const { container } = render(
      <ConstellationCanvasFrame aria-label="test canvas">
        <div data-testid="frame-child" />
      </ConstellationCanvasFrame>,
    );
    const frame = container.querySelector('[aria-label="test canvas"]') as HTMLElement;
    expect(frame).toBeTruthy();
    // Light mode: the black-surface palette is drawn as-is — no filter.
    expect(frame.style.filter).toBe('');
    expect(frame.querySelector('[data-testid="frame-child"]')).toBeTruthy();

    // Dark theme swaps tokens only; the black canvas must not be inverted.
    document.documentElement.setAttribute('data-theme', 'dark');
    await new Promise(resolve => setTimeout(resolve, 0));
    expect(frame.style.filter).toBe('');
    document.documentElement.removeAttribute('data-theme');
  });
});

// ── Component tests (api + canvas stubbed) ───────────────────────────────
// ── Component tests (api + canvas stubbed) ───────────────────────────────

const { apiMock, canvasProps } = vi.hoisted(() => ({
  apiMock: { getCustomerIntelligenceGraph: vi.fn() },
  canvasProps: { current: null as any },
}));

vi.mock('../src/lib/api', () => ({ api: apiMock }));
vi.mock('../src/components/MobiusGraphCanvas', () => ({
  default: (props: any) => {
    canvasProps.current = props;
    return <div data-testid="mobius-graph-canvas" />;
  },
}));

import { CustomerIntelligenceConstellation } from '../src/components/CustomerIntelligenceConstellation';
import { act } from '@testing-library/react';

function mount(name = 'Acme', onNavigate = vi.fn()) {
  render(<CustomerIntelligenceConstellation customerId={1} customerName={name} onNavigate={onNavigate} />);
  return onNavigate;
}

describe('CustomerIntelligenceConstellation (Mobius component)', () => {
  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
    canvasProps.current = null;
  });

  it('shows a loading state before the projection arrives', async () => {
    apiMock.getCustomerIntelligenceGraph.mockReturnValue(new Promise(() => {}));
    mount();
    expect(screen.getByRole('status')).toBeTruthy();
  });

  it('renders the legend, domain filters, reset control, and the canvas', async () => {
    apiMock.getCustomerIntelligenceGraph.mockResolvedValue(graphFixture());
    mount();
    await waitFor(() => expect(screen.getByTestId('mobius-graph-canvas')).toBeTruthy());
    expect(screen.getByText('Customer Intelligence Network')).toBeTruthy();
    const legend = screen.getByLabelText('Constellation legend');
    expect(legend.textContent).toContain('Technology');
    expect(legend.textContent).toContain('Risks / Gaps');
    expect(legend.textContent).toContain('Opportunities');
    const switches = screen.getAllByRole('switch');
    expect(switches.length).toBe(8);
    expect(switches.every((s) => s.getAttribute('aria-checked') === 'true')).toBe(true);
    expect(screen.getByRole('button', { name: 'Reset view' })).toBeTruthy();
    expect(screen.getByText('directed relationship (pulse)')).toBeTruthy();
    expect(screen.queryByTestId('mobius-selection-panel')).toBeNull();
  });

  it('domain filter chips drive the canvas visibleIds (projection untouched)', async () => {
    apiMock.getCustomerIntelligenceGraph.mockResolvedValue(graphFixture());
    mount();
    await waitFor(() => expect(canvasProps.current).toBeTruthy());
    expect(canvasProps.current.visibleIds.has('risk-0')).toBe(true);
    const riskChip = screen.getAllByRole('switch').find((s) => s.textContent?.includes('Risks'))!;
    fireEvent.click(riskChip);
    expect(riskChip.getAttribute('aria-checked')).toBe('false');
    expect(canvasProps.current.visibleIds.has('risk-0')).toBe(false);
    expect(canvasProps.current.visibleIds.has('technology-10')).toBe(true);
    expect(canvasProps.current.graph.nodes.some((n: any) => n.id === 'risk-0')).toBe(true);
    fireEvent.click(riskChip);
    expect(canvasProps.current.visibleIds.has('risk-0')).toBe(true);
  });

  it('offers add-intelligence guidance on a sparse projection', async () => {
    apiMock.getCustomerIntelligenceGraph.mockResolvedValue(sparseFixture());
    mount('Empty Co');
    await waitFor(() => expect(screen.getByText(/intentionally sparse/)).toBeTruthy());
    expect(screen.getByRole('button', { name: 'Technology Inventory' })).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Sales Notes' })).toBeTruthy();
  });

  it('canvas selection opens the panel with a deep link; Escape clears it', async () => {
    apiMock.getCustomerIntelligenceGraph.mockResolvedValue(graphFixture());
    const onNavigate = mount();
    await waitFor(() => expect(canvasProps.current).toBeTruthy());
    act(() => canvasProps.current.onSelect('technology-10'));
    const panel = await screen.findByTestId('mobius-selection-panel');
    expect(panel.textContent).toContain('VMware vSphere 6.5');
    expect(panel.textContent).toContain('connected node');
    fireEvent.click(screen.getByRole('button', { name: 'Open in Technology Inventory' }));
    expect(onNavigate).toHaveBeenCalledWith('technology-inventory');
    fireEvent.keyDown(panel, { key: 'Escape' });
    await waitFor(() => expect(screen.queryByTestId('mobius-selection-panel')).toBeNull());
  });

  it('search selects the matched node (drives the canvas selection)', async () => {
    apiMock.getCustomerIntelligenceGraph.mockResolvedValue(graphFixture());
    mount();
    await waitFor(() => expect(canvasProps.current).toBeTruthy());
    fireEvent.change(screen.getByRole('searchbox'), { target: { value: 'cisco ucs' } });
    const hit = await screen.findByRole('option');
    fireEvent.click(hit.querySelector('button') as Element);
    await waitFor(() => expect(canvasProps.current.selectedId).toBe('technology-11'));
    const panel = screen.getByTestId('mobius-selection-panel');
    expect(panel.textContent).toContain('Cisco UCS C240');
  });

  it('exposes a visually-hidden domain count + node list (a11y fallback)', async () => {
    apiMock.getCustomerIntelligenceGraph.mockResolvedValue(graphFixture());
    mount();
    const counts = await screen.findByLabelText('Intelligence by domain');
    expect(counts.textContent).toContain('Technology: 2');
    expect(screen.getByLabelText('Intelligence nodes').textContent).toContain('Renewal upsell');
  });

  it('group selection shows "Portion group"; empty shows "Empty portion"; chip excludes both', async () => {
    apiMock.getCustomerIntelligenceGraph.mockResolvedValue(hierarchyFixture());
    mount();
    await waitFor(() => expect(canvasProps.current).toBeTruthy());
    const chip = screen.getByTestId('mobius-node-count');
    expect(chip.textContent).toContain('5 nodes'); // 5 data records; group + empty excluded
    act(() => canvasProps.current.onSelect('portion-technology-cloud'));
    expect((await screen.findByTestId('mobius-selection-panel')).textContent).toContain('Portion group');
    act(() => canvasProps.current.onSelect('portion-empty-use_case'));
    await waitFor(() => expect(screen.getByTestId('mobius-selection-panel').textContent).toContain('Empty portion'));
  });

  it('a WebGL failure degrades to the unavailable card (page stays up)', async () => {
    apiMock.getCustomerIntelligenceGraph.mockResolvedValue(graphFixture());
    mount();
    await waitFor(() => expect(canvasProps.current).toBeTruthy());
    act(() => canvasProps.current.onUnavailable());
    expect(await screen.findByText('Visualization unavailable')).toBeTruthy();
    expect(screen.queryByTestId('mobius-graph-canvas')).toBeNull();
    // controls + legend still reachable
    expect(screen.getByLabelText('Constellation legend')).toBeTruthy();
  });

  it('shows an error state when the projection fails', async () => {
    apiMock.getCustomerIntelligenceGraph.mockRejectedValue({ message: 'boom' });
    mount();
    expect(await screen.findByRole('alert')).toBeTruthy();
  });
});

// ── Möbius wiring review (2026-11-01): selection card + deep links ───────
import { deepLinkFor, metadataRows } from '../src/components/CustomerIntelligenceConstellation';
import type { RenderNode } from '../src/lib/intelligenceGraph';

describe('selection card wiring', () => {
  const node = (over: Partial<RenderNode>): RenderNode => ({
    id: 'x', type: 'risk', label: 'x', category: 'risk', entityId: 0, entityType: 'risk', importance: 0.5,
    status: null, confidence: null, verified: true, metadata: {}, route: '', val: 5, ...over,
  } as RenderNode);

  it('formats the evidence object (never "[object Object]") and hides plumbing keys', () => {
    const rows = metadataRows(node({ metadata: {
      type: 'observed_gap', severity: 'high', detail: 'Platform team understaffed',
      evidence: { source: 'sales_evaluation', source_id: 4, source_name: 'Q4 platform readiness' },
      group_key: 'observed_gap', empty: false, domain: 'risk', extra: { nested: 1 },
    } }));
    expect(rows).toEqual([
      ['type', 'observed gap'], ['severity', 'high'], ['detail', 'Platform team understaffed'],
      ['Evidence', 'Sales evaluation · Q4 platform readiness'],
    ]);
    expect(JSON.stringify(rows)).not.toContain('[object Object]');
  });

  it('evidence without a record name shows the source only', () => {
    const rows = metadataRows(node({ metadata: { evidence: { source: 'customer_knowledge', source_id: null, source_name: null } } }));
    expect(rows).toEqual([['Evidence', 'Customer knowledge']]);
  });

  it('risk/opportunity deep-link to the area holding their evidence, else Attention', () => {
    expect(deepLinkFor(node({ metadata: { evidence: { source: 'technology', source_id: 1, source_name: 'RHEL' } } })))
      .toEqual({ target: 'technology-inventory', label: 'Open evidence in Technology Inventory' });
    expect(deepLinkFor(node({ type: 'opportunity', category: 'opportunity', metadata: { evidence: { source: 'sales_note', source_id: 2 } } }))?.target)
      .toBe('sales-notes');
    expect(deepLinkFor(node({ metadata: { evidence: { source: 'unknown_source' } } })))
      .toEqual({ target: 'sales-opportunities', label: 'Open in Attention' });
  });

  it('domain hubs and portion groups open their domain area; the account has no link', () => {
    expect(deepLinkFor(node({ type: 'domain', category: 'technology' }))?.target).toBe('technology-inventory');
    expect(deepLinkFor(node({ type: 'group', category: 'use_case' }))?.target).toBe('use-cases');
    expect(deepLinkFor(node({ type: 'customer', category: 'customer' }))).toBeNull();
    expect(deepLinkFor(node({ type: 'sales_evaluation', category: 'sales_evaluation' }))?.target).toBe('sales-evaluations');
  });
});
