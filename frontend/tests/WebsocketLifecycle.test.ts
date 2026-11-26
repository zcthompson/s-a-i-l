/**
 * notification socket lifecycle & subscription cleanup.
 *
 * Covers the acceptance scenarios: deliberate disconnect,
 * repeated mount/unmount, initial network failure, reconnect failure,
 * successful recovery, 4401 (non-retryable), silent handshake (a timeout is
 * a FAILURE, not an authenticated success), and concurrent connects.
 * Asserts one handler invocation per event, no reconnect after logout, no
 * unresolved connect promises, and no runaway timers.
 *
 * Deterministic: fake WebSocket + fake timers (no real network, no real 5s
 * waits). The module-level singleton is NOT used — a fresh instance per test.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { NotificationWebSocket } from '../src/lib/websocket';

vi.mock('../src/lib/auth', () => ({
  getAuthToken: () => 'fake-jwt',
}));

// ── Fake WebSocket ───────────────────────────────────────────────────────────
type ReadyState = number;
class FakeWebSocket {
  static instances: FakeWebSocket[] = [];
  static CONNECTING = 0;
  static OPEN = 1;
  static CLOSING = 2;
  static CLOSED = 3;
  readyState: ReadyState = FakeWebSocket.CONNECTING;
  closed = false;
  sent: string[] = [];
  onopen: ((ev?: unknown) => void) | null = null;
  onclose: ((ev: { code: number }) => void) | null = null;
  onerror: ((ev?: unknown) => void) | null = null;
  onmessage: ((ev: { data: string }) => void) | null = null;
  constructor(public url: string) {
    FakeWebSocket.instances.push(this);
  }
  send(data: string) {
    if (this.readyState !== FakeWebSocket.OPEN) throw new Error('not open');
    this.sent.push(data);
  }
  close() {
    if (this.closed) return;
    this.closed = true;
    this.readyState = FakeWebSocket.CLOSED;
    const cb = this.onclose;
    this.onclose = null;
    cb?.({ code: 1000 });
  }
  /** Test helper: drive a transition. */
  fireOpen() {
    this.readyState = FakeWebSocket.OPEN;
    this.onopen?.({});
  }
  fireMessage(data: string) {
    this.onmessage?.({ data });
  }
  fireClose(code: number) {
    this.closed = true;
    this.readyState = FakeWebSocket.CLOSED;
    const cb = this.onclose;
    this.onclose = null;
    cb?.({ code });
  }
  fireError() {
    this.onerror?.({});
  }
}

function lastSock() {
  return FakeWebSocket.instances[FakeWebSocket.instances.length - 1];
}
function connectCount() {
  return FakeWebSocket.instances.length;
}

/** Flush the microtask queue without depending on (fake) timers. */
async function microtask() {
  await vi.advanceTimersByTimeAsync(0);
}

beforeEach(() => {
  FakeWebSocket.instances = [];
  vi.useFakeTimers();
  // jsdom ships a real (unused) WebSocket; swap in the fake so `new
  // WebSocket(url)` in the module under test hits our deterministic class.
  // Save the original so afterEach can restore it — leaking the fake onto
  // globalThis would pollute LATER test files that use the real WebSocket.
  (globalThis as Record<string, unknown>).__origWebSocket = (globalThis as Record<string, unknown>).WebSocket;
  (globalThis as Record<string, unknown>).WebSocket = FakeWebSocket;
});

afterEach(() => {
  // CLEAR pending timers (do not RUN them — running reconnect backoff would
  // spawn more sockets mid-teardown and cascade). Restore the real WebSocket
  // global + real timers.
  vi.clearAllTimers();
  vi.useRealTimers();
  (globalThis as Record<string, unknown>).WebSocket = (globalThis as Record<string, unknown>).__origWebSocket;
  delete (globalThis as Record<string, unknown>).__origWebSocket;
});

