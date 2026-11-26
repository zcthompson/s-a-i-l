import { ActionButton } from './ActionButton';
import { SectionIcon } from './SectionIcon';
/**
 * GlobalErrorBoundary — top-level React error boundary. UX audit #1 (2026-09-13):
 * the app had NO app-wide boundary (only the constellation-scoped one), so a
 * render-time throw in any component (null deref after an API shape change, a
 * bad date in a table cell) unmounted the whole SPA — blank page, no recovery.
 * This degrades to a recovery card with a reload action; the
 * ConstellationErrorBoundary stays nested for finer-grained recovery of the
 * canvas renderer.
 */
import { Component, ErrorInfo, ReactNode } from 'react';

interface Props {
  children: ReactNode;
}

interface State {
  error: Error | null;
}

export class GlobalErrorBoundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error('Global render error:', error, info.componentStack);
  }

  render() {
    const { error } = this.state;
    if (!error) return this.props.children;
    return (
      <div
        role="alert"
        aria-live="assertive"
        style={{
          minHeight: '100vh',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          padding: '24px',
          background: 'var(--neutral-0)',
        }}
      >
        <div
          style={{
            background: 'var(--neutral-0)',
            border: '1px solid var(--divider)',
            borderRadius: 'var(--radius)',
            boxShadow: 'var(--shadow-card)',
            padding: '32px 36px',
            maxWidth: '460px',
            textAlign: 'center',
          }}
        >
          <div style={{ fontSize: '2rem', marginBottom: '12px' }} aria-hidden="true"><SectionIcon name="⚠️" size={32} /></div>
          <h1 style={{ margin: '0 0 8px 0', fontSize: '1.2rem', color: 'var(--ink)' }}>
            Something went wrong
          </h1>
          <p style={{ margin: '0 0 6px 0', color: 'var(--neutral-500)', fontSize: '0.9rem' }}>
            The application hit an unexpected error. Reload to try again; unsaved edits may be lost.
          </p>
          <p style={{ margin: '0 0 20px 0', color: 'var(--neutral-500)', fontSize: '0.8rem' }}>
            <span style={{ overflowWrap: 'anywhere' }}>{error.message || String(error)}</span>
          </p>
          <ActionButton
            role="button"
            aria-label="Reload the application"
            onClick={() => window.location.reload()} style={{ marginTop: 14 }}
          >
            Reload application
          </ActionButton>
        </div>
      </div>
    );
  }
}

export default GlobalErrorBoundary;
