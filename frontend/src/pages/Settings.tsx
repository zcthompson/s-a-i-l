import { ActionButton } from '../components/ActionButton';
import { needsAccountAppearanceSave, saveAccountAppearance } from '../lib/accountAppearance';
import { SectionIcon } from '../components/SectionIcon';
import { useEffect, useState } from 'react';
import { createPortal } from 'react-dom';
import { useInRouterContext, useSearchParams } from 'react-router-dom';
import { applyAppearance, getPreferences, removePreference, setPreference } from '../lib/preferences';
import type { PreferencesState } from '../lib/preferences';
import { APP_VERSION } from '../lib/version';

interface SettingsProps {
  onBack?: () => void;
}

type ThemeMode = 'light' | 'dark';
type NotificationPreference = 'all' | 'important' | 'none';

type SettingsTab = 'appearance' | 'notifications' | 'about';

function useRoutedSettingsTab(): [SettingsTab, (tab: SettingsTab) => void] {
  const [params, setParams] = useSearchParams();
  const raw = params.get('settings_tab');
  const tab: SettingsTab = raw === 'notifications' || raw === 'about' ? raw : 'appearance';
  const select = (next: SettingsTab) => {
    if (raw === next) return;
    setParams((previous) => {
      const updated = new URLSearchParams(previous);
      updated.set('settings_tab', next);
      return updated;
    });
  };
  return [tab, select];
}

function useLocalSettingsTab(): [SettingsTab, (tab: SettingsTab) => void] {
  return useState<SettingsTab>('appearance');
}

function useSettingsTab(): [SettingsTab, (tab: SettingsTab) => void] {
  const inRouter = useInRouterContext();
  // Router context is stable for the lifetime of this mounted page.
  // eslint-disable-next-line react-hooks/rules-of-hooks
  return inRouter ? useRoutedSettingsTab() : useLocalSettingsTab();
}

