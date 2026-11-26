/**
 * WebSocket manager for real-time notifications.
 * Handles connection, reconnection, heartbeat, and message routing.
 *
 * Auth: browsers cannot set headers on a WebSocket handshake, so the JWT is
 * sent as the first message after connecting. The server closes with code
 * 4401 if the token is missing/invalid — we do not reconnect in that case.
 *
 * Lifecycle invariants (FE-04):
 * - **Intentional shutdown is modeled separately from connection failure.**
 *   `disconnect()` cancels every timer, settles any pending connect promise,
 *   and detaches the socket so its stale callbacks can never affect a newer
 *   connection (socket generations are validated on every callback).
 * - **Bounded backoff escalates across failed attempts** and resets only
 *   after an *authenticated* (pong-confirmed) success. A fresh programmatic
 *   `connect()` also resets it; reconnects do NOT, so a flapping server is
 *   backed off rather than hammered at the minimum delay.
 * - **A silent authentication timeout is a failure, not a success.** The
 *   connect promise resolves only when the server proves the socket is
 *   authenticated (it answers our `ping` with `pong`, see
 *   backend/routes/notifications.py). If five seconds pass silently the
 *   promise rejects and the socket is retried with backoff.
 * - **Concurrent connects deduplicate**: a second connect while the first is
 *   still in flight returns the same pending promise instead of racing it.
 */
import { getAuthToken } from './auth';

type MessageHandler = (data: { type: string; data: unknown; timestamp: string }) => void;

interface ConnectOptions {
  useCaseId?: string;
}

interface WebSocketState {
  connected: boolean;
  activeConnections: number;
}

/** Raised when the pending connect is settled by intentional teardown. */
export class WebSocketDisconnectedError extends Error {
  constructor() {
    super('WebSocket disconnected');
    this.name = 'WebSocketDisconnectedError';
  }
}

interface PendingConnect {
  epoch: number;
  resolve: () => void;
  reject: (err: Error) => void;
}

export class NotificationWebSocket {
  private ws: WebSocket | null = null;
  private handlers: Map<string, MessageHandler[]> = new Map();
  private state: WebSocketState = {
    connected: false,
    activeConnections: 0,
  };
  private _reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private heartbeatTimer: ReturnType<typeof setInterval> | null = null;
  private authHandshakeTimer: ReturnType<typeof setTimeout> | null = null;
  private reconnectAttempts: number = 0;
  private maxReconnectAttempts = 10;
  private reconnectDelay = 1000;
  /** Options of the most recent connect() — reconnects preserve them so a
   *  reconnect keeps the use_case_id subscription of the original connect. */
  private lastOptions: ConnectOptions = {};
  /** Pending connect settlement — a silent auth timeout or a pre-auth close
   *  must REJECT it, never leave it unresolved. */
  private pending: PendingConnect | null = null;
  /** True while disconnect() is tearing down — onclose must not reconnect. */
  private manualClose: boolean = false;
  /** Socket generation token: every callback validates its own epoch so a
   *  stale socket's handlers never touch the state of a newer connection. */
  private epoch: number = 0;
  /** In-flight connect promise (kept in sync with `pending` synchronously —
   *  a `.finally()` cleanup would only clear it after a microtask, letting
   *  a rapid teardown+reconnect dedup onto a dead promise). */
  private connectPromise: Promise<void> | null = null;

  constructor() {
    // Backend path (must match backend/routes/notifications.py); the Vite
    // dev server proxies /api/* (including WS upgrades) to the backend.
    this.wsUrl = '/api/notifications/ws/notifications';
  }

  private wsUrl: string;

  getState(): WebSocketState {
    return { ...this.state };
  }

  connect(options: ConnectOptions = {}): Promise<void> {
    this.lastOptions = options;
    // A fresh programmatic connect resets the backoff counter. Reconnects
    // (scheduleReconnect → _doConnect) do NOT, so the delay escalates
    // across failed attempts and only an authenticated success (or a new
    // programmatic connect) resets it.
    this.reconnectAttempts = 0;
    return this._doConnect(options);
  }

  private _doConnect(options: ConnectOptions): Promise<void> {
    // Deduplicate / serialize simultaneous connects: an OPEN socket resolves
    // immediately; a still-pending connect returns the SAME promise (the old
    // code closed the pending socket and raced a second connection against
    // it, orphaning the first promise).
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      this.state.activeConnections++;
      return Promise.resolve();
    }
    if (this.connectPromise) {
      return this.connectPromise;
    }

