import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { Settings } from '../src/pages/Settings';
import { MemoryRouter, useLocation, useNavigate } from 'react-router-dom';
import { getPreferences, resetPreferences } from '../src/lib/preferences';

beforeEach(() => {
  resetPreferences();
  document.documentElement.removeAttribute('data-compact');
});
afterEach(() => {
  cleanup();
  vi.useRealTimers();
});

function RouteProbe() {
  const location = useLocation();
  const navigate = useNavigate();
  return <><output data-testid="settings-url">{location.search}</output><button onClick={() => navigate(-1)}>History back</button><button onClick={() => navigate(1)}>History forward</button></>;
}

describe('Settings tab links', () => {
  it('restores a direct link and follows back and forward while preserving parameters and drafts', () => {
    render(<MemoryRouter initialEntries={['/?view=settings-appearance&settings_tab=notifications&extra=1']}><RouteProbe /><Settings /></MemoryRouter>);
    const notifications = screen.getByRole('button', { name: 'Show Notifications settings' });
    expect(notifications.getAttribute('aria-pressed')).toBe('true');
    fireEvent.click(screen.getByLabelText('Receive email alerts'));
    expect(screen.getByText('Unsaved changes')).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: 'Show About settings' }));
    const params = new URLSearchParams(screen.getByTestId('settings-url').textContent ?? '');
    expect(params.get('settings_tab')).toBe('about');
    expect(params.get('extra')).toBe('1');
    expect(params.get('view')).toBe('settings-appearance');
    fireEvent.click(screen.getByText('History back'));
    expect(screen.getByRole('button', { name: 'Show Notifications settings' }).getAttribute('aria-pressed')).toBe('true');
    expect((screen.getByLabelText('Receive email alerts') as HTMLInputElement).checked).toBe(true);
    expect(getPreferences().emailNotif).toBe(false);
    fireEvent.click(screen.getByText('History forward'));
    expect(screen.getByRole('button', { name: 'Show About settings' }).getAttribute('aria-pressed')).toBe('true');
  });

  it('falls back to Appearance for an unknown tab without applying preferences', () => {
    render(<MemoryRouter initialEntries={['/?view=settings-appearance&settings_tab=invalid']}><Settings /></MemoryRouter>);
    expect(screen.getByRole('button', { name: 'Show Appearance settings' }).getAttribute('aria-pressed')).toBe('true');
    expect(getPreferences().emailNotif).toBe(false);
  });
});

describe('Settings draft and commit', () => {
  it('does not persist a draft, then saves and can revert compact mode', () => {
    render(<Settings />);
    const compact = screen.getByLabelText('Enable compact layout');
    fireEvent.click(compact);
    expect(getPreferences().compact).toBe(false);
    expect(screen.getByText('Unsaved changes')).toBeTruthy();

    fireEvent.click(screen.getByRole('button', { name: 'Save appearance settings' }));
    expect(getPreferences().compact).toBe(true);
    expect(document.documentElement.getAttribute('data-compact')).toBe('true');
    expect(screen.getByRole('dialog', { name: 'Keep compact layout?' }).parentElement).toBe(document.body);

    fireEvent.click(screen.getByRole('button', { name: 'Revert compact layout' }));
    expect(getPreferences().compact).toBe(false);
    expect(document.documentElement.hasAttribute('data-compact')).toBe(false);
  });

  it('resets only the active tab after confirmation', () => {
    vi.spyOn(window, 'confirm').mockReturnValue(true);
    render(<Settings />);
    fireEvent.click(screen.getByRole('button', { name: 'Show Notifications settings' }));
    fireEvent.click(screen.getByLabelText('Receive email alerts'));
    fireEvent.click(screen.getByRole('button', { name: 'Save notification settings' }));
    expect(getPreferences().emailNotif).toBe(true);
    fireEvent.click(screen.getByRole('button', { name: 'Reset notification settings' }));
    expect(getPreferences().emailNotif).toBe(false);
    expect(getPreferences().theme).toBe('light');
  });
});
