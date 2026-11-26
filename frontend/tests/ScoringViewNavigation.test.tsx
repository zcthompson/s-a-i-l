import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter, useLocation, useNavigate } from 'react-router-dom';
import { ScoringDashboard } from '../src/components/ScoringDashboard';
vi.mock('../src/lib/api', () => ({ api: {} }));
vi.mock('../src/components/RadarChart', () => ({ RadarChartComponent: () => <div>Radar chart</div> }));
vi.mock('recharts', () => {
  const Stub = ({ children }: { children?: React.ReactNode }) => <div>{children}</div>;
  return { BarChart: Stub, Bar: Stub, XAxis: Stub, YAxis: Stub, CartesianGrid: Stub, Tooltip: Stub, ResponsiveContainer: Stub, PieChart: Stub, Pie: Stub, Cell: Stub, Legend: Stub };
});
const scoredData: any = {
  use_case: { id: 12, title: 'Scored use case' },
  scores: { dimension_scores: [{ name: 'Strategy', score: 5, weight: 0.2 }], overall_score: 5, reasoning: 'Some reasoning', scored_at: null, recommendations: [] },
};
function Probe() {
  const location = useLocation();
  const navigate = useNavigate();
  return <><output data-testid="score-url">{location.search}</output><button onClick={() => navigate(-1)}>History back</button></>;
}
afterEach(cleanup);
describe('scoring view links', () => {
  it('restores a chart tab and follows history for the same use case', () => {
    render(<MemoryRouter initialEntries={['/?score_owner=12&score_tab=bars']}><Probe /><ScoringDashboard scoredData={scoredData} onBack={() => {}} /></MemoryRouter>);
    expect(screen.getByRole('button', { name: 'Show bars tab' }).getAttribute('aria-pressed')).toBe('true');
    fireEvent.click(screen.getByRole('button', { name: 'Show detail tab' }));
    expect(screen.getByTestId('score-url').textContent).toContain('score_tab=detail');
    fireEvent.click(screen.getByText('History back'));
    expect(screen.getByRole('button', { name: 'Show bars tab' }).getAttribute('aria-pressed')).toBe('true');
  });
  it('does not apply another use case’s chart tab', () => {
    render(<MemoryRouter initialEntries={['/?score_owner=99&score_tab=detail']}><ScoringDashboard scoredData={scoredData} onBack={() => {}} /></MemoryRouter>);
    expect(screen.getByRole('button', { name: 'Show radar tab' }).getAttribute('aria-pressed')).toBe('true');
  });
});
