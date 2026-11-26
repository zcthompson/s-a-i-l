/**
 * Regression tests for lib/api.ts:
 *
 * FastAPI 422 validation errors carry `detail` as an ARRAY of
 *   {loc, msg, type}; the previous `new Error(error.detail)` rendered
 *   "[object Object],[object Object]" in every error banner. Now: one
 *   "field: message" per entry (loc minus the leading route segment),
 *   joined with "; ".
 * exportPdf/exportExcel/exportCSV did `res.blob()` with no
 *   `res.ok` check: a 500 downloaded the JSON error body as the "export"
 *   file (corrupt report.pdf). Now: the error is parsed (same helper)
 *   and thrown; the success path (blob) is unchanged.
 *
 * Plain-object response stubs (request() only uses status/ok/text/blob)
 * — no environment-dependent Response/undici assumptions.
 */
import { describe, it, expect, vi, afterEach } from 'vitest';
import { api } from '../src/lib/api';

/** Minimal Response-shaped stub: only the members request()/exports use. */
const fakeResponse = (status: number, body: string, ok?: boolean) => ({
  ok: ok ?? (status >= 200 && status < 400),
  status,
  statusText: status === 500 ? 'Internal Server Error' : 'OK',
  text: async () => body,
  blob: async () => new Blob([body]),
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('422 array-detail error rendering (lib/api.ts)', () => {
  it('renders each 422 entry as "field: message", joined with "; "', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => fakeResponse(
      422,
      JSON.stringify({
        detail: [
          { loc: ['body', 'title'], msg: 'field required', type: 'missing' },
          { loc: ['body', 'estimated_savings'], msg: 'value is not a valid number', type: 'value_error.number' },
        ],
      }),
    )));
    await expect(api.list()).rejects.toThrow('title: field required; estimated_savings: value is not a valid number');
  });

  it('falls back to the message alone when loc has no field segment', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => fakeResponse(
      422,
      JSON.stringify({ detail: [{ loc: ['body'], msg: 'value is not a valid dict', type: 'value_error' }] }),
    )));
    await expect(api.list()).rejects.toThrow('value is not a valid dict');
  });

  it('string detail (500) keeps the previous behavior', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => fakeResponse(500, JSON.stringify({ detail: 'Inference endpoint unavailable' }))));
    await expect(api.list()).rejects.toThrow('Inference endpoint unavailable');
  });

  it('non-JSON error body falls back to the raw text', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => fakeResponse(500, 'Internal Server Error')));
    await expect(api.list()).rejects.toThrow('Internal Server Error');
  });
});

describe('export integrity (lib/api.ts)', () => {
  it('exportPdf: a 500 rejects with the real reason (no corrupt download)', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => fakeResponse(500, JSON.stringify({ detail: 'PDF export failed: report exceeded size limit' }))));
    await expect(api.exportPdf('Acme Corp')).rejects.toThrow('PDF export failed: report exceeded size limit');
  });

  it('exportCSV: a 500 with array detail rejects with the formatted message', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => fakeResponse(
      500,
      JSON.stringify({ detail: [{ loc: ['body', 'use_case_ids'], msg: 'list too long', type: 'value_error' }] }),
    )));
    await expect(api.exportCSV('Acme Corp', [1, 2])).rejects.toThrow('use_case_ids: list too long');
  });

  it('exportExcel: a 500 rejects (no blob returned)', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => fakeResponse(500, JSON.stringify({ detail: 'Export failed' }))));
    await expect(api.exportExcel('Acme Corp')).rejects.toThrow('Export failed');
  });

  it.each(['exportPdf', 'exportCSV', 'exportExcel'] as const)(
    '%s: a 200 resolves with the blob (success path unchanged)',
    async (name) => {
      vi.stubGlobal('fetch', vi.fn(async () => fakeResponse(200, 'file-bytes')));
      const blob: Blob = await api[name]('Acme Corp');
      expect(blob).toBeInstanceOf(Blob);
      // jsdom's Blob lacks .text(); size still proves the bytes passed through.
      expect(blob.size).toBe('file-bytes'.length);
    },
  );
});
