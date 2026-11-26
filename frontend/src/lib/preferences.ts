/**
 * Centralized settings preferences module.
 *
 * Replaces all direct localStorage usage for user preferences.
 * Preferences are stored in a single module so every file reads/writes
 * through the same interface — never localStorage directly.
 *
 * Theme/text size synchronize through accountAppearance; density stays local.
 */

export type ThemeMode = 'light' | 'dark';
export type NotifPreference = 'all' | 'important' | 'none';

export interface PreferencesState {
  theme: ThemeMode;
  fontSize: string;
  compact: boolean;
  notifPref: NotifPreference;
  emailNotif: boolean;
  websocketNotif: boolean;
  // UX audit #7: sidebar collapsed preference — the one setting most likely to
  // be set deliberately (rail width) was the only appearance pref not persisted.
  sidebarCollapsed: boolean;
}

const DEFAULTS: PreferencesState = {
  theme: 'light',
  fontSize: 'medium',
  compact: false,
  notifPref: 'all',
  emailNotif: false,
  websocketNotif: true,
  sidebarCollapsed: false,
};

const STORAGE_KEYS: Record<keyof PreferencesState, string> = {
  theme: 'sail-theme',
  fontSize: 'sail-fontsize',
  compact: 'sail-compact',
  notifPref: 'sail-notif-pref',
  emailNotif: 'sail-email-notif',
  websocketNotif: 'sail-websocket-notif',
  sidebarCollapsed: 'sail-sidebar-collapsed',
};

/** ARCH-03 (ai-launchpad → S-A-I-L): the pre-rename localStorage keys. A
 *  one-time migration reads these so existing users keep their settings
 *  after the rename; each is removed after being migrated. */
const LEGACY_STORAGE_KEYS: Record<keyof PreferencesState, string> = {
  theme: 'ai-launchpad-theme',
  fontSize: 'ai-launchpad-fontsize',
  compact: 'ai-launchpad-compact',
  notifPref: 'ai-launchpad-notif-pref',
  emailNotif: 'ai-launchpad-email-notif',
  websocketNotif: 'ai-launchpad-websocket-notif',
  sidebarCollapsed: 'ai-launchpad-sidebar-collapsed',
};

function migrateLegacyKeys(): void {
  if (typeof localStorage === 'undefined') return;
  (Object.keys(LEGACY_STORAGE_KEYS) as (keyof PreferencesState)[]).forEach((key) => {
    const newKey = STORAGE_KEYS[key];
    const legacyKey = LEGACY_STORAGE_KEYS[key];
    if (localStorage.getItem(newKey) === null) {
      const legacy = localStorage.getItem(legacyKey);
      if (legacy !== null) localStorage.setItem(newKey, legacy);
    }
    localStorage.removeItem(legacyKey);
  });
}

const BOOLEAN_KEYS: Record<string, boolean> = {
  compact: true,
  emailNotif: true,
  websocketNotif: true,
  sidebarCollapsed: true,
};

let _state: PreferencesState = { ...DEFAULTS };
let _initialized = false;
let _owner = '';
const appearanceKeys = ['theme', 'fontSize'] as const;
function ownerKey(owner: string, key: string) { return `sail-appearance:${encodeURIComponent(owner)}:${key}`; }

/** Reload appearance for the active account; never inherit a different user's cache. */
export function activatePreferenceAccount(owner: string): void {
  load();
  if (_owner === owner) return;
  _owner = owner;
  _state.theme = DEFAULTS.theme;
  _state.fontSize = DEFAULTS.fontSize;
  try {
    const theme = localStorage.getItem(ownerKey(owner, 'theme'));
    const fontSize = localStorage.getItem(ownerKey(owner, 'fontSize'));
    if (theme === 'light' || theme === 'dark') _state.theme = theme;
    if (fontSize === 'small' || fontSize === 'medium' || fontSize === 'large') _state.fontSize = fontSize;
  } catch { /* defaults remain available */ }
  applyAppearance(_state);
}


