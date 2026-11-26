import { activatePreferenceAccount } from './preferences';
/**
 * Centralized auth state module.
 *
 * Replaces all direct localStorage usage for auth state. Auth tokens,
 * username, and admin flag are stored in a single module and exposed via
 * getter / setter functions so that every file reads/writes through the
 * same module — never localStorage directly.
 */

/** Raw auth values kept in memory. */
let _token: string | null = null;
let _username: string | null = null;
let _isAdmin: boolean | null = null;
let _role = 'user';
let _salesRole: string | null = null;

// Initialise from localStorage only at import time (one-shot)
if (typeof localStorage !== 'undefined') {
  try { _token = localStorage.getItem('auth_token'); } catch { /* */ }
  try { _username = localStorage.getItem('username'); } catch { /* */ }
  try { _isAdmin = localStorage.getItem('user_is_admin') === 'true'; } catch { /* */ }
  try { _role = localStorage.getItem('user_role') || 'user'; } catch { /* */ }
  try { _salesRole = localStorage.getItem('user_sales_role'); } catch { /* */ }
}

/** Set auth token, username, admin flag, global role, and sales role (called after login). */
export function setAuth(token: string, username: string, isAdmin: boolean, role: string, salesRole: string | null = null): void {
  activatePreferenceAccount(username);
  _token = token;
  _username = username;
  _isAdmin = isAdmin;
  _role = role || 'user';
  _salesRole = salesRole;
  try { localStorage.setItem('auth_token', token); } catch { /* */ }
  try { localStorage.setItem('username', username); } catch { /* */ }
  try { localStorage.setItem('user_is_admin', String(isAdmin)); } catch { /* */ }
  try { localStorage.setItem('user_role', _role); } catch { /* */ }
  try { if (salesRole) { localStorage.setItem('user_sales_role', salesRole); } else { localStorage.removeItem('user_sales_role'); } } catch { /* */ }
}

/** Clear all auth state (called after logout or 401). */
export function clearAuth(): void {
  _token = null;
  _username = null;
  _isAdmin = null;
  _role = 'user';
  _salesRole = null;
  try { localStorage.removeItem('auth_token'); } catch { /* */ }
  try { localStorage.removeItem('username'); } catch { /* */ }
  try { localStorage.removeItem('user_is_admin'); } catch { /* */ }
  try { localStorage.removeItem('user_role'); } catch { /* */ }
  try { localStorage.removeItem('user_sales_role'); } catch { /* */ }
}

/** Get the current auth token. */
export function getAuthToken(): string | null {
  return _token;
}

/** Get the current auth username. */
export function getAuthUsername(): string {
  return _username || '';
}

/** Get the current auth admin flag. */
export function getAuthIsAdmin(): boolean {
  return _isAdmin === true;
}

/** Get the caller's global role (admin, user, auditor, or ps_admin). */
export function getAuthRole(): string {
  return _role || 'user';
}

/** Get the caller's sales role (rep/inside_sales/sales_manager/sales_ops/auditor/sales_admin) or null. */
export function getAuthSalesRole(): string | null {
  return _salesRole;
}

/** Get the current auth state (re-computed from internal state). */
export function getAuthState() {
  return {
    username: getAuthUsername(),
    isAdmin: getAuthIsAdmin(),
    role: getAuthRole(),
    salesRole: getAuthSalesRole(),
    isAuthenticated: _token !== null,
  };
}

/** Refresh the in-memory auth snapshot after another tab changes storage. */
export function syncAuthFromStorage(): void {
  if (typeof localStorage === 'undefined') return;
  try { _token = localStorage.getItem('auth_token'); } catch { _token = null; }
  try { _username = localStorage.getItem('username'); } catch { _username = null; }
  try { _isAdmin = localStorage.getItem('user_is_admin') === 'true'; } catch { _isAdmin = null; }
  try { _role = localStorage.getItem('user_role') || 'user'; } catch { _role = 'user'; }
  try { _salesRole = localStorage.getItem('user_sales_role'); } catch { _salesRole = null; }
}

if (typeof window !== 'undefined') {
  window.addEventListener('storage', (event) => {
    if (event.key !== 'auth_token') return;
    syncAuthFromStorage();
    if (!event.newValue) {
      try { window.sessionStorage.removeItem('sail_session_return'); } catch { /* */ }
      window.location.assign('/login');
    } else if (event.newValue !== event.oldValue) {
      window.location.reload();
    }
  });
}
