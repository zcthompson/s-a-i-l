import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { activatePreferenceAccount, getPreferences, setPreference } from '../src/lib/preferences';
import { setAuth, clearAuth } from '../src/lib/auth';
import { needsAccountAppearanceSave, saveAccountAppearance, synchronizeAppearance } from '../src/lib/accountAppearance';

beforeEach(() => {
  const store = new Map<string, string>();
  vi.stubGlobal('localStorage', { getItem: (key: string) => store.get(key) ?? null, setItem: (key: string, v: string) => store.set(key, v), removeItem: (key: string) => store.delete(key) });
  clearAuth();
  activatePreferenceAccount('');
});
afterEach(() => { clearAuth(); vi.unstubAllGlobals(); });

it('loads account settings and keeps compact local', async () => {
  setAuth('token-a', 'alice', false, 'user');
  setPreference('compact', true);
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({ appearance: { theme: 'dark', fontSize: 'small' } }))));
  await synchronizeAppearance();
  expect(getPreferences()).toMatchObject({ theme: 'dark', fontSize: 'small', compact: true });
  expect(document.documentElement.dataset.theme).toBe('dark');
  await saveAccountAppearance();
  expect(JSON.parse((vi.mocked(fetch).mock.calls[1][1] as RequestInit).body as string)).toEqual({ theme: 'dark', fontSize: 'small' });
});
it('isolates user caches and ignores responses from the previous login', async () => {
  setAuth('token-a', 'alice', false, 'user');
  setPreference('theme', 'dark');
  let resolve!: (r: Response) => void;
  vi.stubGlobal('fetch', vi.fn(() => new Promise<Response>(r => { resolve = r; })));
  const pending = synchronizeAppearance();
  setAuth('token-b', 'bob', false, 'user');
  expect(getPreferences().theme).toBe('light');
  resolve(new Response(JSON.stringify({ appearance: { theme: 'dark', fontSize: 'small' } })));
  await pending;
  expect(getPreferences().theme).toBe('light');
  activatePreferenceAccount('alice');
  expect(getPreferences().theme).toBe('dark');
});
it('retains local settings on an outage and reports failed account saves', async () => {
  setAuth('token-a', 'alice', false, 'user');
  setPreference('theme', 'dark');
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('{}', { status: 503 })));
  await expect(synchronizeAppearance()).rejects.toThrow('unavailable');
  expect(getPreferences().theme).toBe('dark');
  await expect(saveAccountAppearance()).rejects.toThrow('browser only');
});

it('allows first-time saving even if local values already match the form', async () => {
  setAuth('unsaved-token', 'new-account', false, 'user');
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({ appearance: null }))));
  await synchronizeAppearance();
  expect(needsAccountAppearanceSave()).toBe(true);
  await saveAccountAppearance();
  expect(needsAccountAppearanceSave()).toBe(false);
});
