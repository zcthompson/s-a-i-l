import { afterEach, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { ConstellationErrorBoundary } from '../src/components/ConstellationErrorBoundary';
afterEach(() => { cleanup(); vi.restoreAllMocks(); });
it('retries only the failed visualization and recovers its content', () => {
  vi.spyOn(console, 'error').mockImplementation(() => {});
  let fail = true;
  function Child() { if (fail) throw new Error('Synthetic graphics failure'); return <div>Recovered graph</div>; }
  render(<><h1>Customer workspace</h1><ConstellationErrorBoundary><Child /></ConstellationErrorBoundary></>);
  expect(screen.getByRole('alert').textContent).toContain('Visualization unavailable');
  expect(screen.getByRole('heading', { name: 'Customer workspace' })).toBeTruthy();
  fail = false;
  fireEvent.click(screen.getByRole('button', { name: 'Try again' }));
  expect(screen.getByText('Recovered graph')).toBeTruthy();
  expect(screen.queryByRole('alert')).toBeNull();
});