export function Settings({ onBack }: SettingsProps) {
  const [activeTab, setActiveTab] = useSettingsTab();
  const [savedPreferences, setSavedPreferences] = useState<PreferencesState>(() => getPreferences());

  // Appearance settings
  const [themeMode, setThemeMode] = useState<ThemeMode>(() => {
    return getPreferences().theme;
  });

  const [fontSize, setFontSize] = useState<string>(() => {
    return getPreferences().fontSize;
  });

  const [compactMode, setCompactMode] = useState<boolean>(() => {
    return getPreferences().compact;
  });

  // Notification settings
  const [notificationPreference, setNotificationPreference] = useState<NotificationPreference>(() => {
    return getPreferences().notifPref;
  });

  const [emailEnabled, setEmailEnabled] = useState<boolean>(() => {
    return getPreferences().emailNotif;
  });

  const [webSocketEnabled, setWebSocketEnabled] = useState<boolean>(() => {
    return getPreferences().websocketNotif;
  });

  const [pendingAction, setPendingAction] = useState<'save' | 'reset' | null>(null);
  const [saved, setSaved] = useState<string | null>(null);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [compactConfirmation, setCompactConfirmation] = useState<{ previous: boolean } | null>(null);

  const appearanceDirty = needsAccountAppearanceSave() || themeMode !== savedPreferences.theme || fontSize !== savedPreferences.fontSize || compactMode !== savedPreferences.compact;
  const notificationsDirty = notificationPreference !== savedPreferences.notifPref || emailEnabled !== savedPreferences.emailNotif || webSocketEnabled !== savedPreferences.websocketNotif;
  const dirty = appearanceDirty || notificationsDirty;

  const flashSaved = (message: string) => {
    setSaved(message);
    window.setTimeout(() => setSaved(null), 3000);
  };

  const revertCompact = () => {
    if (!compactConfirmation) return;
    setPreference('compact', compactConfirmation.previous);
    const next = { ...getPreferences(), compact: compactConfirmation.previous };
    applyAppearance(next);
    setCompactMode(compactConfirmation.previous);
    setSavedPreferences(next);
    setCompactConfirmation(null);
  };

  useEffect(() => {
    if (!compactConfirmation) return;
    const timer = window.setTimeout(revertCompact, 10_000);
    return () => window.clearTimeout(timer);
  // eslint-disable-next-line react-hooks/exhaustive-deps -- pre-existing dependency list; change only with UI verification
  }, [compactConfirmation]);

  const handleSave = async () => {
    if (pendingAction) return;
    setPendingAction('save');
    setSaveError(null);
    if (activeTab === 'appearance') {
      const previousCompact = savedPreferences.compact;
      setPreference('theme', themeMode);
      setPreference('fontSize', fontSize);
      setPreference('compact', compactMode);
      const next = getPreferences();
      applyAppearance(next);
      setSavedPreferences(next);
      if (compactMode !== previousCompact) setCompactConfirmation({ previous: previousCompact });
      try { await saveAccountAppearance(); flashSaved('Appearance settings saved.'); }
      catch (error) { setSavedPreferences(savedPreferences); setSaveError(error instanceof Error ? error.message : 'Account sync failed'); }
      finally { setPendingAction(null); }
      return;
    }
    setPreference('notifPref', notificationPreference);
    setPreference('emailNotif', emailEnabled);
    setPreference('websocketNotif', webSocketEnabled);
    setSavedPreferences(getPreferences());
    flashSaved('Notification settings saved.');
    setPendingAction(null);
  };

  const handleReset = async () => {
    if (pendingAction) return;
    const label = activeTab === 'appearance' ? 'appearance' : 'notification';
    if (!window.confirm(`Reset ${label} settings to defaults?`)) return;
    setPendingAction('reset');
    try {
      if (activeTab === 'appearance') {
        removePreference('theme');
        removePreference('fontSize');
        removePreference('compact');
        const next = getPreferences();
        setThemeMode(next.theme);
        setFontSize(next.fontSize);
        setCompactMode(next.compact);
        setSavedPreferences(next);
        applyAppearance(next);
        await saveAccountAppearance();
      } else {
        removePreference('notifPref');
        removePreference('emailNotif');
        removePreference('websocketNotif');
        const next = getPreferences();
        setNotificationPreference(next.notifPref);
        setEmailEnabled(next.emailNotif);
        setWebSocketEnabled(next.websocketNotif);
        setSavedPreferences(next);
      }
      flashSaved(`${activeTab === 'appearance' ? 'Appearance' : 'Notification'} settings reset to defaults.`);
    } catch (err) {
      if (activeTab === 'appearance') setSavedPreferences(savedPreferences);
      setSaveError(`Failed to reset settings: ${err instanceof Error ? err.message : 'Unknown error'}`);
      window.setTimeout(() => setSaveError(null), 3000);
    } finally { setPendingAction(null); }
  };

  return (
    <div style={{ maxWidth: '900px', margin: '0 auto', padding: '24px' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '24px' }}>
        <h1 style={{ margin: 0, fontSize: '1.8rem', color: 'var(--ink)' }}><SectionIcon name="⚙️" /> Settings</h1>
        {onBack && (
          <button role="button" aria-label="Back to previous page"
            onClick={onBack}
            style={{
              padding: '8px 16px',
              background: 'var(--neutral-500)',
              color: 'var(--neutral-0)',
              border: 'none',
              borderRadius: 'var(--radius)',
              cursor: 'pointer',
              fontSize: '0.85rem',
              fontWeight: 500,
            }}
          >
            ← Back
          </button>
        )}
      </div>

      {/* Save indicator */}
      {saved && (
        <div role="status" aria-live="polite" style={{
          padding: '12px 16px',
          background: 'var(--status-positive-soft)',
          border: '1px solid var(--status-positive-soft)',
          borderRadius: 'var(--radius)',
          color: 'var(--status-positive)',
          marginBottom: '20px',
          fontSize: '0.9rem',
        }}>
          {saved}
        </div>
      )}
      {saveError && (
        <div role="alert" aria-live="assertive" style={{
          padding: '12px 16px',
          background: 'var(--status-negative-soft)',
          border: '1px solid var(--status-negative-soft)',
          borderRadius: 'var(--radius)',
          color: 'var(--status-negative)',
          marginBottom: '20px',
          fontSize: '0.9rem',
        }}>
          {saveError}
        </div>
      )}
      {dirty && (
        <div role="status" style={{ color: 'var(--status-warning)', fontSize: '0.85rem', fontWeight: 600, marginBottom: '16px' }}>
          Unsaved changes
        </div>
      )}

      {/* Tabs */}
      <div style={{
        display: 'flex',
        gap: '4px',
        marginBottom: '24px',
        borderBottom: '2px solid var(--divider)',
        padding: '0 4px',
      }}>
        {[
          { id: 'appearance' as const, label: 'Appearance', icon: '🎨' },
          { id: 'notifications' as const, label: 'Notifications', icon: '🔔' },
          { id: 'about' as const, label: 'About', icon: 'ℹ️' },
        ].map(tab => (
          <button role="button" aria-label={`Show ${tab.label} settings`} aria-pressed={activeTab === tab.id}
            key={tab.id}
            onClick={() => setActiveTab(tab.id)}
            style={{
              padding: '10px 20px',
              background: activeTab === tab.id ? 'var(--brand-500)' : 'transparent',
              color: activeTab === tab.id ? 'var(--neutral-0)' : 'var(--neutral-500)',
              border: 'none',
              borderRadius: 'var(--radius) var(--radius) 0 0',
              cursor: 'pointer',
              fontSize: '0.9rem',
              fontWeight: activeTab === tab.id ? 600 : 400,
              transition: 'all 0.2s',
            }}
          >
            <SectionIcon name={tab.icon} size={18} /> {tab.label}
          </button>
        ))}
      </div>

      {/* Appearance Tab */}
      {activeTab === 'appearance' && (
        <div style={{ background: 'var(--neutral-0)', borderRadius: 'var(--radius)', padding: '24px', border: '1px solid var(--divider)', marginBottom: '20px' }}>
          <h3 style={{ margin: '0 0 20px 0', fontSize: '1.1rem', color: 'var(--neutral-700)' }}><SectionIcon name="🎨" /> Appearance</h3>

          {/* Theme Mode */}
          <div style={{ marginBottom: '24px' }}>
            <label style={{ display: 'block', marginBottom: '10px', fontSize: '0.9rem', fontWeight: 500, color: 'var(--neutral-500)' }}>
              Theme Mode
            </label>
            <div style={{ display: 'flex', gap: '12px' }}>
              <button role="button" aria-label="Select light theme"
                onClick={() => setThemeMode('light')}
                style={{
                  flex: 1,
                  padding: '14px 16px',
                  background: themeMode === 'light' ? 'var(--brand-500)' : 'var(--neutral-100)',
                  color: themeMode === 'light' ? 'var(--neutral-0)' : 'var(--neutral-500)',
                  border: `2px solid ${themeMode === 'light' ? 'var(--brand-500)' : 'var(--divider)'}`,
                  borderRadius: 'var(--radius)',
                  cursor: 'pointer',
                  fontSize: '0.95rem',
                  fontWeight: 600,
                  textAlign: 'center',
                }}
              >
                ☀️ Light Mode
              </button>
              <button role="button" aria-label="Select dark theme"
                onClick={() => setThemeMode('dark')}
                style={{
                  flex: 1,
                  padding: '14px 16px',
                  background: themeMode === 'dark' ? 'var(--brand-500)' : 'var(--neutral-100)',
                  color: themeMode === 'dark' ? 'var(--neutral-0)' : 'var(--neutral-500)',
                  border: `2px solid ${themeMode === 'dark' ? 'var(--brand-500)' : 'var(--divider)'}`,
                  borderRadius: 'var(--radius)',
                  cursor: 'pointer',
                  fontSize: '0.95rem',
                  fontWeight: 600,
                  textAlign: 'center',
                }}
              >
                🌙 Dark Mode
              </button>
            </div>
          </div>

          {/* Font Size */}
          <div style={{ marginBottom: '24px' }}>
            <label style={{ display: 'block', marginBottom: '10px', fontSize: '0.9rem', fontWeight: 500, color: 'var(--neutral-500)' }}>
              Font Size
            </label>
            <div style={{ display: 'flex', gap: '8px' }}>
              {['small', 'medium', 'large'].map((size) => (
                <button role="button" aria-label={`Set font size to ${size}`}
                  key={size}
                  onClick={() => setFontSize(size)}
                  style={{
                    flex: 1,
                    padding: '12px 12px',
                    background: fontSize === size ? 'var(--brand-500)' : 'var(--neutral-100)',
                    color: fontSize === size ? 'var(--neutral-0)' : 'var(--neutral-500)',
                    border: `2px solid ${fontSize === size ? 'var(--brand-500)' : 'var(--divider)'}`,
                    borderRadius: 'var(--radius)',
                    cursor: 'pointer',
                    fontSize: size === 'small' ? '0.8rem' : size === 'medium' ? '0.95rem' : '1.15rem',
                    fontWeight: 600,
                    textTransform: 'capitalize',
                  }}
                >
                  {size}
                </button>
              ))}
            </div>
          </div>

          {/* Compact Mode */}
          <div style={{ marginBottom: '24px' }}>
            <label style={{ display: 'block', marginBottom: '10px', fontSize: '0.9rem', fontWeight: 500, color: 'var(--neutral-500)' }}>
              Compact Mode
            </label>
            <label style={{
              display: 'flex',
              alignItems: 'center',
              gap: '12px',
              padding: '12px 16px',
              background: compactMode ? 'var(--brand-50)' : 'var(--neutral-0)',
              borderRadius: 'var(--radius)',
              border: `2px solid ${compactMode ? 'var(--brand-500)' : 'var(--divider)'}`,
            }}>
              <input aria-label="Enable compact layout"
                type="checkbox"
                checked={compactMode}
                onChange={(e) => setCompactMode(e.target.checked)}
                style={{ width: '18px', height: '18px', cursor: 'pointer' }}
              />
              <div>
                <div style={{ fontWeight: 500, color: 'var(--neutral-700)', fontSize: '0.9rem' }}>Enable compact layout</div>
                <div style={{ color: 'var(--neutral-500)', fontSize: '0.8rem', marginTop: '2px' }}>Reduce padding and spacing for denser data display</div>
              </div>
            </label>
          </div>

          <p style={{ color: 'var(--neutral-600)', fontSize: '0.85rem' }}>Theme and text size follow your account. Compact layout stays on this device.</p>
          {/* Save / Reset buttons */}
          <div style={{ display: 'flex', gap: '12px', paddingTop: '12px', borderTop: '1px solid var(--divider)' }}>
            <ActionButton variant="primary" busy={pendingAction === "save"} role="button" aria-label="Save appearance settings"
              onClick={handleSave}
              disabled={!appearanceDirty || pendingAction !== null}
            >
              Save Appearance
            </ActionButton>
            <ActionButton variant="quiet" busy={pendingAction === "reset"} role="button" aria-label="Reset appearance settings"
              onClick={handleReset} disabled={pendingAction !== null}
            >
              Reset to Defaults
            </ActionButton>
          </div>
        </div>
      )}

      {/* Notifications Tab */}
      {activeTab === 'notifications' && (
        <div style={{ background: 'var(--neutral-0)', borderRadius: 'var(--radius)', padding: '24px', border: '1px solid var(--divider)', marginBottom: '20px' }}>
          <h3 style={{ margin: '0 0 20px 0', fontSize: '1.1rem', color: 'var(--neutral-700)' }}><SectionIcon name="🔔" /> Notifications</h3>

          {/* Notification Preference */}
          <div style={{ marginBottom: '24px' }}>
            <label style={{ display: 'block', marginBottom: '10px', fontSize: '0.9rem', fontWeight: 500, color: 'var(--neutral-500)' }}>
              Notification Preference
            </label>
            <select aria-label="Notification preference"
              value={notificationPreference}
              onChange={(e) => setNotificationPreference(e.target.value as NotificationPreference)}
              style={{
                width: '100%',
                padding: '10px 14px',
                border: '1px solid var(--divider)',
                borderRadius: 'var(--radius)',
                fontSize: '0.9rem',
                background: 'var(--neutral-0)',
              }}
            >
              <option value="all">All notifications</option>
              <option value="important">Important only</option>
              <option value="none">No notifications</option>
            </select>
          </div>

          {/* Email Notifications */}
          <div style={{ marginBottom: '24px' }}>
            <label style={{ display: 'block', marginBottom: '10px', fontSize: '0.9rem', fontWeight: 500, color: 'var(--neutral-500)' }}>
              Email Notifications
            </label>
            <label style={{
              display: 'flex',
              alignItems: 'center',
              gap: '12px',
              padding: '12px 16px',
              background: emailEnabled ? 'var(--brand-50)' : 'var(--neutral-0)',
              borderRadius: 'var(--radius)',
              border: `2px solid ${emailEnabled ? 'var(--brand-500)' : 'var(--divider)'}`,
            }}>
              <input aria-label="Receive email alerts"
                type="checkbox"
                checked={emailEnabled}
                onChange={(e) => setEmailEnabled(e.target.checked)}
                style={{ width: '18px', height: '18px', cursor: 'pointer' }}
              />
              <div>
                <div style={{ fontWeight: 500, color: 'var(--neutral-700)', fontSize: '0.9rem' }}>Receive email alerts</div>
                <div style={{ color: 'var(--neutral-500)', fontSize: '0.8rem', marginTop: '2px' }}>Get notified about scoring updates and assessments via email</div>
              </div>
            </label>
          </div>

          {/* WebSocket / Real-time Notifications */}
          <div style={{ marginBottom: '24px' }}>
            <label style={{ display: 'block', marginBottom: '10px', fontSize: '0.9rem', fontWeight: 500, color: 'var(--neutral-500)' }}>
              Real-time Notifications
            </label>
            <label style={{
              display: 'flex',
              alignItems: 'center',
              gap: '12px',
              padding: '12px 16px',
              background: webSocketEnabled ? 'var(--brand-50)' : 'var(--neutral-0)',
              borderRadius: 'var(--radius)',
              border: `2px solid ${webSocketEnabled ? 'var(--brand-500)' : 'var(--divider)'}`,
            }}>
              <input aria-label="Enable WebSocket notifications"
                type="checkbox"
                checked={webSocketEnabled}
                onChange={(e) => setWebSocketEnabled(e.target.checked)}
                style={{ width: '18px', height: '18px', cursor: 'pointer' }}
              />
              <div>
                <div style={{ fontWeight: 500, color: 'var(--neutral-700)', fontSize: '0.9rem' }}>Enable WebSocket notifications</div>
                <div style={{ color: 'var(--neutral-500)', fontSize: '0.8rem', marginTop: '2px' }}>Receive real-time in-app notifications via WebSocket connection</div>
              </div>
            </label>
          </div>

          {/* Save / Reset buttons */}
          <div style={{ display: 'flex', gap: '12px', paddingTop: '12px', borderTop: '1px solid var(--divider)' }}>
            <ActionButton variant="primary" busy={pendingAction === "save"} role="button" aria-label="Save notification settings"
              onClick={handleSave}
              disabled={!notificationsDirty || pendingAction !== null}
            >
              Save Notifications
            </ActionButton>
            <ActionButton variant="quiet" busy={pendingAction === "reset"} role="button" aria-label="Reset notification settings"
              onClick={handleReset} disabled={pendingAction !== null}
            >
              Reset to Defaults
            </ActionButton>
          </div>
        </div>
      )}

      {/* About Tab */}
      {activeTab === 'about' && (
        <div style={{ background: 'var(--neutral-0)', borderRadius: 'var(--radius)', padding: '24px', border: '1px solid var(--divider)' }}>
          <h3 style={{ margin: '0 0 20px 0', fontSize: '1.1rem', color: 'var(--neutral-700)' }}><SectionIcon name="ℹ️" /> About</h3>

          <div style={{ display: 'grid', gap: '16px' }}>
            <div style={{
              display: 'flex',
              justifyContent: 'space-between',
              padding: '12px 0',
              borderBottom: '1px solid var(--divider)',
            }}>
              <span style={{ color: 'var(--neutral-500)', fontSize: '0.9rem' }}>Product</span>
              <span style={{ fontWeight: 600, color: 'var(--neutral-700)', fontSize: '0.9rem' }}>S-A-I-L (Sales Analytics and Intelligence Launchpad)</span>
            </div>
            <div style={{
              display: 'flex',
              justifyContent: 'space-between',
              padding: '12px 0',
              borderBottom: '1px solid var(--divider)',
            }}>
              <span style={{ color: 'var(--neutral-500)', fontSize: '0.9rem' }}>Version</span>
              {/* UX audit #15: version from package.json (single source of
                  truth), not a hand-edited UI literal. */}
              <span style={{ fontWeight: 600, color: 'var(--neutral-700)', fontSize: '0.9rem' }}>{APP_VERSION}</span>
            </div>
            <div style={{
              display: 'flex',
              justifyContent: 'space-between',
              padding: '12px 0',
              borderBottom: '1px solid var(--divider)',
            }}>
              <span style={{ color: 'var(--neutral-500)', fontSize: '0.9rem' }}>Description</span>
              <span style={{ maxWidth: '400px', textAlign: 'right', color: 'var(--neutral-700)', fontSize: '0.9rem' }}>Internal AI readiness assessment tool for evaluating and scoring AI use cases across customer organizations</span>
            </div>
            <div style={{
              display: 'flex',
              justifyContent: 'space-between',
              padding: '12px 0',
            }}>
              <span style={{ color: 'var(--neutral-500)', fontSize: '0.9rem' }}>Tech Stack</span>
              <span style={{ textAlign: 'right', color: 'var(--neutral-500)', fontSize: '0.85rem' }}>FastAPI + React + TypeScript + SQLite/PostgreSQL</span>
            </div>
          </div>

          <div style={{ marginTop: '24px', padding: '16px', background: 'var(--neutral-0)', borderRadius: 'var(--radius)', border: '1px solid var(--divider)' }}>
            <p style={{ margin: '0 0 4px 0', color: 'var(--neutral-500)', fontSize: '0.85rem' }}>
              <strong>S-A-I-L</strong> — Sales Analytics and Intelligence Launchpad
            </p>
            <p style={{ margin: 0, color: 'var(--neutral-500)', fontSize: '0.8rem' }}>
              © {new Date().getFullYear()} All rights reserved.
            </p>
          </div>
        </div>
      )}
      {compactConfirmation && createPortal(
        <div role="dialog" aria-modal="true" aria-label="Keep compact layout?" style={{ position: 'fixed', inset: 0, zIndex: 1200, display: 'flex', alignItems: 'flex-end', justifyContent: 'center', padding: '28px', pointerEvents: 'none' }}>
          <div style={{ pointerEvents: 'auto', width: 'min(440px, 90vw)', padding: '18px', borderRadius: 'var(--radius)', background: 'var(--neutral-0)', color: 'var(--ink)', border: '1px solid var(--divider)', boxShadow: 'var(--shadow-raised)' }}>
            <h2 style={{ margin: '0 0 8px', fontSize: '1.05rem' }}>Keep compact layout?</h2>
            <p style={{ margin: '0 0 14px', color: 'var(--neutral-500)', fontSize: '0.85rem' }}>This layout will revert automatically in 10 seconds.</p>
            <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '8px' }}>
              <button aria-label="Revert compact layout" onClick={revertCompact} style={{ padding: '8px 16px', background: 'var(--neutral-0)', color: 'var(--neutral-700)', border: '1px solid var(--divider)', borderRadius: 'var(--radius)', cursor: 'pointer' }}>Revert</button>
              <button aria-label="Keep compact layout" onClick={() => setCompactConfirmation(null)} style={{ padding: '8px 16px', background: 'var(--brand-500)', color: 'var(--neutral-0)', border: 'none', borderRadius: 'var(--radius)', cursor: 'pointer', fontWeight: 600 }}>Keep</button>
            </div>
          </div>
        </div>,
        document.body,
      )}
    </div>
  );
}
export default Settings;
