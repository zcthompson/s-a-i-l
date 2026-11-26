/**
 * Regression tests: Business Impact Matrix — the department legend rendered
 * ON TOP of the XAxis "Effort Level" label.
 *
 * Reported behavior (2026-09-03, user visual check): in the Business Impact
 * section (full customer view), the matrix legend's department names
 * overlapped the "Effort Level" axis text — with or without compact display
 * (compact is a global zoom, so it could not change the relative overlap).
 *
 * Root cause (recharts 2.15.4 source): the bottom XAxis label
 * (position 'bottom', offset 0) is drawn with its text top at the BOTTOM of
 * the 30px axis region, extending DOWN into the bottom margin (Label.js:
 * y = viewBox.y + height + offset, verticalAnchor 'start'). The recharts
 * <Legend> is an absolutely-positioned HTML div anchored at
 * bottom: margin.bottom (32px) — its top edge lands on exactly that same y,
 * so the first legend row painted over the "Effort Level" text.
 *
 * Fix (the contract these tests lock in): the legend is now a custom HTML
 * list rendered BELOW the chart (MatrixLegend). It is structurally separated
 * from the axis label (40px clear space — >10% of the 340px chart height —
 * and the whole block sits 72-88px lower than the previous in-chart
 * position), caps at TWO rows using measured item widths, and collapses the
 * overflow into a "+N more" toggle that expands on demand.
 */
import { describe, it, expect, vi, afterEach, afterAll } from 'vitest';
import { render, screen, cleanup, fireEvent } from '@testing-library/react';
import { ImpactMatrix, MatrixLegend } from '../src/components/ImpactMatrix';

type MatrixPoint = {
  id: number;
  title: string;
  department: string;
  overall_score: number;
  total_impact: number;
  effort_level: number;
  effort_label: string;
  impact_category: string | null;
  status: string;
};

const { apiStub, DEPTS } = vi.hoisted(() => {
  // 12 departments — mirrors the customer-scoped view: every customer in the
  // dev DB has exactly 12 distinct departments across their scored use cases.
  const DEPTS = [
    'Engineering',
    'Finance',
    'Marketing',
    'Operations',
    'IT Infrastructure',
    'Human Resources',
    'Customer Success',
    'Product Management',
    'Supply Chain',
    'Legal',
    'Quality',
    'Data Science',
  ];
  const points: MatrixPoint[] = DEPTS.map((dept, i) => ({
    id: i + 1,
    title: `Use case ${i + 1} — ${dept}`,
    department: dept,
    overall_score: 90 - i * 5, // descending → stable score-ranked legend order
    total_impact: 100000 + i * 25000,
    effort_level: (i % 3) + 1,
    effort_label: ['Short', 'Medium', 'Long'][i % 3],
    impact_category: null,
    status: 'active',
  }));
  const matrixData = {
    points,
    quadrants: { quick_win: [], major_project: [], fill_in: [], thankless_task: [] },
  };
  const methods: Record<string, (...args: any[]) => Promise<any>> = {
    impactMatrix: () => Promise.resolve(matrixData),
  };
  const fallback = () => Promise.resolve([]);
  const apiStub = new Proxy(
    {},
    {
      get: (_target, prop) => (typeof prop === 'string' && methods[prop] ? methods[prop] : fallback),
    },
  );
  return { apiStub, DEPTS };
});

vi.mock('../src/lib/api', () => ({
  api: apiStub,
  clearAuth: vi.fn(),
  getAuthUsername: () => 'admin',
  getAuthIsAdmin: () => false,
  getAuthSalesRole: () => null,
}));

// jsdom has no layout engine: give getBoundingClientRect a deterministic size
// so recharts' ResponsiveContainer renders the full 1200x340 chart svg (the
// "Effort Level" axis label and the recharts wrapper structure become
// assertable). Saved here, restored in afterAll.
const origGBCR = Object.getOwnPropertyDescriptor(Element.prototype, 'getBoundingClientRect');

function stubChartLayout(): void {
  vi.stubGlobal(
    'ResizeObserver',
    class {
      observe() {}
      unobserve() {}
      disconnect() {}
    },
  );
  Object.defineProperty(Element.prototype, 'getBoundingClientRect', {
    configurable: true,
    value: function () {
      return { x: 0, y: 0, top: 0, left: 0, right: 1200, bottom: 340, width: 1200, height: 340 };
    },
  });
}

/**
 * Give the legend row a deterministic width and every measurement-layer item
 * a deterministic width, so the two-row cap computation runs for real.
 * Instance-level stubs only (no prototype pollution).
 */
function stubLegendWidths(row: HTMLElement, itemWidth: number, rowWidth: number): void {
  Object.defineProperty(row, 'clientWidth', { configurable: true, value: rowWidth });
  const layer = row.querySelector('div[aria-hidden="true"]') as HTMLElement;
  Array.from(layer.children).forEach(el =>
    Object.defineProperty(el, 'offsetWidth', { configurable: true, value: itemWidth }),
  );
}

const LEGEND_ITEMS = DEPTS.map((name, i) => ({ name, color: `var(--cat-${i + 1})` }));

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

afterAll(() => {
  if (origGBCR) Object.defineProperty(Element.prototype, 'getBoundingClientRect', origGBCR);
});

