/**
 * H6 — AccountBriefPanel + api fns (synthetic fixtures; api mocked with the
 * vi.hoisted pattern). Rail order is pinned in U4Navigation.test.tsx.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, cleanup, waitFor } from '@testing-library/react';
import { AccountBriefPanel } from '../src/components/AccountBriefPanel';

afterEach(() => cleanup());

const { apiMock } = vi.hoisted(() => ({
  apiMock: { getAccountBrief: vi.fn(), downloadAccountBriefMd: vi.fn(), downloadAccountBriefPdf: vi.fn() },
}));
vi.mock('../src/lib/api', () => ({ api: apiMock }));

const section = (available: boolean) => ({ available, source: null });
const brief = (over: Record<string, unknown> = {}) => ({
  customer_id: 5, customer_name: 'Acme', generated_at: '2026-10-28T12:00:00+00:00', calc_version: 'account-brief/1',
  source_snapshots: {
    pipeline_import_id: null, pipeline_source_file: null, pipeline_imported_at: null,
    technology_recorded: 3, notes_recorded: 2, contacts_recorded: 2, activities_recorded: 1, open_tasks: 4,
  },
  sections: {
    account_snapshot: section(true), technology: section(true), pipeline: section(false), renewals: section(false),
    notes: section(true), attention: section(false), contacts: section(true), persona_questions: section(false),
    engagement: section(true), activities: section(true), tasks: section(true),
  },
  markdown: '# Account Brief — Acme\n\n- note \\<script\\>alert(1)\\</script\\> \\* x\n- <b>raw</b>',
  ...over,
});

beforeEach(() => {
  vi.clearAllMocks();
  apiMock.getAccountBrief.mockResolvedValue(brief());
  apiMock.downloadAccountBriefMd.mockResolvedValue(new Blob(['x']));
  apiMock.downloadAccountBriefPdf.mockResolvedValue(new Blob(['x']));
  (window.URL as any).createObjectURL = vi.fn(() => 'blob:x');
  (window.URL as any).revokeObjectURL = vi.fn();
  vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {});
});

describe('AccountBriefPanel', () => {
  it('fetches on mount and renders meta + markdown verbatim (no HTML interpretation)', async () => {
    render(<AccountBriefPanel customerId={5} userRole="member" />);
    const md = await screen.findByTestId('account-brief-markdown');
    expect(apiMock.getAccountBrief).toHaveBeenCalledWith(5);
    expect(md.tagName).toBe('PRE');
    expect(md.textContent).toBe(brief().markdown);
    expect(md.querySelector('b')).toBeNull();
    const meta = screen.getByTestId('account-brief-meta').textContent!;
    expect(meta).toContain('Generated 2026-10-28T12:00:00+00:00 · account-brief/1');
    expect(meta).toContain('3 technologies · 2 notes · 2 contacts · 1 activities · 4 open tasks (recorded)');
    expect(screen.queryByTestId('account-brief-error')).toBeNull();
  });

  it('download buttons call the api fns and save a file', async () => {
    render(<AccountBriefPanel customerId={5} userRole="auditor" />);
    fireEvent.click(await screen.findByTestId('account-brief-download-md'));
    await waitFor(() => expect(apiMock.downloadAccountBriefMd).toHaveBeenCalledWith(5));
    await waitFor(() => expect((window.URL as any).revokeObjectURL).toHaveBeenCalledTimes(1));
    fireEvent.click(screen.getByTestId('account-brief-download-pdf'));
    await waitFor(() => expect(apiMock.downloadAccountBriefPdf).toHaveBeenCalledWith(5));
  });

  it('shows a download 403 detail verbatim inline (role=status) without losing the preview', async () => {
    apiMock.downloadAccountBriefPdf.mockRejectedValue(new Error('Export is not permitted for this customer'));
    render(<AccountBriefPanel customerId={5} userRole="member" />);
    fireEvent.click(await screen.findByTestId('account-brief-download-pdf'));
    const err = await screen.findByTestId('account-brief-download-error');
    expect(err.textContent).toBe('Export is not permitted for this customer');
    expect(err.getAttribute('role')).toBe('status');
    expect(screen.getByTestId('account-brief-markdown')).toBeTruthy();
  });

  it('shows the preview error verbatim in account-brief-error', async () => {
    apiMock.getAccountBrief.mockRejectedValue(new Error('Customer not found'));
    render(<AccountBriefPanel customerId={5} userRole="member" />);
    const err = await screen.findByTestId('account-brief-error');
    expect(err.textContent).toBe('Customer not found');
    expect(err.getAttribute('role')).toBe('status');
    expect(screen.queryByTestId('account-brief-markdown')).toBeNull();
  });

  it('renders an empty account (all Not recorded.) as a normal state', async () => {
    const lines = ['## Technology inventory', '- Not recorded.', '## Open tasks', '- Not recorded.'].join('\n');
    apiMock.getAccountBrief.mockResolvedValue(brief({
      markdown: lines,
      source_snapshots: { ...brief().source_snapshots, technology_recorded: 0, notes_recorded: 0, contacts_recorded: 0, activities_recorded: 0, open_tasks: 0 },
    }));
    render(<AccountBriefPanel customerId={5} userRole="member" />);
    expect((await screen.findByTestId('account-brief-markdown')).textContent).toBe(lines);
    expect(screen.queryByTestId('account-brief-error')).toBeNull();
  });
});
