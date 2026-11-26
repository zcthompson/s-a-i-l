/**
 * CustomerAliasesField (the Edit customer dialog's Aliases section — moved
 * off the Overview card per the operator directive 2026-11-01): writer
 * controls vs read-only chips (fail-closed default), verbatim 422/409 inline
 * errors, add → refetch, onChange with the raw alias list. Synthetic names only.
 */
import { describe, it, expect, vi, afterEach, beforeEach } from 'vitest';
import { render, screen, cleanup, fireEvent, waitFor } from '@testing-library/react';

const { apiMock } = vi.hoisted(() => ({
  apiMock: { listAliases: vi.fn(), addAlias: vi.fn(), removeAlias: vi.fn() },
}));
vi.mock('../src/lib/api', () => ({ api: apiMock }));

import { CustomerAliasesField } from '../src/components/CustomerAliasesField';

const row = (id: number, alias: string) => ({ id, alias, created_by: 'owner1', created_at: '2026-10-01T12:00:00Z' });
const apiError = (msg: string, status: number) => Object.assign(new Error(msg), { status });
const chips = () => screen.queryAllByTestId('customer-alias-chip').map(c => c.textContent ?? '');

beforeEach(() => {
  apiMock.listAliases.mockReset().mockResolvedValue([row(1, 'Quill Co'), row(2, 'QP Group')]);
  apiMock.addAlias.mockReset();
  apiMock.removeAlias.mockReset().mockResolvedValue(undefined);
});
afterEach(cleanup);

describe('Edit customer — Aliases field', () => {
  it('reports the raw alias list through onChange after load and each add', async () => {
    const onChange = vi.fn();
    render(<CustomerAliasesField customerName="Quillon Partners" canManage onChange={onChange} />);
    await screen.findByText('Quill Co');
    apiMock.addAlias.mockResolvedValue(row(3, 'Quillon Intl'));
    apiMock.listAliases.mockResolvedValue([row(1, 'Quill Co'), row(2, 'QP Group'), row(3, 'Quillon Intl')]);
    fireEvent.change(screen.getByLabelText('New alias'), { target: { value: 'Quillon Intl' } });
    fireEvent.click(screen.getByRole('button', { name: 'Add alias' }));
    await screen.findByText('Quillon Intl');
    expect(onChange).toHaveBeenLastCalledWith(['Quill Co', 'QP Group', 'Quillon Intl']);
  });

  it('several aliases can be attached in one sitting', async () => {
    apiMock.listAliases.mockResolvedValue([]);
    render(<CustomerAliasesField customerName="Quillon Partners" canManage />);
    await screen.findByText('No aliases recorded.');
    const added: ReturnType<typeof row>[] = [];
    for (const [i, name] of ['Quill A', 'Quill B', 'Quill C'].entries()) {
      added.push(row(i + 1, name));
      apiMock.addAlias.mockResolvedValueOnce(row(i + 1, name));
      apiMock.listAliases.mockResolvedValueOnce([...added]);
      fireEvent.change(screen.getByLabelText('New alias'), { target: { value: name } });
      fireEvent.click(screen.getByRole('button', { name: 'Add alias' }));
      await screen.findByText(name);
    }
    expect(chips()).toHaveLength(3);
    expect(apiMock.addAlias).toHaveBeenCalledTimes(3);
  });

  it('owner/admin sees the add input and per-chip remove controls', async () => {
    render(<CustomerAliasesField customerName="Quillon Partners" canManage />);
    await screen.findByText('Quill Co');
    expect(screen.getByTestId('customer-aliases-field').textContent).toContain('Aliases');
    expect(screen.getByRole('list', { name: 'Aliases' })).toBeTruthy();
    expect(apiMock.listAliases).toHaveBeenCalledWith('Quillon Partners');
    expect(screen.getByLabelText('New alias')).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Add alias' }).textContent).toBe('Add');
    expect(screen.getByLabelText('Remove alias Quill Co')).toBeTruthy();
    expect(screen.getByLabelText('Remove alias QP Group')).toBeTruthy();
    expect(screen.getAllByTestId('customer-alias-chip')[0].getAttribute('title')).toContain('Added by owner1');
  });

  it('non-writers (canManage=false and the default) see read-only chips', async () => {
    render(<CustomerAliasesField customerName="Quillon Partners" canManage={false} />);
    await screen.findByText('Quill Co');
    expect(screen.queryByLabelText('New alias')).toBeNull();
    expect(screen.queryByLabelText(/^Remove alias/)).toBeNull();
    cleanup();
    render(<CustomerAliasesField customerName="Quillon Partners" />);
    await screen.findByText('QP Group');
    expect(screen.queryByLabelText('New alias')).toBeNull();
    expect(screen.queryByLabelText(/^Remove alias/)).toBeNull();
  });

  it('empty state', async () => {
    apiMock.listAliases.mockResolvedValue([]);
    render(<CustomerAliasesField customerName="Quillon Partners" canManage />);
    expect(await screen.findByText('No aliases recorded.')).toBeTruthy();
  });

  it('add → list refetch shows the new chip and clears the input', async () => {
    render(<CustomerAliasesField customerName="Quillon Partners" canManage />);
    await screen.findByText('Quill Co');
    apiMock.addAlias.mockResolvedValue(row(3, 'Quillon Intl'));
    apiMock.listAliases.mockResolvedValue([row(1, 'Quill Co'), row(2, 'QP Group'), row(3, 'Quillon Intl')]);
    const input = screen.getByLabelText('New alias') as HTMLInputElement;
    fireEvent.change(input, { target: { value: 'Quillon Intl' } });
    fireEvent.click(screen.getByRole('button', { name: 'Add alias' }));
    await screen.findByText('Quillon Intl');
    expect(apiMock.addAlias).toHaveBeenCalledWith('Quillon Partners', 'Quillon Intl');
    expect(apiMock.listAliases).toHaveBeenCalledTimes(2);
    expect(input.value).toBe('');
    expect(screen.queryByTestId('customer-aliases-error')).toBeNull();
  });

  it('remove → list refetch drops the chip', async () => {
    render(<CustomerAliasesField customerName="Quillon Partners" canManage />);
    await screen.findByText('Quill Co');
    apiMock.listAliases.mockResolvedValue([row(2, 'QP Group')]);
    fireEvent.click(screen.getByLabelText('Remove alias Quill Co'));
    await waitFor(() => expect(screen.queryByText('Quill Co')).toBeNull());
    expect(apiMock.removeAlias).toHaveBeenCalledWith('Quillon Partners', 1);
    expect(chips()).toHaveLength(1);
  });

  it.each([
    ['Alias must differ from the customer name', 422],
    ['Alias matches an existing customer name', 422],
    ['Alias already in use', 409],
  ])('verbatim inline error: %s (%i)', async (msg, status) => {
    render(<CustomerAliasesField customerName="Quillon Partners" canManage />);
    await screen.findByText('Quill Co');
    apiMock.addAlias.mockRejectedValue(apiError(msg, status));
    const input = screen.getByLabelText('New alias') as HTMLInputElement;
    fireEvent.change(input, { target: { value: 'Something' } });
    fireEvent.click(screen.getByRole('button', { name: 'Add alias' }));
    const err = await screen.findByTestId('customer-aliases-error');
    expect(err.textContent).toBe(msg);
    expect(input.value).toBe('Something'); // failure keeps the draft
    expect(apiMock.listAliases).toHaveBeenCalledTimes(1);
  });
});
