import { getAuthToken, getAuthUsername } from './auth';
import { activatePreferenceAccount, applyAppearance, getPreferences, setPreference } from './preferences';

let persistedToken: string | null = null;
export function needsAccountAppearanceSave(): boolean {
  const token = getAuthToken();
  return !!token && persistedToken !== token;
}
export interface AccountAppearance { theme: 'light' | 'dark'; fontSize: 'small' | 'medium' | 'large' }
function valid(value: unknown): value is AccountAppearance {
  const v = value as AccountAppearance | null;
  return !!v && ['light', 'dark'].includes(v.theme) && ['small', 'medium', 'large'].includes(v.fontSize);
}
export async function synchronizeAppearance(): Promise<void> {
  const token = getAuthToken();
  const username = getAuthUsername();
  if (!token) return;
  activatePreferenceAccount(username);
  const response = await fetch('/api/preferences/appearance/', { signal: AbortSignal.timeout(5000), headers: { Authorization: `Bearer ${token}` } });
  if (!response.ok) throw new Error('Account appearance unavailable');
  const { appearance } = await response.json();
  if (token !== getAuthToken() || username !== getAuthUsername()) return;
  if (appearance === null) return; // Keep this account's local settings until explicitly saved.
  if (!valid(appearance)) throw new Error('Invalid account appearance');
  persistedToken = token;
  setPreference('theme', appearance.theme);
  setPreference('fontSize', appearance.fontSize);
  applyAppearance(getPreferences());
}
export async function saveAccountAppearance(): Promise<void> {
  const token = getAuthToken();
  if (!token) return;
  const { theme, fontSize } = getPreferences();
  const response = await fetch('/api/preferences/appearance/', {
    method: 'PUT', signal: AbortSignal.timeout(5000), headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
    body: JSON.stringify({ theme, fontSize }),
  });
  if (!response.ok) throw new Error('Saved on this browser only. Account sync failed; try saving again.');
  if (token === getAuthToken()) persistedToken = token;
}
