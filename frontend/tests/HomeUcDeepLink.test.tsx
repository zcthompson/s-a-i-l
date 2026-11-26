/**
 * FE-11 — shareable use-case destinations (part 48).
 *
 * A deep link /?view=detail&uc=<id> (and scoring-dashboard/drilldown) must
 * restore the authorized record via the API instead of bouncing to the
 * assessment list; a forbidden/removed record falls back safely to the
 * list. The header <h2> (getViewLabel) is a deterministic probe independent
 * of lazy content.
 */
import { describe, it, expect, vi, afterEach, beforeAll } from 'vitest';
import { render, cleanup, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { Home } from '../src/pages/Home';

beforeAll(() => {
  if (typeof Element !== 'undefined' && !Element.prototype.scrollTo) {
    Element.prototype.scrollTo = function () { return undefined; };
  }
});

const UC = {
  id: 42,
  title: 'Deep-linked use case',
  description: '',
  customer_id: 1,
  customer_name: 'Acme',
  department: 'Eng',
  status: 'active',
  goals: [],
  challenges: [],
  pain_points: [],
  overall_score: 55.0,
  created_at: '2026-09-01T00:00:00Z',
  updated_at: '2026-09-01T00:00:00Z',
};

const { apiStub } = vi.hoisted(() => {
  const stub: any = {
    get: vi.fn(async (id: number) => (id === 42 ? UC : Promise.reject(new Error('404')))),
  };
  // Every other api method → resolve [] (Home's mount effects are tolerant).
  const proxy: any = new Proxy({}, {
    get: (_t, prop) => {
      if (typeof prop === 'string' && prop in stub) return stub[prop];
      return () => Promise.resolve([]);
    },
  });
  return { apiStub: proxy };
});

vi.mock('../src/lib/api', () => ({
  api: apiStub,
  clearAuth: vi.fn(),
  getAuthUsername: () => 'tester',
  getAuthIsAdmin: () => false,
  getAuthSalesRole: () => null,
}));
vi.mock('../src/lib/websocket', () => ({
  ws: { connect: vi.fn(), disconnect: vi.fn(), subscribe: vi.fn() },
}));

afterEach(cleanup);

const headerTitle = () => document.querySelector('main > header h2')?.textContent ?? '';

describe('FE-11 shareable use-case destinations', () => {
  it('deep link /?view=detail&uc=42 restores the record (not the assessment list)', async () => {
    render(
      <MemoryRouter initialEntries={['/?view=detail&uc=42']}>
        <Home />
      </MemoryRouter>,
    );
    // The selection-required view is preserved (uc present), and the record
    // is fetched + selected — the header shows the detail view, not the list.
    await waitFor(() => expect(headerTitle()).toBe('Use Case Detail'), { timeout: 2000 });
    expect(apiStub.get).toHaveBeenCalledWith(42);
  });

  it('deep link for a removed/forbidden use case falls back to the assessment list', async () => {
    render(
      <MemoryRouter initialEntries={['/?view=detail&uc=9999']}>
        <Home />
      </MemoryRouter>,
    );
    // api.get rejects (404) → selection dropped → safety net lands on the list.
    await waitFor(() => expect(headerTitle()).toBe('Assessments'), { timeout: 2000 });
  });

  it('selection-required view WITHOUT uc stays on the assessment list (original dead-end guard)', () => {
    render(
      <MemoryRouter initialEntries={['/?view=detail']}>
        <Home />
      </MemoryRouter>,
    );
    expect(headerTitle()).toBe('Assessments');
  });
});
