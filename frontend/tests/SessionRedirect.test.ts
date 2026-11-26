/**
 * session-expiry return destination.
 *
 * The api-layer 401 handler preserves the current internal destination
 * (pathname+search+hash) in sessionStorage and Login returns to it. These
 * helpers are the security-critical part: they must accept only INTERNAL
 * destinations (no open redirect / protocol-relative / cross-origin), and
 * round-trip a single destination through save→consume.
 */
import { describe, it, expect, beforeEach } from 'vitest';
import { isInternalPath, saveSessionReturn, consumeSessionReturn } from '../src/lib/sessionRedirect';

describe('FE-08 session-redirect destination safety', () => {
  beforeEach(() => {
    window.sessionStorage.clear();
  });

  it('accepts clean internal relative paths with query + hash', () => {
    expect(isInternalPath('/')).toBe(true);
    expect(isInternalPath('/?view=customers&customer=Acme')).toBe(true);
    expect(isInternalPath('/customers/Acme#overview')).toBe(true);
  });

  it('rejects external + protocol-relative + smuggled destinations', () => {
    expect(isInternalPath('https://evil.example/x')).toBe(false);
    expect(isInternalPath('http://evil.example')).toBe(false);
    expect(isInternalPath('//evil.example')).toBe(false);
    expect(isInternalPath('javascript:alert(1)')).toBe(false);
    expect(isInternalPath('/https://evil.example')).toBe(false);
    expect(isInternalPath('')).toBe(false);
  });

  it('save then consume round-trips one internal destination', () => {
    window.history.replaceState({}, '', '/?view=customers&customer=Acme#tech');
    expect(saveSessionReturn()).toBe(true);
    expect(consumeSessionReturn()).toBe('/?view=customers&customer=Acme#tech');
    // Consumed (single-use): a second read returns null.
    expect(consumeSessionReturn()).toBeNull();
  });

  it('consume returns null when nothing was stored', () => {
    expect(consumeSessionReturn()).toBeNull();
  });

  it('rejects a stored external destination on consume (defensive)', () => {
    window.sessionStorage.setItem('sail_session_return', 'https://evil.example/x');
    expect(consumeSessionReturn()).toBeNull();
  });
});