function load(): PreferencesState {
  if (_initialized) return _state;
  _initialized = true;
  if (typeof localStorage === 'undefined') return _state;
  try {
    migrateLegacyKeys();
    const t = localStorage.getItem(STORAGE_KEYS.theme);
    if (t === 'dark' || t === 'light') _state.theme = t;
    const f = localStorage.getItem(STORAGE_KEYS.fontSize);
    if (f === 'small' || f === 'medium' || f === 'large') _state.fontSize = f;
    const c = localStorage.getItem(STORAGE_KEYS.compact);
    if (c === 'true') _state.compact = true;
    const n = localStorage.getItem(STORAGE_KEYS.notifPref);
    if (n === 'all' || n === 'important' || n === 'none') _state.notifPref = n as NotifPreference;
    const e = localStorage.getItem(STORAGE_KEYS.emailNotif);
    if (e === 'true') _state.emailNotif = true;
    const w = localStorage.getItem(STORAGE_KEYS.websocketNotif);
    if (w === 'false') _state.websocketNotif = false;
    const s = localStorage.getItem(STORAGE_KEYS.sidebarCollapsed);
    if (s === 'true') _state.sidebarCollapsed = true;
  } catch { /* storage unavailable — keep defaults */ }
  try {
    _owner = localStorage.getItem('username') || '';
    const migrationOwner = localStorage.getItem('sail-appearance-migrated-owner');
    if (_owner && !migrationOwner) {
      for (const key of appearanceKeys) localStorage.setItem(ownerKey(_owner, key), String(_state[key]));
      localStorage.setItem('sail-appearance-migrated-owner', _owner);
    }
    if (_owner) {
      const owner = _owner;
      _owner = '\0';
      activatePreferenceAccount(owner);
    }
  } catch { /* local cache is optional */ }
  return _state;
}

function save(key: keyof PreferencesState, value: string | boolean): void {
  load();
  const strVal = typeof value === 'boolean' ? String(value) : String(value);
  // biome-ignore lint/suspicious/noExplicitAny: PreferencesState keys are validated
  (_state as Record<string, any>)[key] = BOOLEAN_KEYS[key as string] ? (strVal === 'true') : strVal;
  try {
    localStorage.setItem(STORAGE_KEYS[key], strVal);
    if (_owner && (key === 'theme' || key === 'fontSize')) localStorage.setItem(ownerKey(_owner, key), strVal);
  } catch { /* storage unavailable */ }
}

function remove(key: keyof PreferencesState): void {
  load();
  // biome-ignore lint/suspicious/noExplicitAny: PreferencesState keys are validated
  (_state as Record<string, any>)[key] = DEFAULTS[key];
  try {
    localStorage.removeItem(STORAGE_KEYS[key]);
    if (_owner && (key === 'theme' || key === 'fontSize')) localStorage.removeItem(ownerKey(_owner, key));
  } catch { /* storage unavailable */ }
}

/** Get all current preferences. */
export function getPreferences(): PreferencesState {
  load();
  return { ..._state };
}

/** Apply appearance preferences to the document without persisting them. */
export function applyAppearance(prefs: Pick<PreferencesState, 'theme' | 'fontSize' | 'compact'>): void {
  if (typeof document === 'undefined') return;
  document.documentElement.setAttribute('data-theme', prefs.theme);
  document.documentElement.setAttribute('data-fontsize', prefs.fontSize);
  if (prefs.compact) document.documentElement.setAttribute('data-compact', 'true');
  else document.documentElement.removeAttribute('data-compact');
}

/** Set a single preference and persist it. */
export function setPreference(key: keyof PreferencesState, value: string | boolean): void {
  save(key, value);
}

/** Remove a single preference (revert to default). */
export function removePreference(key: keyof PreferencesState): void {
  remove(key);
}

/** Reset all preferences to defaults. */
export function resetPreferences(): void {
  _state = { ...DEFAULTS };
  if (typeof localStorage === 'undefined') return;
  try {
    for (const key of Object.keys(STORAGE_KEYS) as Array<keyof PreferencesState>) {
      localStorage.removeItem(STORAGE_KEYS[key]);
      if (_owner && (key === 'theme' || key === 'fontSize')) localStorage.removeItem(ownerKey(_owner, key));
    }
  } catch { /* storage unavailable */ }
}
