import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { act, cleanup, fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter, useNavigate } from 'react-router-dom';
import { Home } from '../src/pages/Home';
const apiMock = vi.hoisted(() => ({ get: vi.fn(), list: vi.fn(), score: vi.fn() }));
vi.mock('../src/lib/api', () => ({ api: new Proxy(apiMock, { get: (target, key) => target[key as keyof typeof target] || (() => Promise.resolve([])) }), clearAuth: vi.fn(), getAuthUsername: () => 'tester', getAuthIsAdmin: () => true, getAuthSalesRole: () => null }));
vi.mock('../src/lib/websocket', () => ({ ws: { connect: vi.fn(), disconnect: vi.fn(), subscribe: () => () => {} } }));
vi.mock('../src/components/RadarChart', () => ({ RadarChartComponent: () => <div>Saved radar</div> }));
vi.mock('../src/pages/AssessmentList', () => ({ default: () => <div>Assessment recovery</div> }));
function Switch() { const navigate = useNavigate(); return <button onClick={() => navigate('/?view=scoring-dashboard&uc=13')}>Other score</button>; }
const record = (id: number) => ({ id, title: `Saved case ${id}`, overall_score: 65, scores: { dimension_scores: [{ name: `Dimension ${id}`, score: 65, weight: 1 }], reasoning: `Saved reasoning ${id}`, recommendations: [] }, scored_at: '2026-10-01T12:00:00Z' });
const mount = () => render(<MemoryRouter initialEntries={['/?view=scoring-dashboard&uc=12']}><Home /><Switch /></MemoryRouter>);
beforeEach(() => { vi.clearAllMocks(); apiMock.get.mockImplementation((id: number) => Promise.resolve(record(id))); apiMock.list.mockResolvedValue([]); });
afterEach(cleanup);
it('restores the saved breakdown on a fresh deep link without scoring again', async () => {
  mount();
  expect(await screen.findByRole('heading', { name: 'Saved case 12' })).toBeTruthy();
  expect(screen.getByText('Dimension 12')).toBeTruthy();
  expect(screen.getByText('Saved reasoning 12')).toBeTruthy();
  expect(apiMock.get).toHaveBeenCalledWith(12);
  expect(apiMock.score).not.toHaveBeenCalled();
});
it('hides the previous results until another authorized record is restored', async () => {
  let resolve!: (value: ReturnType<typeof record>) => void;
  apiMock.get.mockImplementation((id: number) => id === 12 ? Promise.resolve(record(id)) : new Promise(r => { resolve = r; }));
  mount(); await screen.findByRole('heading', { name: 'Saved case 12' });
  fireEvent.click(screen.getByText('Other score'));
  expect(screen.queryByText('Saved reasoning 12')).toBeNull();
  await act(async () => resolve(record(13)));
  expect(await screen.findByRole('heading', { name: 'Saved case 13' })).toBeTruthy();
  expect(screen.getByText('Saved reasoning 13')).toBeTruthy();
});
it('keeps missing scores unavailable rather than inventing a breakdown', async () => {
  apiMock.get.mockResolvedValue({ ...record(12), scores: null });
  mount();
  expect(await screen.findByText('Scoring results are unavailable.')).toBeTruthy();
  expect(screen.queryByText('Saved reasoning 12')).toBeNull();
  expect(apiMock.score).not.toHaveBeenCalled();
});
it('recovers from an unauthorized or missing record without displaying scores', async () => {
  apiMock.get.mockRejectedValue(new Error('Not found'));
  mount();
  expect(await screen.findByText('Assessment recovery')).toBeTruthy();
  expect(screen.queryByText('Saved reasoning 12')).toBeNull();
});
