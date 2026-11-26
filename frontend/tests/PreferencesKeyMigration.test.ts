/**
 * ARCH-03 (ai-launchpad -> S-A-I-L) localStorage key migration.
 *
 * The preferences module renamed its raw localStorage keys from
 * `ai-launchpad-*` to `sail-*` (2026-10-16). A one-time migration in
 * `load()` copies any surviving legacy value onto the new key and removes
 * the legacy key, so existing users keep their settings across the rename.
 *
 * The module caches state on first `load()` (module singleton), so each test
 * uses a fresh module import (vi.resetModules + dynamic import) with a clean
 * in-memory localStorage.
 *
 * Node >= 25 ships a global `localStorage` that is undefined unless
 * --localstorage-file is given, and it shadows jsdom's Storage under vitest
 * (same class as the UXAudit014 root cause) — install an in-memory stub so
 * the test is independent of the Node version.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { cleanup } from '@testing-library/react';

function installStorageStub() {
  const store = new Map<string, string>();
  vi.stubGlobal('localStorage', {
    getItem: (k: string) => (store.has(k) ? store.get(k)! : null),
    setItem: (k: string, v: string) => { store.set(k, String(v)); },
    removeItem: (k: string) => { store.delete(k); },
    clear: () => { store.clear(); },
  });
}

beforeEach(() => {
  installStorageStub();
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.resetModules();
});

async function freshPrefs() {
  vi.resetModules();
  const mod = await import('../src/lib/preferences');
  return mod;
}

describe('ARCH-03 localStorage legacy-key migration', () => {
  it('copies a legacy theme value onto the new key and removes the legacy key', async () => {
    localStorage.setItem('ai-launchpad-theme', 'dark');
    localStorage.setItem('ai-launchpad-sidebar-collapsed', 'true');

    const { getPreferences } = await freshPrefs();

    const p = getPreferences();
    expect(p.theme).toBe('dark');
    expect(p.sidebarCollapsed).toBe(true);
    // New keys now hold the migrated values.
    expect(localStorage.getItem('sail-theme')).toBe('dark');
    expect(localStorage.getItem('sail-sidebar-collapsed')).toBe('true');
    // Legacy keys are cleaned up.
    expect(localStorage.getItem('ai-launchpad-theme')).toBeNull();
    expect(localStorage.getItem('ai-launchpad-sidebar-collapsed')).toBeNull();
  });

  it('does not overwrite an existing new key when a legacy value also exists', async () => {
    localStorage.setItem('ai-launchpad-theme', 'light');
    localStorage.setItem('sail-theme', 'dark'); // user already on the new key

    const { getPreferences } = await freshPrefs();

    // The new key wins (dark); the legacy key is still cleaned up.
    expect(getPreferences().theme).toBe('dark');
    expect(localStorage.getItem('sail-theme')).toBe('dark');
    expect(localStorage.getItem('ai-launchpad-theme')).toBeNull();
  });

  it('leaves storage untouched when no legacy keys exist (clean first run)', async () => {
    const { getPreferences } = await freshPrefs();
    expect(getPreferences().theme).toBe('light'); // default
    // No spurious new/legacy keys created just by loading.
    expect(localStorage.getItem('sail-theme')).toBeNull();
    expect(localStorage.getItem('ai-launchpad-theme')).toBeNull();
  });
});

it('retains appearance on reload in the same browser, but defaults in another browser', async () => {
  const prefs = await freshPrefs();
  prefs.setPreference('theme', 'dark');
  prefs.setPreference('fontSize', 'small');
  expect((await freshPrefs()).getPreferences()).toMatchObject({ theme: 'dark', fontSize: 'small' });
  installStorageStub(); // Independent browser storage, without a database reseed.
  expect((await freshPrefs()).getPreferences()).toMatchObject({ theme: 'light', fontSize: 'medium' });
});
