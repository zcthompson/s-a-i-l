/**
 * NotificationsPage — full-screen notifications view with real-time WebSocket updates.
 */

import { useState, useEffect, useRef } from 'react';
import { useInRouterContext, useSearchParams } from 'react-router-dom';
import { api } from '../lib/api';
import { NotificationItem } from '../types/use_case';
import { ws } from '../lib/websocket';

interface NotificationsPageProps {
  onBack: () => void;
  username: string;
}

type NotificationView = 'all' | 'unread' | 'read';

function useRoutedNotificationView(): [NotificationView, (view: NotificationView) => void] {
  const [params, setParams] = useSearchParams();
  const raw = params.get('notification_filter');
  const view: NotificationView = raw === 'unread' || raw === 'read' ? raw : 'all';
  return [view, (next) => {
    if (raw === next) return;
    setParams((previous) => {
      const updated = new URLSearchParams(previous);
      updated.set('notification_filter', next);
      return updated;
    });
  }];
}

function useLocalNotificationView(): [NotificationView, (view: NotificationView) => void] {
  return useState<NotificationView>('all');
}

function useNotificationView(): [NotificationView, (view: NotificationView) => void] {
  const inRouter = useInRouterContext();
  // Router context stays stable for the mounted page.
  // eslint-disable-next-line react-hooks/rules-of-hooks
  return inRouter ? useRoutedNotificationView() : useLocalNotificationView();
}

const TYPE_ICONS: Record<string, string> = {
  scoring: '📊',
  status_change: '🔄',
  comment: '💬',
  mention: '🔔',
  user_added: '👤',
  user_removed: '🚪',
  role_changed: '🛡️',
  system: '⚙️',
};

