/**
 * NotificationBell — bell icon with unread count badge, opens notification panel.
 */

import { useState, useRef, useEffect } from 'react';
import { createPortal } from 'react-dom';
import { api } from '../lib/api';
import { getAuthUsername } from '../lib/auth';
import type { NotificationItem } from '../types/use_case';

interface NotificationBellProps {
  unreadCount: number;
  /** True when the last unread-count refresh failed (the count may be stale). */
  stale?: boolean;
  onNavigate: (view: string) => void;
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

export function NotificationBell({ unreadCount, stale = false, onNavigate }: NotificationBellProps) {
  const [isOpen, setIsOpen] = useState(false);
  const [notifications, setNotifications] = useState<NotificationItem[]>([]);
  const [loading, setLoading] = useState(false);
  const panelRef = useRef<HTMLDivElement>(null);
  const username = getAuthUsername();

  useEffect(() => {
    if (!isOpen || !username) return;
    setLoading(true);
    api.getNotifications(20, false)
      .then(data => { setNotifications(data); setLoading(false); })
      .catch(() => { setLoading(false); });
  }, [isOpen, username]);

  // Close panel when clicking outside
  useEffect(() => {
    if (!isOpen) return;
    const handler = (e: MouseEvent) => {
      if (panelRef.current && !panelRef.current.contains(e.target as Node)) {
        setIsOpen(false);
      }
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, [isOpen]);

  const handleMarkRead = (id: number) => {
    api.markNotificationRead(id).catch(() => {});
    setNotifications(prev => prev.map(n => n.id === id ? { ...n, read: true } : n));
  };

  const handleMarkAllRead = () => {
    const promises = notifications.filter(n => !n.read).map(n =>
      api.markNotificationRead(n.id).catch(() => {})
    );
    Promise.all(promises).catch(() => {});
    setNotifications(prev => prev.map(n => ({ ...n, read: true })));
  };

  const handleDismiss = (id: number) => {
    setNotifications(prev => prev.filter(n => n.id !== id));
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

  if (unreadCount === 0 && !isOpen) {
    return (
      <button
        role="button"
        aria-label="Notifications"
        aria-live="polite"
        onClick={() => setIsOpen(true)}
        style={{
          background: 'transparent',
          border: 'none',
          cursor: 'pointer',
          fontSize: '1.25rem',
          padding: '4px',
          position: 'relative',
        }}
      >
        🔔
      </button>
    );
  }

  return (
    <div style={{ position: 'relative' }} ref={panelRef}>
      {/* Bell button */}
      <button
        role="button"
        aria-label={`Notifications, ${unreadCount} unread${stale ? ' (count may be stale — last refresh failed)' : ''}`}
        aria-live="polite"
        onClick={() => setIsOpen(!isOpen)}
        style={{
          background: 'transparent',
          border: 'none',
          cursor: 'pointer',
          fontSize: '1.25rem',
          padding: '4px',
          position: 'relative',
        }}
      >
        🔔
        {unreadCount > 0 && (
          <span
            style={{
              position: 'absolute',
              top: '-2px',
              right: '-4px',
              background: 'var(--status-negative)',
              color: 'var(--neutral-0)',
              fontSize: '0.6rem',
              fontWeight: 'bold',
              borderRadius: '50%',
              width: '16px',
              height: '16px',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
            }}
          >
            {unreadCount > 99 ? '99+' : unreadCount}
          </span>
        )}
      </button>

      {/* Dropdown panel (portaled to <body> so it stays viewport-anchored
          under the dark-theme filter, which makes #root a containing block) */}
      {isOpen && createPortal(
        <>
          <div
            style={{
              position: 'fixed',
              top: 0,
              left: 0,
              right: 0,
              bottom: 0,
              zIndex: 1000,
            }}
            onClick={() => setIsOpen(false)}
          />
          <div
            style={{
              position: 'fixed',
              top: '52px',
              right: '20px',
              width: '380px',
              maxHeight: '480px',
              background: 'var(--neutral-0)',
              borderRadius: 'var(--radius)',
              boxShadow: 'var(--shadow-raised)',
              zIndex: 1001,
              display: 'flex',
              flexDirection: 'column',
              overflow: 'hidden',
            }}
            role="dialog"
            aria-label="Notifications"
          >
            {/* Header */}
            <div style={{
              padding: '12px 16px',
              borderBottom: '1px solid var(--divider)',
              display: 'flex',
              justifyContent: 'space-between',
              alignItems: 'center',
            }}>
              <h3 style={{ margin: 0, fontSize: '0.95rem', color: 'var(--ink)', fontWeight: 600 }}>
                Notifications
                {unreadCount > 0 && (
                  <span style={{
                    marginLeft: '6px',
                    fontSize: '0.75rem',
                    color: 'var(--status-negative)',
                    fontWeight: 'bold',
                  }}>
                    ({unreadCount} unread)
                  </span>
                )}
              </h3>
              <button
                role="button"
                aria-label="Mark all as read"
                onClick={handleMarkAllRead}
                style={{
                  background: 'none',
                  border: 'none',
                  color: 'var(--brand-700)',
                  cursor: 'pointer',
                  fontSize: '0.75rem',
                  fontWeight: 500,
                  padding: '4px 8px',
                  borderRadius: 'var(--radius-sm)',
                }}
              >
                Mark all read
              </button>
            </div>

            {/* List */}
            <div style={{
              overflow: 'auto',
              flex: 1,
              maxHeight: '400px',
            }}>
              {loading ? (
                <div style={{
                  padding: '24px',
                  textAlign: 'center',
                  color: 'var(--neutral-500)',
                  fontSize: '0.85rem',
                }}>
                  Loading…
                </div>
              ) : notifications.length === 0 ? (
                <div style={{
                  padding: '24px',
                  textAlign: 'center',
                  color: 'var(--neutral-500)',
                  fontSize: '0.85rem',
                }}>
                  No notifications yet
                </div>
              ) : (
                notifications.map(notification => (
                  <div
                    key={notification.id}
                    role="article"
                    aria-label={`Notification: ${notification.message}`}
                    style={{
                      padding: '12px 16px',
                      borderBottom: '1px solid var(--neutral-100)',
                      background: notification.read ? 'var(--neutral-0)' : 'var(--brand-50)',
                      transition: 'background 0.2s',
                      position: 'relative',
                    }}
                  >
                    <div style={{ display: 'flex', alignItems: 'flex-start', gap: '8px' }}>
                      <span style={{ fontSize: '1.1rem', flexShrink: 0, marginTop: '1px' }}>
                        {TYPE_ICONS[notification.type] || '🔔'}
                      </span>
                      <div style={{ flex: 1, minWidth: 0 }}>
                        <div style={{
                          fontSize: '0.85rem',
                          color: 'var(--neutral-700)',
                          fontWeight: notification.read ? 400 : 600,
                          lineHeight: '1.4',
                        }}>
                          {notification.message}
                        </div>
                        <div style={{
                          fontSize: '0.7rem',
                          color: 'var(--neutral-500)',
                          marginTop: '4px',
                          display: 'flex',
                          justifyContent: 'space-between',
                          alignItems: 'center',
                        }}>
                          <span>{timeAgo(notification.created_at)}</span>
                          <span style={{
                            fontSize: '0.6rem',
                            textTransform: 'uppercase',
                            padding: '1px 6px',
                            borderRadius: 'var(--radius-sm)',
                            background: notification.read ? 'var(--neutral-100)' : 'var(--brand-500)',
                            color: notification.read ? 'var(--neutral-500)' : 'var(--neutral-0)',
                          }}>
                            {notification.type}
                          </span>
                        </div>
                      </div>
                      {/* Dismiss button */}
                      <button
                        role="button"
                        aria-label="Dismiss notification"
                        onClick={() => handleDismiss(notification.id)}
                        style={{
                          background: 'none',
                          border: 'none',
                          color: 'var(--neutral-500)',
                          cursor: 'pointer',
                          fontSize: '0.85rem',
                          padding: '2px 4px',
                          flexShrink: 0,
                        }}
                      >
                        ✕
                      </button>
                    </div>
                    {!notification.read && (
                      <button
                        role="button"
                        aria-label="Mark notification as read"
                        onClick={() => handleMarkRead(notification.id)}
                        style={{
                          position: 'absolute',
                          bottom: '4px',
                          right: '12px',
                          background: 'none',
                          border: 'none',
                          color: 'var(--brand-700)',
                          cursor: 'pointer',
                          fontSize: '0.65rem',
                          fontWeight: 500,
                        }}
                      >
                        Mark as read
                      </button>
                    )}
                  </div>
                ))
              )}
            </div>

            {/* Footer */}
            <div style={{
              padding: '10px 16px',
              borderTop: '1px solid var(--divider)',
              textAlign: 'center',
            }}>
              <button
                role="button"
                aria-label="View all notifications"
                onClick={() => {
                  setIsOpen(false);
                  onNavigate('collab-notifications');
                }}
                style={{
                  background: 'none',
                  border: 'none',
                  color: 'var(--brand-700)',
                  cursor: 'pointer',
                  fontSize: '0.8rem',
                  fontWeight: 500,
                }}
              >
                View all notifications →
              </button>
            </div>
          </div>
        </>,
        document.body
      )}
    </div>
  );
}
