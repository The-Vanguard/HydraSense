import React from 'react';

/**
 * ErrorBoundary — Catches render errors and displays a clear recovery UI
 * instead of letting the entire page crash to a blank screen.
 */
export default class ErrorBoundary extends React.Component {
  constructor(props) {
    super(props);
    this.state = { hasError: false, error: null, errorInfo: null };
  }

  static getDerivedStateFromError(error) {
    return { hasError: true, error };
  }

  componentDidCatch(error, errorInfo) {
    console.error('HydraSense ErrorBoundary caught an error:', error, errorInfo);
    this.setState({ errorInfo });
  }

  handleReset = () => {
    this.setState({ hasError: false, error: null, errorInfo: null });
  };

  render() {
    if (this.state.hasError) {
      if (this.props.fallback) {
        return typeof this.props.fallback === 'function'
          ? this.props.fallback(this.state.error, this.handleReset)
          : this.props.fallback;
      }

      return (
        <div style={{
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          justifyContent: 'center',
          height: '100vh',
          background: '#0d1117',
          color: '#e6edf3',
          fontFamily: "'IBM Plex Sans', -apple-system, BlinkMacSystemFont, sans-serif",
          padding: 24,
          textAlign: 'center',
        }}>
          <div style={{
            background: '#161b22',
            border: '1px solid #30363d',
            borderRadius: 8,
            padding: 32,
            maxWidth: 600,
            width: '100%',
            boxShadow: '0 8px 24px rgba(0,0,0,0.5)',
          }}>
            <div style={{ fontSize: 24, marginBottom: 8 }}>⚠️ Dashboard Component Error</div>
            <div style={{ fontSize: 13, color: '#8b949e', marginBottom: 16 }}>
              A component encountered an issue during rendering:
            </div>
            <div style={{
              background: '#0d1117',
              border: '1px solid #ef444455',
              borderRadius: 6,
              padding: 12,
              color: '#ef4444',
              fontFamily: "'IBM Plex Mono', monospace",
              fontSize: 12,
              textAlign: 'left',
              overflowX: 'auto',
              marginBottom: 20,
              maxHeight: 180,
            }}>
              {this.state.error?.toString() || 'Unknown error'}
            </div>
            <button
              onClick={() => window.location.reload()}
              style={{
                background: '#38bdf8',
                color: '#0d1117',
                border: 'none',
                borderRadius: 6,
                padding: '8px 20px',
                fontWeight: 600,
                fontSize: 13,
                cursor: 'pointer',
              }}
            >
              Reload Application
            </button>
          </div>
        </div>
      );
    }

    return this.props.children;
  }
}
