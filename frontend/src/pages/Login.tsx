import { useState, useEffect } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { api, setAuth, clearAuth, getAuthToken, getAuthUsername, getAuthIsAdmin } from '../lib/api';
import { clearSessionReturn, consumeSessionExpired, consumeSessionReturn, isInternalPath, resetSessionRedirect } from '../lib/sessionRedirect';
import type { UserResponse } from '../types/use_case';

export function LoginPage() {
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const [isRegistering, setIsRegistering] = useState(false);
  const [pendingUsers, setPendingUsers] = useState<UserResponse[]>([]);
  const [actionLoading, setActionLoading] = useState<string | null>(null);
  const [localRegisterEnabled, setLocalRegisterEnabled] = useState(true);
  const [ldapEnabled, setLdapEnabled] = useState(false);
  const [loginHint, setLoginHint] = useState('');
  const navigate = useNavigate();
  const location = useLocation();
  const [regDepartment, setRegDepartment] = useState('');

  // On mount: if already logged in, detect admin panel state
  useEffect(() => {
    if (consumeSessionExpired()) setError('Session expired — please sign in again.');
    const token = getAuthToken();
    const storedUsername = getAuthUsername();
    const isAdmin = getAuthIsAdmin();
    if (token && storedUsername) {
      // Admin can view pending users
      if (isAdmin) {
        loadPendingUsers();
      }
    }
    if (!token && typeof api.getAuthPublicSettings === 'function') {
      api.getAuthPublicSettings()
        .then((settings) => {
          setLocalRegisterEnabled(settings.local_register_enabled);
          setLdapEnabled(settings.ldap_enabled);
          setLoginHint(settings.login_hint || '');
          if (!settings.local_register_enabled) {
            setIsRegistering(false);
          }
        })
        .catch(() => {
          // Older backends may not expose public auth settings. Preserve the
          // legacy login/register experience when that endpoint is absent.
        });
    }
  }, []);

  const loadPendingUsers = async () => {
    try {
      const users = await api.getPendingUsers();
      setPendingUsers(users);
    } catch {
      // Ignore errors in background
    }
  };

  const handleApprove = async (userUsername: string) => {
    setActionLoading(userUsername);
    try {
      await api.approveUser(userUsername);
      await loadPendingUsers();
    } catch (err: any) {
      setError(err.message || 'Approval failed');
    } finally {
      setActionLoading(null);
    }
  };

  const handleLogin = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    setLoading(true);
    try {
      const result = await api.login(username, password);
      setAuth(result.token, result.username, result.is_admin, result.role, result.sales_role ?? null);
      resetSessionRedirect();
      // FE-08: return to the pre-expiry destination (validated internal
      // path saved in sessionStorage), falling back to home. Credential
      // failures never reach here, so this only fires on a real login.
      const from = (location.state as { from?: { pathname?: string; search?: string; hash?: string } } | null)?.from;
      const stateDestination = from ? `${from.pathname ?? '/'}${from.search ?? ''}${from.hash ?? ''}` : null;
      navigate(consumeSessionReturn() ?? (stateDestination && isInternalPath(stateDestination) ? stateDestination : '/'));
    } catch (err: any) {
      setError(err.message || 'Login failed');
    } finally {
      setLoading(false);
    }
  };

  const handleRegister = async () => {
    if (!username || !password) {
      setError('Enter username and password');
      return;
    }
    setError('');
    setLoading(true);
    try {
      await api.register({
        username,
        email: `${username}@local`,
        password,
        display_name: username,
        department: regDepartment || undefined,
      });
      setIsRegistering(false);
      setError('Registration successful — log in');
    } catch (err: any) {
      setError(err.message || 'Registration failed');
    } finally {
      setLoading(false);
    }
  };

  const handleLogout = () => {
    clearSessionReturn();
    clearAuth();
    setUsername('');
    setPassword('');
    setError('');
    setPendingUsers([]);
    navigate('/login');
  };

  // ── Logged-in state ──────────────────────────────────────────────────────
  const loggedInUsername = getAuthUsername();
  const isAdmin = getAuthIsAdmin();

  if (loggedInUsername) {
    return (
      <div style={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        minHeight: 'var(--full-viewport, 100vh)',
        background: 'var(--gradient-brand-deep)',
      }}>
        <div style={{
          background: 'var(--neutral-0)',
          borderRadius: 'var(--radius)',
          padding: '2rem',
          width: '450px',
          boxShadow: 'var(--shadow-modal)',
        }}>
          <h2 style={{ textAlign: 'center', color: 'var(--neutral-700)', marginBottom: '1rem' }}>
            Sales Analytics and Intelligence Launchpad
          </h2>
          <div style={{
            textAlign: 'center',
            padding: '1rem',
            background: 'var(--brand-50)',
            borderRadius: 'var(--radius)',
            marginBottom: '1rem',
          }}>
            <p style={{ margin: 0, fontWeight: 'bold', color: 'var(--neutral-700)' }}>
              Logged in as: {loggedInUsername}
            </p>
            {isAdmin && (
              <span style={{
                display: 'inline-block',
                marginTop: '0.5rem',
                padding: '0.25rem 0.75rem',
                background: 'var(--brand-500)',
                color: 'var(--neutral-0)',
                borderRadius: 'var(--radius)',
                fontSize: '0.75rem',
                fontWeight: 'bold',
              }}>
                🔑 Admin
              </span>
            )}
          </div>
          {/* Admin approval panel */}
          {isAdmin && (
            <div style={{
              borderTop: '1px solid var(--divider)',
              paddingTop: '1rem',
              marginBottom: '1rem',
            }}>
              <h3 style={{ color: 'var(--neutral-700)', marginBottom: '0.75rem', fontSize: '1rem' }}>
                Pending User Approvals ({pendingUsers.length})
              </h3>
              {pendingUsers.length === 0 ? (
                <p style={{ color: 'var(--neutral-500)', textAlign: 'center', margin: 0 }}>
                  No pending users
                </p>
              ) : (
                <div>
                  {pendingUsers.map((user) => (
                    <div key={user.id} style={{
                      display: 'flex',
                      justifyContent: 'space-between',
                      alignItems: 'center',
                      padding: '0.5rem',
                      background: 'var(--neutral-50)',
                      borderRadius: 'var(--radius)',
                      marginBottom: '0.5rem',
                    }}>
                      <div>
                        <strong style={{ color: 'var(--neutral-700)' }}>{user.username}</strong>
                        <span style={{ color: 'var(--neutral-500)', marginLeft: '0.5rem' }}>{user.email}</span>
                      </div>
                      <button role="button" aria-label={`Approve ${user.username}`}
                        onClick={() => handleApprove(user.username)}
                        disabled={actionLoading === user.username}
                        style={{
                          padding: '0.35rem 0.75rem',
                          background: 'var(--status-positive)',
                          color: 'var(--neutral-0)',
                          border: 'none',
                          borderRadius: 'var(--radius-sm)',
                          cursor: actionLoading === user.username ? 'not-allowed' : 'pointer',
                          fontSize: '0.85rem',
                        }}
                      >
                        {actionLoading === user.username ? '✓' : 'Approve'}
                      </button>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}
          {/* Logout button */}
          <button role="button" aria-label="Log out"
            onClick={handleLogout}
            style={{
              width: '100%',
              padding: '0.75rem',
              background: 'var(--neutral-500)',
              color: 'var(--neutral-0)',
              border: 'none',
              borderRadius: 'var(--radius)',
              fontSize: '1rem',
              cursor: 'pointer',
            }}
          >
            Logout
          </button>
        </div>
      </div>
    );
  }

  // ── Login/Register form (not logged in) ───────────────────────────────────
  return (
    <div style={{
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      minHeight: 'var(--full-viewport, 100vh)',
      background: 'var(--gradient-brand-deep)',
    }}>
      <div style={{
        background: 'var(--neutral-0)',
        borderRadius: 'var(--radius)',
        padding: '2rem',
        width: '380px',
        boxShadow: 'var(--shadow-modal)',
      }}>
        <img
          src="/sail_logo.svg"
          alt="S-A-I-L — Sales Analytics and Intelligence Launchpad"
          style={{
            display: 'block',
            width: '220px',
            height: 'auto',
            margin: '0 auto 0.75rem',
            borderRadius: 'var(--radius)',
            objectFit: 'contain',
          }}
        />
        <h2 style={{ textAlign: 'center', color: 'var(--neutral-700)', marginBottom: '1.5rem' }}>
          Sales Analytics and Intelligence Launchpad
        </h2>
        {isRegistering && localRegisterEnabled ? (
          /* Registration form */
          <div>
            <div style={{ marginBottom: '0.75rem' }}>
              <input aria-label="Username"
                type="text"
                placeholder="Username"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                style={{
                  width: '100%',
                  padding: '0.75rem',
                  border: '1px solid var(--divider)',
                  borderRadius: 'var(--radius)',
                  fontSize: '1rem',
                  boxSizing: 'border-box',
                }}
              />
            </div>
            <div style={{ marginBottom: '0.75rem' }}>
              <input aria-label="Password"
                type="password"
                placeholder="Password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                style={{
                  width: '100%',
                  padding: '0.75rem',
                  border: '1px solid var(--divider)',
                  borderRadius: 'var(--radius)',
                  fontSize: '1rem',
                  boxSizing: 'border-box',
                }}
              />
            </div>
            <div style={{ marginBottom: '0.75rem' }}>
              <input aria-label="Department (optional)"
                type="text"
                placeholder="Department (optional)"
                value={regDepartment}
                onChange={(e) => setRegDepartment(e.target.value)}
                style={{
                  width: '100%',
                  padding: '0.75rem',
                  border: '1px solid var(--divider)',
                  borderRadius: 'var(--radius)',
                  fontSize: '1rem',
                  boxSizing: 'border-box',
                }}
              />
            </div>
            <button role="button" aria-label="Register a new account"
              type="button"
              onClick={handleRegister}
              disabled={loading}
              style={{
                width: '100%',
                padding: '0.75rem',
                background: 'var(--status-positive)',
                color: 'var(--neutral-0)',
                border: 'none',
                borderRadius: 'var(--radius)',
                fontSize: '1rem',
                cursor: 'pointer',
                marginBottom: '0.5rem',
              }}
            >
              {loading ? 'Registering...' : 'Register'}
            </button>
            <button role="button" aria-label="Back to login"
              type="button"
              onClick={() => setIsRegistering(false)}
              style={{
                width: '100%',
                padding: '0.5rem',
                background: 'transparent',
                color: 'var(--neutral-500)',
                border: 'none',
                borderRadius: 'var(--radius)',
                fontSize: '0.9rem',
                cursor: 'pointer',
              }}
            >
              Back to Login
            </button>
          </div>
        ) : (
          /* Login form */
          <form onSubmit={handleLogin}>
            <div style={{ marginBottom: '1rem' }}>
              <input aria-label="Username"
                type="text"
                placeholder="Username"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                style={{
                  width: '100%',
                  padding: '0.75rem',
                  border: '1px solid var(--divider)',
                  borderRadius: 'var(--radius)',
                  fontSize: '1rem',
                  boxSizing: 'border-box',
                }}
              />
            </div>
            <div style={{ marginBottom: '1rem' }}>
              <input aria-label="Password"
                type="password"
                placeholder="Password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                style={{
                  width: '100%',
                  padding: '0.75rem',
                  border: '1px solid var(--divider)',
                  borderRadius: 'var(--radius)',
                  fontSize: '1rem',
                  boxSizing: 'border-box',
                }}
              />
            </div>
            <button role="button" aria-label="Log in"
              type="submit"
              disabled={loading}
              style={{
                width: '100%',
                padding: '0.75rem',
                background: 'var(--brand-500)',
                color: 'var(--neutral-0)',
                border: 'none',
                borderRadius: 'var(--radius)',
                fontSize: '1rem',
                cursor: 'pointer',
                marginBottom: '0.5rem',
              }}
            >
              {loading ? 'Logging in...' : 'Login'}
            </button>
            {localRegisterEnabled ? (
              <button role="button" aria-label="Switch to registration"
                type="button"
                onClick={() => setIsRegistering(true)}
                disabled={loading}
                style={{
                  width: '100%',
                  padding: '0.75rem',
                  background: 'var(--status-positive)',
                  color: 'var(--neutral-0)',
                  border: 'none',
                  borderRadius: 'var(--radius)',
                  fontSize: '1rem',
                  cursor: 'pointer',
                }}
              >
                {loading ? 'Loading...' : 'Register'}
              </button>
            ) : (
              <p style={{ margin: '0.75rem 0 0', color: 'var(--neutral-500)', textAlign: 'center', fontSize: '0.85rem' }}>
                Self-registration is disabled — contact an administrator.
              </p>
            )}
          </form>
        )}
        {ldapEnabled && loginHint && (
          <p style={{ margin: '0.75rem 0 0', color: 'var(--neutral-500)', textAlign: 'center', fontSize: '0.85rem' }}>
            {loginHint}
          </p>
        )}
        {error && (
          <p role="alert" aria-live="assertive" style={{ color: 'var(--status-negative)', background: 'var(--status-negative-soft)', borderLeft: '4px solid var(--status-negative)', padding: '12px 16px', textAlign: 'center', marginTop: '1rem' }}>
            <span aria-hidden="true">⚠️ </span>{error}
          </p>
        )}
        {loading && <p role="status" aria-live="polite" style={{ color: 'var(--neutral-500)', textAlign: 'center' }}>Processing your request…</p>}
        <p style={{ color: 'var(--neutral-500)', textAlign: 'center', fontSize: '0.85rem', marginTop: '1rem' }}>
          Auth is optional — set SAIL_API_KEYS to require login
        </p>
      </div>
    </div>
  );
}