    // Close any leftover non-open socket and detach its callbacks so they
    // cannot fire into the new connection's state.
    if (this.ws) {
      this._detach(this.ws);
      this._closeQuiet(this.ws);
      this.ws = null;
    }

    const epoch = ++this.epoch;
    this.manualClose = false;

    const token = getAuthToken();
    if (!token) {
      // The server would close with 4401 — fail fast, no socket created,
      // nothing in flight (so nothing is registered in pending/
      // connectPromise and the next connect starts clean).
      return Promise.reject(
        new Error('No auth token available for the WebSocket handshake'),
      );
    }

    // The `new Promise` executor runs synchronously, so `pending` is live
    // the moment connect() begins and `connectPromise` is assigned before
    // any other connect() in the same task can observe it — that makes the
    // dedup check at the top of _doConnect safe.
    const promise = new Promise<void>((resolve, reject) => {
      this.pending = { epoch, resolve, reject };
      try {
        const url = options.useCaseId
          ? `${this.wsUrl}?use_case_id=${encodeURIComponent(options.useCaseId)}`
          : this.wsUrl;
        const socket = new WebSocket(url);
        this.ws = socket;

        socket.onopen = () => {
          if (epoch !== this.epoch) return; // obsolete socket
          // Authenticate first (browsers cannot set headers on a WS
          // handshake), then prove the socket is alive + authenticated.
          try {
            socket.send(JSON.stringify({ auth: token }));
            socket.send('ping');
          } catch {
            /* connection dropped before send — onclose handles it */
          }
          this.state.activeConnections = 1;
          // A SILENT timeout is not authenticated success: the server must
          // answer the ping with a pong (backend/routes/notifications.py).
          // If five seconds pass without it, fail the connect, drop the
          // socket, and retry with bounded backoff rather than declaring the
          // session alive.
          this.authHandshakeTimer = setTimeout(() => {
            if (epoch !== this.epoch) return;
            this.authHandshakeTimer = null;
            this._failPending(epoch, new Error('WebSocket authentication timed out (no pong)'));
            // Drop the socket quietly (detach FIRST so its onclose cannot
            // double-schedule the retry) and let the bounded backoff take
            // over.
            this.state.connected = false;
            this.state.activeConnections = 0;
            if (this.ws === socket) this.ws = null;
            this._detach(socket);
            this._closeQuiet(socket);
            this.scheduleReconnect();
          }, 5000);
        };

        socket.onmessage = (event) => {
          if (epoch !== this.epoch) return; // obsolete socket
          const data = event.data;
          if (data === 'pong') {
            if (this.authHandshakeTimer) {
              clearTimeout(this.authHandshakeTimer);
              this.authHandshakeTimer = null;
              // Authenticated + confirmed — the success point where the
              // backoff counter resets.
              this.state.connected = true;
              this.reconnectAttempts = 0;
              this.startHeartbeat();
              this._settlePending(epoch);
            }
            return; // post-auth pong (heartbeat) — nothing to settle
          }
          let message;
          try {
            message = JSON.parse(data);
          } catch {
            return;
          }
          const handlers = this.handlers.get(message.type) || [];
          handlers.forEach(h => h(message));
          this.handlers.get('*')?.forEach(h => h(message));
        };

        socket.onerror = () => {
          if (epoch !== this.epoch) return;
          this.state.connected = false;
          // Fail the pending connect; onclose schedules the bounded retry.
          this._failPending(epoch, new Error('WebSocket error'));
        };

        socket.onclose = (event: CloseEvent) => {
          if (epoch !== this.epoch) return; // obsolete socket — a stale
          // socket's close must never schedule a reconnect or settle the
          // NEW connection's state
          this.stopHeartbeat();
          if (this.authHandshakeTimer) {
            clearTimeout(this.authHandshakeTimer);
            this.authHandshakeTimer = null;
          }
          const authAcknowledged = this.state.connected;
          this.state.connected = false;
          this.state.activeConnections = 0;
          // Intentional shutdown: settle the pending promise and stop —
          // never schedule a reconnect after logout/teardown.
          if (this.manualClose) {
            this._failPending(epoch, new WebSocketDisconnectedError());
            return;
          }
          // Closed before the auth handshake was acknowledged: fail the
          // pending connect (4401 = rejected auth — never reconnect).
          if (!authAcknowledged) {
            this._failPending(
              epoch,
              new Error(
                event.code === 4401
                  ? 'WebSocket auth rejected (4401)'
                  : 'WebSocket closed before authentication',
              ),
            );
          }
          // 4401 = rejected auth handshake — don't hammer the server.
          if (event.code === 4401) return;
          // Connection failure (or a post-auth drop): bounded backoff retry.
          // Recovery IS scheduled on the pre-auth failure path too (the old
          // code could return here without retrying).
          this.scheduleReconnect();
        };
      } catch (err) {
        this._failPending(epoch, err instanceof Error ? err : new Error(String(err)));
      }
    });

