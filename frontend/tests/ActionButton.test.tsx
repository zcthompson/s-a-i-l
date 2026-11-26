import { afterEach, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { ActionButton } from '../src/components/ActionButton';
afterEach(cleanup);
it('keeps its name and blocks repeat activation while busy, then re-enables', () => {
  const click = vi.fn();
  const { rerender } = render(<ActionButton busy aria-label="Save account" onClick={click}>Save</ActionButton>);
  const button = screen.getByRole('button', { name: 'Save account' }) as HTMLButtonElement;
  expect(button.disabled).toBe(true);
  expect(button.getAttribute('aria-busy')).toBe('true');
  fireEvent.click(button);
  expect(click).not.toHaveBeenCalled();
  rerender(<ActionButton busy={false} aria-label="Save account" onClick={click}>Save</ActionButton>);
  expect(button.disabled).toBe(false);
  expect(button.getAttribute('aria-busy')).toBeNull();
  fireEvent.click(button);
  expect(click).toHaveBeenCalledTimes(1);
});