async function waitForSettled(p: Promise<unknown>) {
  // Await via the guarded chain so an expected rejection does not throw
  // into the test body; a connect promise must never be left unresolved.
  await p.catch(() => undefined);
  await microtask();
}

describe('NotificationWebSocket lifecycle (FE-04)', () => {
  it('resolves the connect promise only on a pong-confirmed auth', async () => {
    const w = new NotificationWebSocket();
    const p = w.connect();
    const sock = lastSock();
    sock.fireOpen();
    // auth + ping sent on open
    expect(sock.sent[0]).toBe(JSON.stringify({ auth: 'fake-jwt' }));
    expect(sock.sent[1]).toBe('ping');
    // No pong yet — the promise must NOT have resolved.
    let settled = false;
    p.then(() => { settled = true; }).catch(() => { settled = true; });
    await vi.advanceTimersByTimeAsync(1000);
    await microtask();
    expect(settled).toBe(false);
    // Server answers the ping → authenticated success.
    sock.fireMessage('pong');
    await waitForSettled(p);
    expect(w.getState().connected).toBe(true);
    expect(w.getState().activeConnections).toBe(1);
    w.disconnect();
  });

  it('treats a silent authentication timeout as a FAILURE (rejects + retries)', async () => {
    const w = new NotificationWebSocket();
    const p = w.connect();
    let rejected = '';
    p.catch((e) => { rejected = e.message; });
    const sock = lastSock();
    sock.fireOpen();
    // Five seconds pass with no pong → the connect must reject, and the
    // socket be retried with backoff (not silently declared authenticated).
    await vi.advanceTimersByTimeAsync(5000);
    await microtask();
    expect(rejected).toContain('timed out');
    expect(w.getState().connected).toBe(false);
    // The server-side close (which a real silent server would produce)
    // drives the bounded retry — attempt 2 at ~1s.
    sock.fireClose(1006);
    await vi.advanceTimersByTimeAsync(1100);
    await microtask();
    expect(connectCount()).toBe(2);
    w.disconnect();
  });

  it('deliberate disconnect settles the pending promise and never reconnects', async () => {
    const w = new NotificationWebSocket();
    const p = w.connect();
    const sock = lastSock();
    sock.fireOpen();
    // Logout / teardown while the handshake is still pending.
    w.disconnect();
    await waitForSettled(p); // must settle — no unhandled/unresolved promise
    const before = connectCount();
    await vi.advanceTimersByTimeAsync(60_000);
    expect(connectCount()).toBe(before); // no reconnect after logout
    expect(w.getState().connected).toBe(false);
  });

  it('repeated mount/unmount (StrictMode) leaves no timers or handlers', async () => {
    const w = new NotificationWebSocket();
    let calls = 0;
    const handler = () => { calls++; };
    // Simulate React StrictMode: setup, cleanup, setup again.
    const unsub1 = w.subscribe('*', handler);
    const p1 = w.connect();
    p1.catch(() => undefined);
    unsub1();
    w.disconnect();
    const p2 = w.connect();
    p2.catch(() => undefined);
    const unsub2 = w.subscribe('*', handler);
    const sock = lastSock();
    sock.fireOpen();
    sock.fireMessage('pong');
    await vi.advanceTimersByTimeAsync(0);
    // A delivered event fires the handler exactly ONCE (the stale first
    // subscription was removed; only the live one remains).
    sock.fireMessage(JSON.stringify({ type: 'scoring', data: {}, timestamp: 't' }));
    expect(calls).toBe(1);
    // Teardown again.
    unsub2();
    w.disconnect();
    sock.fireMessage(JSON.stringify({ type: 'scoring', data: {}, timestamp: 't' }));
    expect(calls).toBe(1); // no invocation after unsubscribe
    const before = connectCount();
    await vi.advanceTimersByTimeAsync(120_000);
    expect(connectCount()).toBe(before); // no runaway reconnect timers
  });

  it('initial network failure retries with bounded backoff then recovers', async () => {
    const w = new NotificationWebSocket();
    const p = w.connect();
    p.catch(() => undefined);
    const s1 = lastSock();
    s1.fireError();
    s1.fireClose(1006); // transport failure (not 4401)
    // Attempt 1 retry at 1s…
    await vi.advanceTimersByTimeAsync(1100);
    await microtask();
    expect(connectCount()).toBe(2);
    const s2 = lastSock();
    s2.fireError();
    s2.fireClose(1006);
    // Attempt 2 retry at 2s (escalating, not reset)…
    await vi.advanceTimersByTimeAsync(2100);
    await microtask();
    expect(connectCount()).toBe(3);
    const s3 = lastSock();
    // Recovery: the third attempt authenticates.
    s3.fireOpen();
    s3.fireMessage('pong');
    expect(w.getState().connected).toBe(true);
    // Successful reset: a later failure backs off from the base delay again.
    s3.fireClose(1006);
    await vi.advanceTimersByTimeAsync(1100);
    await microtask();
    expect(connectCount()).toBe(4);
    w.disconnect();
  });

  it('stops after the bounded number of reconnect attempts', async () => {
    const w = new NotificationWebSocket();
    const p = w.connect();
    p.catch(() => undefined);
    // Drive 10 consecutive failures; after the max, no further reconnects.
    for (let i = 0; i < 10; i++) {
      const s = lastSock();
      s.fireError();
      s.fireClose(1006);
      const delay = 1000 * Math.pow(2, i);
      await vi.advanceTimersByTimeAsync(Math.min(delay + 200, 30_200));
      await microtask();
    }
    const atMax = connectCount();
    await vi.advanceTimersByTimeAsync(600_000);
    await microtask();
    expect(connectCount()).toBe(atMax); // exhausted — no more attempts
    w.disconnect();
  });

  it('4401 (rejected auth) is never retried', async () => {
    const w = new NotificationWebSocket();
    const p = w.connect();
    let rejected = '';
    p.catch((e) => { rejected = e.message; });
    const s1 = lastSock();
    s1.fireOpen();
    s1.fireClose(4401);
    await microtask();
    expect(rejected).toContain('4401');
    await vi.advanceTimersByTimeAsync(60_000);
    expect(connectCount()).toBe(1); // no reconnect after rejected auth
    w.disconnect();
  });

  it('concurrent connects deduplicate onto one pending promise', async () => {
    const w = new NotificationWebSocket();
    const p1 = w.connect();
    const p2 = w.connect(); // same in-flight connection
    expect(p1).toBe(p2);
    expect(connectCount()).toBe(1); // only ONE socket was created
    const sock = lastSock();
    sock.fireOpen();
    sock.fireMessage('pong');
    await waitForSettled(p1);
    await waitForSettled(p2);
    expect(w.getState().connected).toBe(true);
    // A connect on the now-OPEN socket resolves immediately, no new socket.
    const before = connectCount();
    await waitForSettled(w.connect());
    expect(connectCount()).toBe(before);
    w.disconnect();
  });

  it('one handler invocation per event, per subscription', async () => {
    const w = new NotificationWebSocket();
    let a = 0;
    let b = 0;
    const unsubA = w.subscribe('*', () => { a++; });
    const unsubB = w.subscribe('scoring', () => { b++; });
    const p = w.connect();
    p.catch(() => undefined);
    const sock = lastSock();
    sock.fireOpen();
    sock.fireMessage('pong');
    sock.fireMessage(JSON.stringify({ type: 'scoring', data: {}, timestamp: 't' }));
    sock.fireMessage(JSON.stringify({ type: 'comment', data: {}, timestamp: 't' }));
    expect(a).toBe(2); // wildcard sees both events
    expect(b).toBe(1); // typed handler sees only 'scoring'
    unsubA();
    unsubB();
    w.disconnect();
  });
});