    this.connectPromise = promise;
    return promise;
  }

  /**
   * Intentional teardown (logout / component unmount): cancel every timer,
   * settle the pending connect promise, and detach the socket so its stale
   * callbacks cannot affect a newer connection.
   */
  disconnect(): void {
    this.epoch++;
    this.manualClose = true;
    // Settle the pending connect directly (NOT via the epoch-checked helper:
    // the epoch was just bumped, so the pending entry — created under the
    // previous generation — would never match and the promise would stay
    // unresolved).
    if (this.pending) {
      const p = this.pending;
      this.pending = null;
      this.connectPromise = null; // 1:1 with pending
      p.reject(new WebSocketDisconnectedError());
    }
    if (this._reconnectTimer) {
      clearTimeout(this._reconnectTimer);
      this._reconnectTimer = null;
    }
    this.stopHeartbeat();
    if (this.authHandshakeTimer) {
      clearTimeout(this.authHandshakeTimer);
      this.authHandshakeTimer = null;
    }
    if (this.ws) {
      const stale = this.ws;
      this.ws = null;
      this._detach(stale);
      this._closeQuiet(stale);
    }
    this.state.activeConnections = 0;
    this.state.connected = false;
  }

  /** Null out a socket's handlers so it can no longer talk to our state. */
  private _detach(socket: WebSocket): void {
    socket.onopen = null;
    socket.onclose = null;
    socket.onerror = null;
    socket.onmessage = null;
  }

  private _closeQuiet(socket: WebSocket): void {
    try {
      socket.close();
    } catch {
      /* already closing/closed */
    }
  }

  /** Resolve the pending connect (no-op once settled or already failed). */
  private _settlePending(epoch: number): void {
    if (this.pending && this.pending.epoch === epoch) {
      const p = this.pending;
      this.pending = null;
      this.connectPromise = null; // 1:1 with pending
      p.resolve();
    }
  }

  /** Reject the pending connect (no-op once settled or already failed). */
  private _failPending(epoch: number, err: Error): void {
    if (this.pending && this.pending.epoch === epoch) {
      const p = this.pending;
      this.pending = null;
      this.connectPromise = null; // 1:1 with pending
      p.reject(err);
    }
  }

  subscribe(type: string, handler: MessageHandler): () => void {
    if (!this.handlers.has(type)) {
      this.handlers.set(type, []);
    }
    this.handlers.get(type)!.push(handler);
    return () => this.unsubscribe(type, handler);
  }

  unsubscribe(type: string, handler: MessageHandler): void {
    const handlers = this.handlers.get(type);
    if (handlers) {
      const idx = handlers.indexOf(handler);
      if (idx >= 0) handlers.splice(idx, 1);
      if (handlers.length === 0) this.handlers.delete(type);
    }
  }

  private scheduleReconnect(): void {
    if (this.manualClose) return;
    if (this.reconnectAttempts >= this.maxReconnectAttempts) return;

    // Bounded backoff across failed attempts; the counter is only reset on
    // an authenticated success or a fresh programmatic connect().
    this.reconnectAttempts++;
    const delay = Math.min(this.reconnectDelay * Math.pow(2, this.reconnectAttempts - 1), 30000);
    this._reconnectTimer = setTimeout(() => {
      if (this.manualClose) return;
      this._reconnectTimer = null;
      // Reconnect with the original options (preserves the use_case_id
      // subscription the initial connect used). NOTE: _doConnect — NOT the
      // public connect() — so the backoff counter keeps escalating.
      this._doConnect(this.lastOptions).catch(() => { /* bounded by maxReconnectAttempts */ });
    }, delay);
  }

  private startHeartbeat(): void {
    this.stopHeartbeat();
    this.heartbeatTimer = setInterval(() => {
      if (this.ws && this.ws.readyState === WebSocket.OPEN) {
        try {
          this.ws.send('ping');
        } catch {
          /* onclose handles it */
        }
      }
    }, 30000);
  }

  private stopHeartbeat(): void {
    if (this.heartbeatTimer) {
      clearInterval(this.heartbeatTimer);
      this.heartbeatTimer = null;
    }
  }
}

// Singleton instance
export const ws = new NotificationWebSocket();
