import { SectionIcon } from '../components/SectionIcon';
/**
 * NotFound — catch-all route view. UX audit #2 (2026-09-13): unknown paths
 * silently bounced to the dashboard with zero signal that the destination
 * didn't exist — a problem for a tool where ?view=/?customer= deep links are
 * a documented feature. This gives stale shared links / typos a real 404.
 */
import { Link } from 'react-router-dom';

interface NotFoundProps {
  /** The unmatched path (from the router match), for context in the copy. */
  path?: string;
}

export function NotFound({ path }: NotFoundProps) {
  return (
    <div
      style={{
        minHeight: '100vh',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        padding: '24px',
        background: 'var(--neutral-0)',
      }}
    >
      <div style={{ textAlign: 'center', maxWidth: '420px' }}>
        <div style={{ fontSize: '3rem', marginBottom: '12px' }} aria-hidden="true"><SectionIcon name="🧭" size={40} /></div>
        <h1 style={{ margin: '0 0 8px 0', fontSize: '1.4rem', color: 'var(--ink)' }}>
          Page not found
        </h1>
        <p style={{ margin: '0 0 6px 0', color: 'var(--neutral-500)', fontSize: '0.95rem' }}>
          The page you were looking for doesn't exist — the link may be stale or the address was
          mistyped.
        </p>
        {path && (
          <p style={{ margin: '0 0 16px 0', color: 'var(--neutral-500)', fontSize: '0.8rem', overflowWrap: 'anywhere' }}>
            {/* useMatch('/*') drops the leading slash — restore it for display. */}
            No view matches <code style={{ background: 'var(--neutral-100)', padding: '2px 6px', borderRadius: '4px' }}>{path.startsWith('/') ? path : `/${path}`}</code>
          </p>
        )}
        <Link
          data-ui="recovery-link"
          to="/"
          style={{
            display: 'inline-block',
            padding: '10px 24px',
            background: 'var(--brand-500)',
            color: 'var(--neutral-0)',
            borderRadius: 'var(--radius)',
            fontSize: '0.9rem',
            fontWeight: 600,
            textDecoration: 'none',
          }}
        >
          ← Back to dashboard
        </Link>
      </div>
    </div>
  );
}

export default NotFound;