export function NotificationsPage({ onBack, username }: NotificationsPageProps) {
  const [notifications, setNotifications] = useState<NotificationItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [view, setView] = useNotificationView();
  const [count, setCount] = useState({ all: 0, unread: 0 });
  // UX audit #3: a failed count fetch used to be `/* ignore */`d, leaving the
  // badge silently stale with no indication anything went wrong. Track the
  // staleness and surface a subtle cue next to the count (same pattern as the
  // header NotificationBell's `stale` prop).
  const [countStale, setCountStale] = useState(false);
  const loadSeq = useRef(0);

  const loadNotifications = async (unreadOnly = false) => {
    const seq = ++loadSeq.current;
    setLoading(true);
    setError(null);
    try {
      const data = await api.getNotifications(100, unreadOnly);
      if (seq !== loadSeq.current) return;
      const sorted = [...data].sort((a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime());
      setNotifications(sorted);
      setCount(prev => ({ ...prev, [unreadOnly ? 'unread' : 'all']: sorted.length }));
    } catch (err: any) {
      if (seq !== loadSeq.current) return;
      setError(err.message || 'Failed to load notifications');
      setNotifications([]);
    } finally {
      if (seq === loadSeq.current) setLoading(false);
    }
  };

  const loadAllCounts = async () => {
    try {
      const [unread, all] = await Promise.all([
        api.getNotifications(100, true),
        api.getNotifications(100, false),
      ]);
      setCount({ all: all.length, unread: unread.length });
      setCountStale(false);
    } catch {
      // UX audit #3: don't swallow the failure silently — the badge now shows
      // a "may be out of date" cue instead of pretending to be fresh.
      setCountStale(true);
    }
  };

  useEffect(() => {
    loadNotifications(view === 'unread');
    return () => { loadSeq.current += 1; };
  }, [view]);

  useEffect(() => {
    loadAllCounts();
  }, []);

  // WebSocket for real-time updates
  useEffect(() => {
    if (!username) return;

    const unsubscribe = ws.subscribe('*', (message) => {
      const { type, data } = message;
      // Only process notifications that match our username
      if (type === 'scoring' || type === 'status_change' || type === 'comment' || type === 'mention' || type === 'notification_created') {
        const messageData = data as Record<string, unknown>;
        const targetUser = messageData?.user_name as string;
        if (targetUser === username) {
          // Refresh notifications to pick up new ones
          loadNotifications(view === 'unread');
          loadAllCounts();
        }
      }
    });

    return () => { if (typeof unsubscribe === 'function') unsubscribe(); };
  }, [username, view]);

  const handleMarkRead = async (id: number) => {
    try {
      await Promise.resolve(api.markNotificationRead(id));
      setNotifications(prev =>
        prev.map(n => n.id === id ? { ...n, read: true } : n)
      );
      setCount(prev => ({ ...prev, unread: Math.max(0, prev.unread - 1), all: prev.all }));
    } catch { /* ignore */ }
  };

  const handleMarkAllRead = async () => {
    const promises = notifications
      .filter(n => !n.read)
      .map(n => api.markNotificationRead(n.id).catch(() => null));
    await Promise.all(promises);
    setNotifications(prev => prev.map(n => ({ ...n, read: true })));
    setCount(prev => ({ ...prev, unread: 0, all: prev.all }));
  };

  const timeAgo = (iso: string) => {
    const now = Date.now();
    const then = new Date(iso).getTime();
    const diff = now - then;
    const mins = Math.floor(diff / 60000);
    if (mins < 1) return 'just now';
    if (mins < 60) return `${mins}m ago`;
    const hrs = Math.floor(mins / 60);
    if (hrs < 24) return `${hrs}h ago`;
    const days = Math.floor(hrs / 24);
    return `${days}d ago`;
  };

  const filteredNotifications = view === 'unread'
    ? notifications.filter(n => !n.read)
    : view === 'read' ? notifications.filter(n => n.read) : notifications;

  return (
    <div style={{ maxWidth: '800px', margin: '0 auto', padding: '24px' }}>
      {/* Header */}
      <div style={{
        display: 'flex',
        justifyContent: 'space-between',
        alignItems: 'center',
        marginBottom: '24px',
        paddingBottom: '16px',
        borderBottom: '1px solid var(--divider)',
      }}>
        <div>
          <h2 style={{ margin: '0 0 4px 0', color: 'var(--ink)', fontSize: '1.2rem' }}>
            Notifications
          </h2>
          <p style={{ margin: 0, color: 'var(--neutral-500)', fontSize: '0.85rem' }}>
            {count.unread > 0
              ? `${count.unread} unread notification${count.unread > 1 ? 's' : ''}`
              : 'All caught up'}
            {countStale && (
              <span role="status" aria-live="polite" style={{ marginLeft: '8px', fontSize: '0.78rem', color: 'var(--status-warning)' }}>
                · counts may be out of date
              </span>
            )}
          </p>
        </div>
        <button
          role="button"
          aria-label="Go back"
          onClick={onBack}
          style={{
            padding: '8px 16px',
            background: 'var(--neutral-100)',
            color: 'var(--neutral-700)',
            border: 'none',
            borderRadius: 'var(--radius)',
            cursor: 'pointer',
            fontSize: '0.85rem',
            fontWeight: 500,
          }}
        >
          ← Back
        </button>
      </div>

      {/* View Tabs */}
      <div style={{
        display: 'flex',
        gap: '8px',
        marginBottom: '20px',
      }}>
        {(['all', 'unread', 'read'] as const).map(v => (
          <button
            key={v}
            role="button"
            aria-label={`Show ${v} notifications`}
            aria-pressed={view === v}
            onClick={() => setView(v)}
            style={{
              padding: '6px 16px',
              background: view === v ? 'var(--brand-500)' : 'var(--neutral-100)',
              color: view === v ? 'var(--neutral-0)' : 'var(--neutral-500)',
              border: 'none',
              borderRadius: 'var(--radius-pill)',
              cursor: 'pointer',
              fontSize: '0.8rem',
              fontWeight: view === v ? 600 : 400,
              transition: 'all 0.2s',
            }}
          >
            {v === 'all' ? 'All' : v === 'unread' ? `Unread (${count.unread})` : 'Read'}
          </button>
        ))}
      </div>

      {/* Action Bar */}
      <div style={{
        display: 'flex',
        justifyContent: 'space-between',
        alignItems: 'center',
        marginBottom: '16px',
      }}>
        <div style={{ fontSize: '0.85rem', color: 'var(--neutral-500)' }}>
          {filteredNotifications.length} notification{filteredNotifications.length !== 1 ? 's' : ''}
        </div>
        <div style={{ display: 'flex', gap: '8px' }}>
          {notifications.some(n => !n.read) && (
            <button
              role="button"
              aria-label="Mark all as read"
              onClick={handleMarkAllRead}
              style={{
                padding: '4px 12px',
                background: 'var(--brand-500)',
                color: 'var(--neutral-0)',
                border: 'none',
                borderRadius: 'var(--radius-sm)',
                cursor: 'pointer',
                fontSize: '0.75rem',
                fontWeight: 500,
              }}
            >
              Mark all read
            </button>
          )}
        </div>
      </div>

      {/* Error */}
      {error && (
        <div role="alert" aria-live="assertive" style={{
          padding: '12px 16px',
          background: 'var(--status-negative-soft)',
          borderLeft: '4px solid var(--status-negative)',
          borderRadius: 'var(--radius-sm)',
          marginBottom: '16px',
          color: 'var(--status-negative)',
          fontSize: '0.85rem',
        }}>
          <span aria-hidden="true">⚠️ </span>{error}
        </div>
      )}

      {/* Loading */}
      {loading && (
        <div role="status" aria-live="polite" style={{
          padding: '40px',
          textAlign: 'center',
          color: 'var(--neutral-500)',
          fontSize: '0.9rem',
        }}>
          Loading notifications…
        </div>
      )}

      {/* Notifications List */}
      {!loading && (
        <>
          {filteredNotifications.length === 0 ? (
            <div style={{
              padding: '40px',
              textAlign: 'center',
              color: 'var(--neutral-500)',
              fontSize: '0.9rem',
            }}>
              {view === 'unread'
                ? 'No unread notifications'
                : view === 'read'
                  ? 'No read notifications'
                  : 'No notifications yet'}
            </div>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
              {filteredNotifications.map(notification => (
                <div
                  key={notification.id}
                  role="article"
                  aria-label={`Notification: ${notification.message}`}
                  style={{
                    padding: '16px',
                    background: notification.read ? 'var(--neutral-0)' : 'var(--brand-50)',
                    borderRadius: 'var(--radius)',
                    border: notification.read ? '1px solid var(--divider)' : '1px solid var(--brand-100)',
                    transition: 'all 0.2s',
                  }}
                >
                  <div style={{ display: 'flex', gap: '12px' }}>
                    <span style={{ fontSize: '1.2rem', flexShrink: 0 }}>
                      {TYPE_ICONS[notification.type] || '🔔'}
                    </span>
                    <div style={{ flex: 1, minWidth: 0 }}>
                      <div style={{
                        fontSize: '0.9rem',
                        color: 'var(--neutral-700)',
                        fontWeight: notification.read ? 400 : 600,
                        lineHeight: '1.4',
                      }}>
                        {notification.message}
                      </div>
                      <div style={{
                        display: 'flex',
                        justifyContent: 'space-between',
                        alignItems: 'center',
                        marginTop: '8px',
                      }}>
                        <span style={{ fontSize: '0.7rem', color: 'var(--neutral-500)' }}>
                          {timeAgo(notification.created_at)}
                        </span>
                        <div style={{ display: 'flex', gap: '4px', alignItems: 'center' }}>
                          <span style={{
                            fontSize: '0.65rem',
                            textTransform: 'uppercase',
                            padding: '2px 8px',
                            borderRadius: 'var(--radius-sm)',
                            background: notification.read ? 'var(--neutral-100)' : 'var(--brand-500)',
                            color: notification.read ? 'var(--neutral-500)' : 'var(--neutral-0)',
                          }}>
                            {notification.type}
                          </span>
                          {!notification.read && (
                            <button
                              role="button"
                              aria-label="Mark as read"
                              onClick={() => handleMarkRead(notification.id)}
                              style={{
                                background: 'none',
                                border: 'none',
                                color: 'var(--brand-700)',
                                cursor: 'pointer',
                                fontSize: '0.7rem',
                                fontWeight: 500,
                                padding: '2px 8px',
                              }}
                            >
                              Mark read
                            </button>
                          )}
                        </div>
                      </div>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )}
        </>
      )}
    </div>
  );
}
