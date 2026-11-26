import { useEffect, useState } from 'react';
import { synchronizeAppearance } from './lib/accountAppearance';
import { BrowserRouter, Routes, Route, Navigate, useLocation, useMatch } from 'react-router-dom';
import { Home } from './pages/Home';
import { LoginPage } from './pages/Login';
import { NotFound } from './pages/NotFound';
import { getAuthToken } from './lib/api';
import './styles/mobile.css';
import './styles/theme.css';

// Guard: redirect to login only if no token exists.
// Prevents the redirect loop caused by navigation state updates by checking once.
function AuthenticatedRoute({ children }: { children: JSX.Element }) {
  const token = getAuthToken();
  const location = useLocation();
  const [readyToken, setReadyToken] = useState<string | null>(null);
  useEffect(() => {
    let active = true;
    if (token) synchronizeAppearance().catch(() => { /* Retain account-local cache while offline. */ }).finally(() => { if (active) setReadyToken(token); });
    return () => { active = false; };
  }, [token]);
  if (!token) {
    // Remember the intended destination (including any ?view= deep link)
    // so the post-login redirect returns the user to where they headed.
    return <Navigate to="/login" replace state={{ from: location }} />;
  }
  if (readyToken !== token) return <p role="status">Loading appearance…</p>;
  return children;
}

// Route to stay on login if already logged in
function RedirectIfAuthenticated({ children }: { children: JSX.Element }) {
  const token = getAuthToken();
  const location = useLocation();

  if (token) {
    // Redirect to the page they were trying to access, or to home.
    // Preserve pathname AND search so deep links (?view=…) survive login.
    const from = location.state?.from as { pathname?: string; search?: string } | undefined;
    const to = from ? `${from.pathname ?? '/'}${from.search ?? ''}` : '/';
    return <Navigate to={to} replace />;
  }

  return children;
}

// UX audit #2: unknown routes used to silently bounce to the dashboard with
// no signal the destination didn't exist (a real problem for ?view=/
// ?customer= deep links). The catch-all now renders a 404 view with the
// unmatched path.
function NotFoundRoute() {
  const match = useMatch('/*');
  return <NotFound path={match?.params['*']} />;
}

export function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/login" element={<RedirectIfAuthenticated><LoginPage /></RedirectIfAuthenticated>} />
        <Route
          path="/"
          element={
            <AuthenticatedRoute>
              <Home />
            </AuthenticatedRoute>
          }
        />
        <Route path="*" element={<NotFoundRoute />} />
      </Routes>
    </BrowserRouter>
  );
}
