import { afterEach, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { RadarChartComponent } from '../src/components/RadarChart';
vi.mock('recharts', () => {
  const Stub = ({ children }: { children?: React.ReactNode }) => <div>{children}</div>;
  return { Radar: Stub, RadarChart: Stub, PolarGrid: Stub, PolarAngleAxis: Stub, PolarRadiusAxis: Stub, ResponsiveContainer: Stub, Tooltip: Stub, Legend: Stub };
});
afterEach(cleanup);
it('keeps full dimension names and exact values available beyond abbreviated chart labels', () => {
  const name = 'Organizational Readiness with a long descriptive label';
  render(<RadarChartComponent dimensionScores={[{ name, score: 0, weight: .2, description: '' }]} />);
  expect(screen.getByRole('img').getAttribute('aria-label')).toContain(name);
  fireEvent.click(screen.getByText('View chart data'));
  const region = screen.getByRole('region', { name: 'AI Readiness Radar data' });
  expect(region.tabIndex).toBe(0);
  expect(screen.getByRole('rowheader', { name })).toBeTruthy();
  expect(screen.getByRole('cell', { name: '0.0' })).toBeTruthy();
  expect(screen.getByRole('cell', { name: '20%' })).toBeTruthy();
});
it('reports an empty chart without fabricating numeric values', () => {
  render(<RadarChartComponent dimensionScores={[]} />);
  expect(screen.getByRole('status').textContent).toBe('No chart data available.');
  expect(screen.queryByRole('table')).toBeNull();
});