describe('ImpactMatrix — legend placement (no "Effort Level" overlap)', () => {
  it('renders the department legend BELOW the chart, outside the recharts wrapper, with the axis label intact', async () => {
    stubChartLayout();
    render(<ImpactMatrix customerId={7} section="all" />);

    // The custom legend list loads with the data…
    const list = await screen.findByRole('list', { name: /departments ranked by average readiness score/i });
    // …with every department visible as a listitem (uncapped in jsdom:
    // widths unmeasurable), in score-ranked order.
    expect(screen.getAllByRole('listitem')).toHaveLength(DEPTS.length);
    const visibleText = visibleLegendText(list);
    expect(visibleText).toContain(DEPTS[0]);
    expect(visibleText).toContain(DEPTS[DEPTS.length - 1]);

    // The "Effort Level" axis label is still inside the chart svg…
    const axisLabel = screen.getByText('Effort Level');
    expect(axisLabel.closest('svg')).not.toBeNull();
    // …and the legend is NOT inside the chart's svg or recharts wrapper —
    // the pre-fix collision site (the legend div was anchored at
    // bottom: margin.bottom, exactly on the axis label).
    expect(list.closest('svg')).toBeNull();
    expect(list.closest('.recharts-wrapper')).toBeNull();

    // In the card, the legend comes AFTER the chart container.
    const card = screen.getByRole('region', { name: 'Business impact matrix chart' });
    const chartContainer = card.querySelector('.recharts-responsive-container');
    expect(chartContainer).not.toBeNull();
    const children = Array.from(card.children);
    expect(children.indexOf(chartContainer as Element)).toBeLessThan(children.indexOf(list.parentElement as Element));
  });
});

/** Text of the VISIBLE legend items only (excludes the hidden measurement
 *  layer, which always contains every name). */
function visibleLegendText(list: Element): string {
  const items = Array.from(list.querySelectorAll('[role="listitem"]')) as HTMLElement[];
  return items.map(el => el.textContent ?? '').join(' ');
}

describe('MatrixLegend — two-row cap with "+N more" expander', () => {
  it('caps at two rows with a +N more toggle when the departments overflow', () => {
    render(<MatrixLegend items={LEGEND_ITEMS} />);
    const list = screen.getByRole('list', { name: /departments ranked by average readiness score/i });
    // Mount in jsdom is unmeasurable → uncapped; give it deterministic widths
    // (12 items x 100px, 16px gaps, 500px row) and re-measure via the window
    // resize hook: row 1 holds 4 items (448px), row 2 (minus the 110px chip
    // reserve) holds 3 more (332px) → cap 7.
    stubLegendWidths(list, 100, 500);
    fireEvent(window, new Event('resize'));
    // 7 department items + the chip's listitem = 8 listitems; the first
    // hidden item (index 7, "Product Management") must be gone, the last
    // visible one (index 6, "Customer Success") present.
    expect(screen.getAllByRole('listitem')).toHaveLength(8);
    let visibleText = visibleLegendText(list);
    expect(visibleText).toContain('Customer Success');
    expect(visibleText).not.toContain('Product Management');
    const chip = screen.getByRole('button', { name: 'Show 5 more departments' });
    expect(chip.textContent).toBe('+5 more');

    // Expand → all 12 names + the "Show less" chip's listitem = 13…
    fireEvent.click(chip);
    expect(screen.getAllByRole('listitem')).toHaveLength(13);
    visibleText = visibleLegendText(list);
    expect(visibleText).toContain('Product Management');
    expect(visibleText).toContain('Data Science');
    const collapse = screen.getByRole('button', { name: 'Collapse department legend' });
    expect(collapse.textContent).toBe('Show less');
    // …and collapse back to the two-row cap.
    fireEvent.click(collapse);
    expect(screen.getAllByRole('listitem')).toHaveLength(8);
    expect(visibleLegendText(list)).not.toContain('Product Management');
  });

  it('shows every department without the toggle when all fit in two rows', () => {
    render(<MatrixLegend items={LEGEND_ITEMS} />);
    const list = screen.getByRole('list', { name: /departments ranked by average readiness score/i });
    // 12 x 100px + 16px gaps fit: row 1 = 8 items (912px of 1000px),
    // row 2 = the remaining 4 (448px of the 890px budget).
    stubLegendWidths(list, 100, 1000);
    fireEvent(window, new Event('resize'));
    expect(screen.getAllByRole('listitem')).toHaveLength(12);
    expect(screen.queryByRole('button')).toBeNull();
    expect(visibleLegendText(list)).toContain('Data Science');
  });

  it('degrades gracefully when a single department name exceeds the row width', () => {
    render(<MatrixLegend items={LEGEND_ITEMS} />);
    const list = screen.getByRole('list', { name: /departments ranked by average readiness score/i });
    // Each item (600px) is wider than the row (500px): at least one item
    // stays visible and the rest collapse into the chip.
    stubLegendWidths(list, 600, 500);
    fireEvent(window, new Event('resize'));
    expect(screen.getAllByRole('listitem')).toHaveLength(2); // 1 item + chip
    expect(screen.getByRole('button', { name: 'Show 11 more departments' })).toBeTruthy();
    const visibleText = visibleLegendText(list);
    expect(visibleText).toContain('Engineering');
    expect(visibleText).not.toContain('Data Science');
  });
});
