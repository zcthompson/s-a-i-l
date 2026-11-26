import React from 'react'
import ReactDOM from 'react-dom/client'
import { App } from './App'
import { GlobalErrorBoundary } from './components/GlobalErrorBoundary'
import { applyAppearance, getPreferences } from './lib/preferences'

// Apply saved appearance preferences BEFORE the first render so the
// dark-theme / font-size / compact attributes are live on initial paint
// (Settings.tsx keeps them in sync while the Settings page is open).
applyAppearance(getPreferences())

// GlobalErrorBoundary (UX audit #1): a render crash in ANY component used to
// unmount the whole SPA (blank page, no recovery). The boundary degrades to
// a reload card; the constellation canvas keeps its own nested, finer-grained
// boundary.
ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <GlobalErrorBoundary>
      <App />
    </GlobalErrorBoundary>
  </React.StrictMode>,
)
