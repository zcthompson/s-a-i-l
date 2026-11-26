/**
 * Session-expiry redirect helpers (FE-08, part 48).
 *
 * A protected API returning 401 (session expired) must send the user to
 * /login AND preserve the exact internal destination they were at (pathname,
 * search, hash) so signing back in returns them there. The hard
 * `window.location.href = '/login'` clears router state, so the destination
 * is carried in sessionStorage (which survives the reload) and consumed once
 * after a successful login.
 *
 * Invariants:
 * - Only INTERNAL destinations are accepted/returned — external origins and
 *   protocol-relative (`//host/…`) URLs are rejected (no open redirect).
 * - Simultaneous 401s collapse into one transition (the first stores the
 *   destination + navigates; the rest just throw without a second redirect).
 * - Credential failures on the login form never trigger this (they stay on
 *   /login).
 */

const SESSION_RETURN_KEY = 'sail_session_return';
const SESSION_EXPIRED_KEY = 'sail_session_expired';

/** A destination is internal iff it has no scheme/authority (relative) or,
 * when absolute, the same-origin http(s) form. Rejects protocol-relative and
 * cross-origin URLs. */
export function isInternalPath(path: string): boolean {
  if (!path || path.startsWith('//')) return false; // empty / protocol-relative
  // Already a clean relative path (optional ?#/).
  if (path.startsWith('/')) {
    // Guard against "/http://…" style smuggling.
    return !path.slice(1).match(/^[a-z][a-z0-9+.-]*:/i);
  }
  if (/^https?:\/\//i.test(path)) {
    try {
      const u = new URL(path);
      return u.origin === window.location.origin;
    } catch {
      return false;
    }
  }
  return false; // bare relative (e.g. "foo/bar") — treat as not a valid return
}

/** Capture the current internal destination for the post-login return.
 *  Returns true if a valid destination was stored. */
export function saveSessionReturn(): boolean {
  const dest = window.location.pathname + window.location.search + window.location.hash;
  if (!isInternalPath(dest)) return false;
  try {
    window.sessionStorage.setItem(SESSION_RETURN_KEY, dest);
    return true;
  } catch {
    return false; // storage unavailable (private mode) — fall back to "/"
  }
}

/** Read AND clear the stored destination. Returns a validated internal path
 *  or null (so the caller defaults to "/"). */
export function consumeSessionReturn(): string | null {
  let dest: string | null = null;
  try {
    dest = window.sessionStorage.getItem(SESSION_RETURN_KEY);
    window.sessionStorage.removeItem(SESSION_RETURN_KEY);
  } catch {
    return null;
  }
  return dest && isInternalPath(dest) ? dest : null;
}

export function clearSessionReturn(): void {
  try { window.sessionStorage.removeItem(SESSION_RETURN_KEY); } catch { /* storage unavailable */ }
}

export function markSessionExpired(): void {
  try { window.sessionStorage.setItem(SESSION_EXPIRED_KEY, 'true'); } catch { /* storage unavailable */ }
}

export function consumeSessionExpired(): boolean {
  try {
    const expired = window.sessionStorage.getItem(SESSION_EXPIRED_KEY) === 'true';
    window.sessionStorage.removeItem(SESSION_EXPIRED_KEY);
    return expired;
  } catch {
    return false;
  }
}

/** True if a session-return redirect is already in flight (dedups
 *  simultaneous 401s). Resets on the next document load (fresh module). */
let redirectInFlight = false;
export function beginSessionRedirect(): boolean {
  if (redirectInFlight) return false; // a second simultaneous 401 — skip
  redirectInFlight = true;
  return true;
}

/** Re-arm expiry handling after a successful in-document sign-in. */
export function resetSessionRedirect(): void {
  redirectInFlight = false;
}
