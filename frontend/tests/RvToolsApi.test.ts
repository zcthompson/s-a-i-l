// RVTools api client — request shape (URL, method, FormData target field,
// query params) and the .status sentinel on errors.
import { describe, it, expect, vi, afterEach } from 'vitest';
import { api } from '../src/lib/api';

const fakeResponse = (status: number, body: string) => ({
  ok: status >= 200 && status < 400,
  status,
  statusText: status === 404 ? 'Not Found' : status === 403 ? 'Forbidden' : 'OK',
  text: async () => body,
  json: async () => JSON.parse(body),
});
const stubFetch = (status: number, body: unknown) => {
  const fn = vi.fn(async (..._a: unknown[]) => fakeResponse(status, JSON.stringify(body)));
  vi.stubGlobal('fetch', fn);
  return fn;
};
afterEach(() => { vi.unstubAllGlobals(); });

describe('RVTools api client', () => {
  it('uploadRvToolsImport posts multipart with file + customer_name only', async () => {
    const fetchMock = stubFetch(201, { import_id: 1 });
    const file = new File(['x'], 'a.xlsx');
    const res = await api.uploadRvToolsImport(file, { customer_name: 'Acme' });
    expect(res).toEqual({ import_id: 1 });
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toMatch(/\/rvtools-import\/$/);
    expect(init.method).toBe('POST');
    const fd = init.body as FormData;
    expect(fd.get('file')).toBeInstanceOf(File);
    expect(fd.get('customer_name')).toBe('Acme');
    expect(fd.has('new_customer_name')).toBe(false);
    expect((init.headers as Record<string, string>)['Content-Type']).toBeUndefined();
  });

  it('uploadRvToolsImport attaches .status on errors', async () => {
    stubFetch(403, { detail: 'Requires sales manager or higher' });
    await expect(api.uploadRvToolsImport(new File(['x'], 'a.xlsx'), { customer_name: 'A' }))
      .rejects.toMatchObject({ status: 403, message: expect.stringContaining('Requires sales manager') });
  });

  it('listRvToolsImports GETs the collection', async () => {
    const fetchMock = stubFetch(200, []);
    expect(await api.listRvToolsImports()).toEqual([]);
    expect((fetchMock.mock.calls[0] as [string])[0]).toMatch(/\/rvtools-import\/$/);
  });

  it('getRvToolsImport passes vm_limit/vm_offset only when given', async () => {
    const fetchMock = stubFetch(200, { import_id: 7 });
    await api.getRvToolsImport(7);
    expect((fetchMock.mock.calls[0] as [string])[0]).toMatch(/\/rvtools-import\/7\/$/);
    await api.getRvToolsImport(7, 100, 200);
    expect((fetchMock.mock.calls[1] as [string])[0]).toMatch(/\/rvtools-import\/7\/\?vm_limit=100&vm_offset=200$/);
  });

  it('getRvToolsImport 404 carries .status', async () => {
    stubFetch(404, { detail: 'Not found' });
    await expect(api.getRvToolsImport(9)).rejects.toMatchObject({ status: 404 });
  });

  it('deleteRvToolsImport uses DELETE', async () => {
    const fetchMock = stubFetch(200, { detail: 'ok', temp_customer_kept: true });
    await api.deleteRvToolsImport(3);
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toMatch(/\/rvtools-import\/3\/$/);
    expect(init.method).toBe('DELETE');
  });

  it('getCustomerRvTools encodes the customer name', async () => {
    const fetchMock = stubFetch(200, { customer_name: 'A & B/C' });
    await api.getCustomerRvTools('A & B/C');
    expect((fetchMock.mock.calls[0] as [string])[0]).toMatch(/\/customers\/A%20%26%20B%2FC\/rvtools\/$/);
  });

  it('getCustomerRvTools 404 carries .status', async () => {
    stubFetch(404, { detail: 'Customer not found' });
    await expect(api.getCustomerRvTools('Nope')).rejects.toMatchObject({ status: 404 });
  });
});
