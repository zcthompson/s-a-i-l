import { ActionButton } from './ActionButton';
/**
 * ConstellationErrorBoundary — a minimal, locally-scoped React error boundary
 * for the Customer Intelligence Constellation. It complements the global
 * boundary so a WebGL renderer failure stays within this section. This degrades just the visualization section to a
 * graceful 'visualization unavailable' card with a retry, and logs the
 * stable `[mobius] webgl unavailable` marker the CDP harness asserts on.
 */
import { Component, ErrorInfo, ReactNode } from 'react';

interface Props {
  children: ReactNode;
}

interface State {
  error: Error | null;
}

export class ConstellationErrorBoundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error('[mobius] webgl unavailable', 'render error:', error, info.componentStack);
  }

  reset = () => this.setState({ error: null });

  render() {
    const { error } = this.state;
    if (!error) return this.props.children;
    return (
      <div
        role="alert"
        style={{
          border: '1px solid var(--divider)',
          borderRadius: 'var(--radius)',
          padding: '18px 20px',
          background: 'var(--neutral-50)',
          color: 'var(--neutral-700)',
          fontSize: '0.9rem',
        }}
      >
        <strong style={{ color: 'var(--ink)' }}>Visualization unavailable</strong>
        <p style={{ margin: '8px 0 0', fontSize: '0.82rem', color: 'var(--neutral-600)' }}>
          <span style={{ overflowWrap: 'anywhere' }}>{error.message || String(error)}</span>
        </p>
        <ActionButton
          role="button"
          onClick={this.reset} style={{ marginTop: 14 }}
        >
          Try again
        </ActionButton>
      </div>
    );
  }
}

export default ConstellationErrorBoundary;
