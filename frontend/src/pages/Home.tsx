import { storedScoring } from '../lib/storedScoring';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { useState, useEffect, useRef, lazy, Suspense } from 'react';
import { createPortal } from 'react-dom';
import { Sidebar } from '../components/Sidebar';
import { HomeDashboard } from './HomeDashboard';
import { UseCaseDetail } from '../components/UseCaseDetail';
import { api, clearAuth, getAuthUsername, getAuthIsAdmin, getAuthSalesRole } from '../lib/api';
import { clearSessionReturn } from '../lib/sessionRedirect';
import { getAuthRole } from '../lib/auth';
import { ws } from '../lib/websocket';
import { normalizeView, isSelectionRequiredView, getViewLabel } from '../lib/nav';
import { getPreferences, setPreference } from '../lib/preferences';
import { UseCase, ScoredUseCaseResponse } from '../types/use_case';
import { AI_SCORING_REQUIRES_AI_ASSESSMENT } from '../lib/assessmentLabels';
import { useWorkspaceScroll } from '../lib/useWorkspaceScroll';
import { useReducedMotion } from '../lib/theme';
import { PORTFOLIO_FILTER_PARAMS } from '../lib/useDashboardScope';

// ── Lazy-loaded route components (code-split into separate bundles) ──
const AssessmentForm = lazy(() => import('../components/AssessmentForm'));
const AssessmentList = lazy(() => import('./AssessmentList'));
const BusinessImpact = lazy(() => import('./BusinessImpact'));
const ScoringDashboard = lazy(() => import('../components/ScoringDashboard'));
const ImpactMatrix = lazy(() => import('../components/ImpactMatrix'));
const DeptComparison = lazy(() => import('../components/DeptComparison'));
const ScoreDrillDown = lazy(() => import('../components/ScoreDrillDown'));
const CommentThread = lazy(() => import('../components/CommentThread'));
const AnalyticsDashboard = lazy(() => import('../components/AnalyticsDashboard'));
const IntegrationSettings = lazy(() => import('../components/IntegrationSettings'));
const PDFReport = lazy(() => import('../components/PDFReport'));
const ExportPage = lazy(() => import('./ExportPage'));
const IntelligenceImport = lazy(() => import('./IntelligenceImport'));
const TemplatesPage = lazy(() => import('./TemplatesPage'));
const BulkScore = lazy(() => import('../components/BulkScore'));
const AdminPage = lazy(() => import('./AdminPage'));
const CustomerDashboard = lazy(() => import('./CustomerDashboard'));
const Settings = lazy(() => import('./Settings'));
const GlobalAdminDashboard = lazy(() => import('../components/GlobalAdminDashboard'));
const CustomerOwnership = lazy(() => import('../components/CustomerOwnership'));
const NotificationBell = lazy(() => import('../components/NotificationBell').then(m => ({ default: m.NotificationBell })));
const NotificationsPage = lazy(() => import('./NotificationsPage').then(m => ({ default: m.NotificationsPage })));

// Suspense fallback: lightweight spinner matching project style
// WP23a F4(c): client-side ceiling for a long AI operation. Abort at this
// point — the server-side model work may run to completion (no server
// cancel protocol exists; note for a future backend WP).
const LONG_OP_TIMEOUT_MS = 300_000;

export function LoadingFallback() {
  const reducedMotion = useReducedMotion();
  return (
    <div style={{ padding: '40px', textAlign: 'center', color: 'var(--neutral-500)' }} role="status" aria-live="polite">
      <div style={{ fontSize: '1.2rem', marginBottom: '8px' }}>Loading…</div>
      <div style={{ width: '24px', height: '24px', border: '3px solid var(--divider)', borderTopColor: 'var(--brand-500)', borderRadius: '50%', margin: '12px auto', animation: reducedMotion ? 'none' : 'spin 1s linear infinite' }} />
    </div>
  );
}

// F19: admin deep links (?view=admin*, ?view=customer-create) used to render
// the admin pages/controls for ANY user; the server then 403s on every
// action. The sidebar already hides these destinations, but a direct URL
// bypasses it — the dispatch itself must fail closed. The backend remains
// the authorization boundary; this only prevents rendering dead controls.
function AdminAreaDenied({ onBack }: { onBack: () => void }) {
  return (
    <div style={{ padding: '40px', textAlign: 'center', color: 'var(--neutral-500)' }} role="alert">
      <div style={{ fontSize: '1rem', fontWeight: 600, color: 'var(--ink)', marginBottom: '8px' }}>
        Administrator access required
      </div>
      <div style={{ fontSize: '0.9rem', marginBottom: '16px' }}>
        This area is only available to administrators.
      </div>
      <button role="button" aria-label="Back to dashboard"
        onClick={onBack}
        style={{ padding: '8px 16px', background: 'var(--neutral-100)', color: 'var(--neutral-500)', border: '1px solid var(--divider)', borderRadius: 'var(--radius)', cursor: 'pointer', fontSize: '0.85rem', fontWeight: 600 }}
      >
        Back to dashboard
      </button>
    </div>
  );
}

export function Home() {
  const reducedMotion = useReducedMotion();
  const [searchParams, setSearchParams] = useSearchParams();
  const navigate = useNavigate();
  const username = getAuthUsername();
  const userIsAdmin = getAuthIsAdmin();
  const userRole = getAuthRole();
  // D3: sales managers may create prospect accounts (admin-reviewed).
  const canCreateAccounts = userIsAdmin || getAuthSalesRole() === 'sales_manager';
  // UX audit #7: seed + persist the sidebar collapse preference through the
  // preferences module — it was the only appearance setting lost on reload.
  const [mobileNavOpen, setMobileNavOpen] = useState(false);
  const [sidebarCollapsed, setSidebarCollapsed] = useState<boolean>(
    () => getPreferences().sidebarCollapsed,
  );
  useEffect(() => {
    setPreference('sidebarCollapsed', sidebarCollapsed);
  }, [sidebarCollapsed]);
  const closeMobileNav = () => {
    setMobileNavOpen(false);
    window.setTimeout(() => document.getElementById('mobile-nav-toggle')?.focus(), 0);
  };
  useEffect(() => {
    if (!mobileNavOpen) return;
    const containFocus = (event: FocusEvent) => {
      const drawer = document.getElementById('navigation-shell');
      if (drawer && event.target instanceof Node && !drawer.contains(event.target)) {
        document.getElementById('mobile-nav-close')?.focus();
      }
    };
    document.addEventListener('focusin', containFocus);
    return () => document.removeEventListener('focusin', containFocus);
  }, [mobileNavOpen]);

  useEffect(() => {
    if (!mobileNavOpen || typeof window.matchMedia !== 'function') return;
    const mobile = window.matchMedia('(max-width: 700px)');
    const onResize = (event: MediaQueryListEvent) => { if (!event.matches) setMobileNavOpen(false); };
    mobile.addEventListener('change', onResize);
    return () => mobile.removeEventListener('change', onResize);
  }, [mobileNavOpen]);

  // Seed the view from the ?view= param so deep links (?view=customers) and
  // refreshes restore the intended view. Selection-required views can't
  // render without a selected use case (always null on a fresh mount), so
  // they land on the assessment list instead of a dead end.
  // FE-11: a selection-required view deep-linked with ?uc=<id> must NOT be
  // redirected to the assessment list up front — the uc-restore effect below
  // fetches the authorized record. Only redirect when there's no ?uc to
  // restore (the original dead-end guard).
  const [view, setView] = useState<string>(() => {
    const raw = searchParams.get('view');
    if (!raw) return 'dashboard';
    const v = normalizeView(raw);
    if (isSelectionRequiredView(v) && !searchParams.get('uc')) return 'assessment-list';
    return v;
  });
  const [selectedUseCase, setSelectedUseCase] = useState<UseCase | null>(null);
  const [scoredData, setScoredData] = useState<ScoredUseCaseResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [editMode, setEditMode] = useState(false);
  const [unreadCount, setUnreadCount] = useState(0);
  const [unreadStale, setUnreadStale] = useState(false);
  // F5: seed the customer selection from ?customer= so refresh/deep links
  // restore the customer's dashboard (WP23 F5 pain: "refresh loses the
  // customer context"). Only honored for the customers view.
  const [selectedCustomerName, setSelectedCustomerName] = useState<string | null>(() => {
    if (view !== 'customers') return null;
    return searchParams.get('customer');
  });
  const [customerAction, setCustomerAction] = useState<string | null>(null);
  // Customer to return to after save/cancel when an edit was started from a customer dashboard
  const [customerReturn, setCustomerReturn] = useState<string | null>(null);
  // FE-12: whether the assessment wizard holds unsaved changes — guards
  // sidebar navigation (the form's own Cancel + beforeunload cover the other
  // two abandonment paths). Reset when leaving the wizard (the form
  // unmounts on any other view, so the flag must not outlive it).
  const [wizardDirty, setWizardDirty] = useState(false);
  const [applicationSettingsDirty, setApplicationSettingsDirty] = useState(false);
  const [confirmLeaveWizard, setConfirmLeaveWizard] = useState(false);
  const pendingWizardNav = useRef<string | null>(null);
  useEffect(() => {
    if (view !== 'assessment-create') setWizardDirty(false);
  }, [view]);
  // Comments view (sidebar entry, no use case selected): state of the
  // first-accessible-use-case auto-select — 'loading' | 'empty' | 'error'.
  const [commentsStatus, setCommentsStatus] = useState<'loading' | 'empty' | 'error' | null>(null);
  const [commentsError, setCommentsError] = useState<string | null>(null);

  // WP23a F4: the overlay names the operation in flight + elapsed time, and
  // a 300s cap aborts the client wait (see LONG_OP_TIMEOUT_MS).
  const [loadingLabel, setLoadingLabel] = useState<string | null>(null);
  const [elapsed, setElapsed] = useState(0);
  const loadingOpRef = useRef<{ controller: AbortController; timer: ReturnType<typeof setTimeout> } | null>(null);
  // F4(d): the WS handler is created once (deps [username]); it reads the
  // current selection/label through refs so it never resubscribes.
  const selectedUseCaseRef = useRef<UseCase | null>(null);
  const loadingLabelRef = useRef<string | null>(null);

  const stopLoading = () => {
    if (loadingOpRef.current) {
      clearTimeout(loadingOpRef.current.timer);
      loadingOpRef.current = null;
    }
    setLoading(false);
    setLoadingLabel(null);
    setElapsed(0);
  };

  const startLoading = (label: string) => {
    if (loadingOpRef.current) clearTimeout(loadingOpRef.current.timer);
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), LONG_OP_TIMEOUT_MS);
    loadingOpRef.current = { controller, timer };
    setLoading(true);
    setLoadingLabel(label);
    setElapsed(0);
    return controller.signal;
  };

  const cancelLoading = () => {
    loadingOpRef.current?.controller.abort();
  };

  // view → URL: keep ?view= in sync with the active view so browser
  // back/forward, refresh, bookmarks, and deep links all track navigation.
  // The first write replaces (establishes the baseline without polluting
  // the history entry the user arrived on); later writes push, so every
  // in-app navigation is a restorable history step.
  //
  // `internalUrlWrites` records every view value this file has written to
  // the URL so the URL→view effect can recognize its OWN writes landing
  // (WP23a F1 root cause, the WP26 oscillation class re-opened through the
  // safety-net path): the safety-net redirects a selection-required view
  // (e.g. 'scoring-dashboard' → 'assessment-list') WITHOUT the URL having
  // caught up, and without this guard the URL→view effect re-applies the
  // stale URL value on the next commit, the safety-net fires again, and
  // view/URL ping-pong at effect rate (the pre-fix F1 cross-view buttons
  // hung the app). With the guard, internal writes are consumed, not
  // re-applied — only EXTERNAL URL changes (back/forward, manual URL
  // edits, deep-link loads) drive the view.
  const internalUrlWrites = useRef<Set<string>>(new Set());
  // F5: the same internal-write guard for the ?customer= param (single slot:
  // only the MOST RECENT internal write is suppressed, so back/forward to an
  // OLDER customer entry still applies — a Set would swallow it).
  const pendingCustomerWrite = useRef<string | null | undefined>(undefined);
  // FE-11: the internal-write guard for ?uc= (same single-slot pattern as
  // ?customer=) — our own uc write is consumed, not re-fetched.
  const pendingUcWrite = useRef<string | null | undefined>(undefined);
  const initialUrlSync = useRef(true);
  useEffect(() => {
    const next = new URLSearchParams(searchParams);
    const rawView = next.get('view');
    const viewSame = rawView === view;
    const legacyViewAlias = rawView === 'my-dashboard' && view === 'dashboard';
    // F5: ?customer= is scoped to the customers view (the initializer
    // honors it there only) — on other views the param is dropped from
    // the URL (it is inert there: a wizard refresh does not restore the
    // customer selection, so no point carrying it).
    const customersView = view === 'customers' || view === 'customer-create';
    const customerValue = customersView ? selectedCustomerName : null;
    const customerSame = (next.get('customer') ?? null) === customerValue;
    const areaSame = customersView || (!next.has('area') && !next.has('customer_uc'));
    const settingsView = view === 'settings' || view === 'settings-appearance';
    const settingsSame = settingsView || !next.has('settings_tab');
    // FE-11: ?uc= is scoped to selection-required views — carry the selected
    // use-case id so a refresh/direct-entry restores that record (dropped on
    // other views where it is inert).
    const ucValue = isSelectionRequiredView(view) ? (selectedUseCase ? String(selectedUseCase.id) : null) : null;
    const ucSame = (next.get('uc') ?? null) === ucValue;
    // FE-11 mount race: a deep-link ?uc= is present but the record is not yet
    // selected (the restore fetch is in flight). Do NOT drop the param now —
    // skip this write; the fetch's completion re-runs the writer with the
    // selection set (or clears ?uc on failure). Order-independent: derived
    // from props, not a ref the writer would run before.
    if (isSelectionRequiredView(view) && !selectedUseCase && searchParams.get('uc')) {
      return;
    }
    if (viewSame && customerSame && ucSame && areaSame && settingsSame) {
      initialUrlSync.current = false;
      return;
    }
    if (customerValue) {
      next.set('customer', customerValue);
    } else {
      next.delete('customer');
    }
    if (ucValue) {
      next.set('uc', ucValue);
    } else {
      next.delete('uc');
    }
    if (!customersView) { next.delete('area'); next.delete('customer_uc'); }
    if (!settingsView) next.delete('settings_tab');
    // Portfolio filters from another surface must not narrow a new dashboard.
    const sourceView = next.get('view');
    if (view === 'dashboard' && sourceView && normalizeView(sourceView) !== 'dashboard') {
      PORTFOLIO_FILTER_PARAMS.forEach(key => next.delete(key));
      next.delete('portfolio_scope');
    }
    next.set('view', view);
    if (!viewSame) internalUrlWrites.current.add(view);
    pendingCustomerWrite.current = customerValue;
    pendingUcWrite.current = ucValue;
    setSearchParams(next, { replace: initialUrlSync.current || legacyViewAlias });
    initialUrlSync.current = false;
    // Deps: [view, selectedCustomerName, selectedUseCase] — this effect must
    // NOT key on searchParams (WP26 root cause: re-running when the URL
    // changes reads the pre-update value and pushes stale state back into the
    // URL, oscillating view and URL). It runs only when the STATE changes and
    // reads the current render's searchParams (always the live URL).
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [view, selectedCustomerName, selectedUseCase]);

  // URL → view/customer: apply EXTERNAL URL changes (back/forward, direct
  // links, manual URL edits). Changes that match a value this file itself
  // wrote (internalUrlWrites / pendingCustomerWrite) are consumed and
  // skipped — re-applying our own write is what turned the safety-net
  // redirect into a view/URL oscillation (WP23a F1; WP26 established the
  // one-direction rule).
  useEffect(() => {
    const raw = searchParams.get('view');
    if (raw) {
      if (internalUrlWrites.current.has(raw)) {
        internalUrlWrites.current.delete(raw);
      } else {
        setView(normalizeView(raw));
      }
    }
    // F5: external customer-param changes (back/forward to a different
    // customer entry, manual edit). A pending internal write that matches
    // the param is consumed (our own write just landed — re-applying it is
    // how the WP26 oscillation class re-enters); anything else is applied.
    // (setSelectedCustomerName with an equal value is a no-op — React
    // bails out — so the null case needs no special-casing.)
    const cust = searchParams.get('customer') ?? null;
    const pending = pendingCustomerWrite.current;
    pendingCustomerWrite.current = undefined;
    if (!(pending !== undefined && pending === cust)) {
      setSelectedCustomerName(cust);
    }
  }, [searchParams]);

  // FE-11: restore a deep-linked use case (?uc=<id>) into the selection so a
  // selection-required view (scoring-dashboard, scoring-drilldown, detail)
  // reaches its content on refresh/direct-entry with a useful loading,
  // forbidden(404), and recovery state. External ?uc changes (back/forward,
  // manual edit) fetch via the API (backend enforces authorization); our OWN
  // writes (pendingUcWrite) are consumed so the URL sync doesn't re-fetch
  // (the WP23a F1 oscillation class, same guard as ?customer=).
  useEffect(() => {
    const ucId = searchParams.get('uc');
    const pending = pendingUcWrite.current;
    pendingUcWrite.current = undefined;
    if (pending === ucId) return; // our own write landed — consume, don't refetch
    if (!ucId) return;
    if (selectedUseCase?.id === Number(ucId)) return; // already selected
    let cancelled = false;
    (async () => {
      try {
        const uc = await api.get(Number(ucId));
        if (cancelled) return;
        setSelectedUseCase(uc);
      } catch {
        if (cancelled) return;
        // Forbidden or removed record: drop the stale selection AND clear the
        // ?uc param so the safety net redirects to the assessment list (the
        // param is no longer backed by a real, authorized record).
        setSelectedUseCase(null);
        pendingUcWrite.current = null;
        setSearchParams((prev) => {
          const next = new URLSearchParams(prev);
          next.delete('uc');
          return next;
        }, { replace: true });
      }
    })();
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [searchParams]);

  // Safety net: a selection-required view without a selected use case is a
  // dead end — redirect to the assessment list. (FE-11: when a ?uc deep-link
  // is still in flight the restore effect owns the selection, so the param
  // is present and we must NOT bounce it; only redirect when there is no ?uc
  // and no selection — the original dead-end case. Keys on searchParams too
  // so it re-checks once the restore effect clears a failed ?uc.)
  useEffect(() => {
    if (!selectedUseCase && isSelectionRequiredView(view) && !searchParams.get('uc')) {
      setView('assessment-list');
    }
  }, [view, selectedUseCase, searchParams]);

  const mainRef = useRef<HTMLElement | null>(null);
  useWorkspaceScroll(mainRef);

  // F4: refs for the once-created WS handler (see the WebSocket effect).
  useEffect(() => { selectedUseCaseRef.current = selectedUseCase; }, [selectedUseCase]);
  useEffect(() => { loadingLabelRef.current = loadingLabel; }, [loadingLabel]);

  // F4(a): 1s elapsed timer while an operation is in flight.
  useEffect(() => {
    if (!loading) return;
    const started = Date.now();
    const timer = setInterval(() => setElapsed(Math.floor((Date.now() - started) / 1000)), 1000);
    return () => clearInterval(timer);
  }, [loading]);

  // FE-12: guard navigation AWAY from a dirty assessment wizard. Returns true
  // if the navigation may proceed (clean wizard or same view); false otherwise
  // (a Stay/Discard confirm is surfaced via the sidebar path). The form's own
  // Cancel + the beforeunload hook cover the other abandonment paths.
  const guardWizardNav = (target: string): boolean => {
    if (view === 'admin-integrations' && applicationSettingsDirty && target !== view && !window.confirm('Discard unsaved application settings changes?')) return false;
    if (view === 'assessment-create' && wizardDirty && target !== 'assessment-create') {
      pendingWizardNav.current = target;
      setConfirmLeaveWizard(true);
      return false;
    }
    return true;
  };

  // Custom onNavigate wrapper that captures customer name
  const handleNavigate = (view: string, customerName?: string, action?: string) => {
    view = normalizeView(view);
    if (!guardWizardNav(view)) return;
    setCustomerAction(action && (view === 'customers' || view === 'customer-create') ? action : null);
    if (view === 'customers' && customerName) {
      setSelectedCustomerName(customerName);
      setView(view);
    } else {
      if (view === 'assessment-create') {
        // "New assessment" entry: always create mode — clear any stale edit state
        setEditMode(false);
        setCustomerReturn(null);
      }
      setView(view);
    }
  };

  // Sidebar / in-page navigation: going (back) to the customer list clears any
  // previously selected customer so the My Customers side list is shown.
  const doNav = (view: string) => {
    view = normalizeView(view);
    if (view === 'settings-appearance' && (searchParams.get('view') === 'settings-appearance' || searchParams.get('view') === 'settings')) {
      if (searchParams.get('settings_tab') !== 'appearance') {
        setSearchParams((previous) => {
          const next = new URLSearchParams(previous);
          next.set('settings_tab', 'appearance');
          return next;
        });
      }
    }
    setCustomerAction(null);
    if (view === 'customers') setSelectedCustomerName(null);
    if (view === 'assessment-create') {
      // "New assessment" entry: always create mode — clear any stale edit state
      setEditMode(false);
      setCustomerReturn(null);
    }
    setView(view);
  };
  const handleNav = (view: string) => {
    if (!guardWizardNav(view)) return;
    doNav(view);
  };

  // Comments view with no selection: auto-select the first accessible use
  // case so the sidebar Comments entry reaches a real thread. The honest
  // empty-state wording in the render covers the loading/empty/error windows.
  useEffect(() => {
    if (view !== 'collab-comments' || selectedUseCase) return;
    let cancelled = false;
    setCommentsStatus('loading');
    setCommentsError(null);
    (async () => {
      try {
        const useCases = await api.list({ status: '' });
        if (cancelled) return;
        if (useCases.length > 0) {
          setSelectedUseCase(useCases[0]);
          setCommentsStatus(null);
        } else {
          setCommentsStatus('empty');
        }
      } catch (err) {
        if (cancelled) return;
        setCommentsStatus('error');
        setCommentsError(err instanceof Error ? err.message : 'Failed to load use cases');
      }
    })();
    return () => { cancelled = true; };
  }, [view, selectedUseCase]);

  // WebSocket for real-time notification updates
  useEffect(() => {
    if (!username) return;
    const handler = (message: { type: string; data: unknown; timestamp: string }) => {
      const { type, data } = message;
      if (['scoring', 'status_change', 'comment', 'mention', 'user_added', 'user_removed', 'role_changed', 'notification_created'].includes(type)) {
        const dataObj = data as Record<string, unknown>;
        const targetUser = dataObj?.user_name as string;
        if (targetUser === username) {
          refreshUnreadCount();
        }
      }
      // F4(d): a scoring completion for the selected use case → refresh its
      // score (single api.get) + clear the matching busy state, so a
      // background score lands without a manual reload. The event is a
      // notification row (type + message + customer_id; the use case is
      // identified by its title in the deterministic message format —
      // backend/services/scoring.py).
      if (type === 'scoring') {
        const sel = selectedUseCaseRef.current;
        if (sel) {
          const dataObj = data as { customer_id?: number; message?: string };
          const titleMatch = /^Use case '([^']*)' has been scored/.exec(dataObj?.message ?? '')?.[1];
          if (titleMatch === sel.title && (dataObj?.customer_id == null || dataObj.customer_id === sel.customer_id)) {
            if (loadingLabelRef.current === `Scoring '${sel.title}'…`) {
              stopLoading();
            }
            api.get(sel.id).then((refreshed) => {
              if (refreshed) setSelectedUseCase(refreshed);
            }).catch(() => { /* advisory refresh — keep the last known state */ });
          }
        }
      }
    };
    // FE-04: keep the unsubscribe function (the old code subscribed and then
    // only called disconnect() on cleanup — the handler leaked across
    // StrictMode remounts and fired multiple times per event).
    const unsubscribe = ws.subscribe('*', handler);
    // FE-04: handle the connect rejection instead of leaving an unhandled
    // promise — the 30s polling fallback keeps the unread count fresh, and
    // the socket's own bounded backoff keeps retrying. Guarded so a
    // test-stubbed ws.connect() (vi.fn() → undefined) cannot crash the
    // effect; the real implementation always returns a Promise.
    const connectResult = ws.connect();
    if (connectResult && typeof connectResult.catch === 'function') {
      connectResult.catch((err) => {
        console.warn('[Home] notification WebSocket connect rejected:', err);
      });
    }

    return () => {
      if (typeof unsubscribe === 'function') unsubscribe();
      ws.disconnect();
    };
  }, [username]);

  const refreshUnreadCount = async () => {
    try {
      const unread = await api.getNotifications(1000, true);
      setUnreadCount(unread.length);
      setUnreadStale(false);
    } catch (err) {
      // Keep the last known count; the bell surfaces the stale state
      // (a 30-second background poll — deliberately no full-page banner)
      console.warn('[Home] unread notification refresh failed:', err);
      setUnreadStale(true);
    }
  };

  // Periodic unread count refresh
  useEffect(() => {
    const interval = setInterval(refreshUnreadCount, 30000);
    refreshUnreadCount();
    return () => clearInterval(interval);
  }, [username]);

  const handleScore = async (useCaseId: number, useCaseTitle?: string) => {
    // F4(a/c): named overlay + AbortController (300s cap + Cancel).
    const signal = startLoading(`Scoring '${useCaseTitle ?? selectedUseCase?.title ?? 'use case'}'…`);
    try {
      // api.score returns the {use_case, scores} envelope directly —
      // pass it through; do not re-wrap it (the re-wrap put the whole
      // envelope under `scores`, so dimension_scores was undefined).
      const scoringResult = await api.score(useCaseId, signal);
      // FE-01: the scored result is associated with the use case it
      // actually belongs to — adopt the returned record as THE selection
      // so the results, drill-down, comments, and Back all refer to the
      // same record (scoring a row from the list without viewing it no
      // longer strands an unrelated pre-existing selection).
      setSelectedUseCase(scoringResult.use_case);
      setScoredData(scoringResult);
      setView('scoring-dashboard');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Scoring failed');
    } finally {
      stopLoading();
    }
  };

  const handleCreate = async (data: any) => {
    // FE-06: the form is the error owner — await the callback and let
    // failures propagate (the form shows an actionable save error and keeps
    // the input). A successful create navigates; the overlay's Cancel aborts
    // the client wait via the same signal.
    const signal = startLoading('Creating use case…');
    try {
      await api.create(data, signal);
    } finally {
      stopLoading();
    }
    // Save succeeded: leave the wizard.
    setView('assessment-list');
  };

  const handleEdit = async (data: any) => {
    if (!selectedUseCase) return;
    const signal = startLoading('Saving changes…');
    // FE-06: refresh from the mutation's response, not by scanning the first
    // list page — a save followed by a refresh failure is NOT an unsaved
    // edit, and the record is always present (no silent 100-row truncation).
    const updated = await api.update(selectedUseCase.id, data, signal);
    stopLoading();
    setSelectedUseCase(updated);
    const ret = customerReturn;
    setCustomerReturn(null);
    if (ret) {
      // Edit was started from a customer dashboard: return to that customer
      setSelectedCustomerName(ret);
      setView('customers');
    } else {
      setView('detail');
    }
  };

  const handleSelect = (useCase: UseCase) => {
    setSelectedUseCase(useCase);
    // FE-01: cached scoring data belongs to a SPECIFIC record — a new
    // selection must not render (or Back-navigate to) another record's
    // results.
    setScoredData(null);
    setView('detail');
  };

  // Edit a use case from a customer dashboard: open the wizard in EDIT mode
  // with all previously defined factors pre-filled; remember the customer so
  // the save/cancel path returns to that customer's dashboard.
  const handleEditFromCustomer = (uc: UseCase) => {
    setSelectedUseCase(uc);
    setEditMode(true);
    setCustomerReturn(uc.customer_name ?? null);
    setView('assessment-create');
  };

  // WP23a (F1): customer-detail cross-view handoff. The customer dashboard
  // selects its use case LOCALLY; before the view changes, the use case is
  // handed up to Home state so selection-required views (scoring-dashboard,
  // scoring-drilldown) render FOR THAT use case and collab-comments opens
  // ITS thread — not the dead-end page or the auto-selected first
  // accessible use case (the pre-fix F1 behavior).
  const handleOpenScoring = (uc: UseCase) => {
    setSelectedUseCase(uc);
    setView('scoring-dashboard');
  };
  const handleOpenDrilldown = (uc: UseCase) => {
    setSelectedUseCase(uc);
    setView('scoring-drilldown');
  };
  const handleOpenComments = (uc: UseCase) => {
    setSelectedUseCase(uc);
    setView('collab-comments');
  };

  const handleLogout = () => {
    clearSessionReturn();
    clearAuth();
    navigate('/login');
  };

  const renderContent = () => {
    if (view === 'dashboard') return <HomeDashboard onNavigate={handleNavigate} isAdmin={userIsAdmin} username={username} />;
    // Deterministic key (not Date.now()): any Home re-render with the wizard
    // open (WS unread change, error/loading flags) must not remount it and
    // wipe in-progress input. Leaving the view unmounts the component, so
    // each entry still starts a fresh wizard.
    if (view === 'assessment-create') return <AssessmentForm key={editMode && selectedUseCase ? 'edit-' + selectedUseCase.id : 'create'} onSubmit={handleCreate} onCancel={() => { setEditMode(false); const ret = customerReturn; setCustomerReturn(null); if (ret) { setSelectedCustomerName(ret); setView('customers'); } else { setView('assessment-list'); } }} onEdit={handleEdit} editMode={editMode} initialData={selectedUseCase} onDirtyChange={setWizardDirty} />;
    if (view === 'assessment-list') return <AssessmentList onSelect={handleSelect} onScore={(uc: UseCase) => handleScore(uc.id, uc.title)} onEdit={(uc: UseCase) => { setSelectedUseCase(uc); setEditMode(true); setCustomerReturn(null); setView('assessment-create'); }} />;
    if (view === 'detail' && !selectedUseCase) return (
      // One-frame guard for deep links / edge paths that lose the selection;
      // the redirect effect above bounces to the assessment list.
      <div style={{ padding: '40px', textAlign: 'center', color: 'var(--neutral-500)' }}>
        <div style={{ fontSize: '1rem' }}>Please select a use case from the list to view its detail.</div>
        <div style={{ marginTop: '16px' }}>
          <button role="button" aria-label="Go to assessment list"
            onClick={() => setView('assessment-list')}
            style={{ padding: '8px 16px', background: 'var(--brand-500)', color: 'var(--neutral-0)', border: 'none', borderRadius: 'var(--radius)', cursor: 'pointer', fontSize: '0.85rem', fontWeight: 600 }}
          >
            Go to Assessments
          </button>
        </div>
      </div>
    );
    if (view === 'detail' && selectedUseCase) return (
      // WP23a step 0 (F6): the shared detail component — the ~165-line
      // inline copy is gone (it had drifted from the CustomerDashboard
      // variant: labels + navigation targets).
      <UseCaseDetail
        useCase={selectedUseCase}
        // Part 13 WS5 (R8): AI scoring entry points are hidden on
        // generic-round use cases (the backend 422s them) — no dead controls.
        scoringUnavailableReason={selectedUseCase.assessment_type === 'generic' ? AI_SCORING_REQUIRES_AI_ASSESSMENT : null}
        onEdit={(uc) => { setSelectedUseCase(uc); setEditMode(true); setView('assessment-create'); }}
        onScore={(uc) => handleScore(uc.id)}
        onOpenScoring={handleOpenScoring}
        onOpenDrilldown={handleOpenDrilldown}
        onOpenComments={handleOpenComments}
        onBack={() => setView('assessment-list')}
      />
    );
    if (view === 'scoring-dashboard') {
      if (!selectedUseCase) return <div style={{ padding: '40px', textAlign: 'center', color: 'var(--neutral-500)' }}>Please select a use case from the list to view scoring results.</div>;
      // FE-01: cached scoring data is only shown when it belongs to the
      // current selection (a late response for an abandoned record must
      // not render over the one the user is viewing).
      const requestedId = searchParams.get('uc');
      if (requestedId && Number(requestedId) !== selectedUseCase.id) return <p role="status">Loading scoring results…</p>;
      const restored = scoredData?.use_case === selectedUseCase ? scoredData : storedScoring(selectedUseCase);
      return <ScoringDashboard key={selectedUseCase.id} scoredData={restored || { use_case: selectedUseCase, scores: { dimension_scores: [], overall_score: 0, reasoning: '', scored_at: '', recommendations: [] } }} onBack={() => setView('detail')} />;
    }
    if (view === 'scoring-history') {
      if (!selectedUseCase) return <div style={{ padding: '40px', textAlign: 'center', color: 'var(--neutral-500)' }}>Please select a use case from the list to view score history.</div>;
      return <ScoreDrillDown useCaseId={selectedUseCase.id} onBack={() => setView('detail')} showHistoryOnly={true} />;
    }
    if (view === 'scoring-drilldown' && selectedUseCase) return <ScoreDrillDown useCaseId={selectedUseCase.id} onBack={() => setView('detail')} />;
    if (view === 'analytics-matrix') return <ImpactMatrix onBack={() => setView('dashboard')} />;
    if (view === 'analytics-dept') return <DeptComparison onBack={() => setView('dashboard')} />;
    if (view === 'analytics-correlation' || view === 'analytics-trends') return <AnalyticsDashboard onBack={() => setView('dashboard')} />;
    if (view === 'business-impact') return <BusinessImpact onBack={() => setView('dashboard')} />;
    if (view === 'admin-integrations') return userIsAdmin ? <IntegrationSettings onDirtyChange={setApplicationSettingsDirty} onBack={() => setView('dashboard')} /> : <AdminAreaDenied onBack={() => setView('dashboard')} />;
    if (view === 'gi-import') return <IntelligenceImport onOpenCustomer={(name: string) => { setSelectedCustomerName(name); setView('customers'); }} />;
    if (view === 'export') return <ExportPage />;
    if (view === 'export-pdf') return <PDFReport onBack={() => setView('export')} />;
    if (view === 'export-excel') return <ExportPage initialFormat="excel" />;
    if (view === 'assessment-bulk') return <BulkScore onBack={() => setView('assessment-list')} />;
    if (view === 'assessment-templates') return <TemplatesPage onBack={() => setView('assessment-list')} />;
    // Fallback: redirect parent section routes to their first child
    if (view === 'assessment') return <AssessmentList onSelect={handleSelect} onScore={(uc: UseCase) => handleScore(uc.id, uc.title)} onEdit={(uc: UseCase) => { setSelectedUseCase(uc); setEditMode(true); setCustomerReturn(null); setView('assessment-create'); }} />;
    if (view === 'settings') return <Settings onBack={() => setView('dashboard')} />;
    if (view === 'settings-appearance') return <Settings onBack={() => setView('dashboard')} />;
    if (view === 'customers') return <CustomerDashboard onNavigate={handleNav} onEditUseCase={handleEditFromCustomer} onOpenScoring={handleOpenScoring} onOpenDrilldown={handleOpenDrilldown} onOpenComments={handleOpenComments} onCustomerSelect={setSelectedCustomerName} selectedCustomerName={selectedCustomerName} initialAction={customerAction} />;
    if (view === 'admin-global') return <GlobalAdminDashboard userIsAdmin={userIsAdmin} userRole={userRole} />;
    if (view === 'admin-ownership') return <CustomerOwnership onOpenCustomer={(name: string) => { setSelectedCustomerName(name); setView('customers'); }} />;
    if (view === 'customer-create') return canCreateAccounts ? (
      <CustomerDashboard onNavigate={handleNav} onEditUseCase={handleEditFromCustomer} onOpenScoring={handleOpenScoring} onOpenDrilldown={handleOpenDrilldown} onOpenComments={handleOpenComments} onCustomerSelect={setSelectedCustomerName} isNewCustomer={true} initialAction={customerAction} />
    ) : <AdminAreaDenied onBack={() => setView('customers')} />;
    if (view === 'admin' || view.startsWith('admin-')) return userIsAdmin ? <AdminPage onNavigate={(v: string) => setView(v)} activeView={view === 'admin-users' ? 'all-users' : 'pending'} /> : <AdminAreaDenied onBack={() => setView('dashboard')} />;
    if (view === 'collab-comments') {
      if (selectedUseCase) return <CommentThread useCaseId={selectedUseCase.id} useCaseTitle={selectedUseCase.title} onBack={() => setView('detail')} />;
      return (
        <div style={{ padding: '40px', textAlign: 'center', color: 'var(--neutral-500)' }}>
          <div style={{ fontSize: '1rem' }}>Select a use case to view its comment thread</div>
          {commentsStatus === 'loading' && (
            <div role="status" aria-live="polite">Opening the first available use case…</div>
          )}
          {commentsStatus === 'empty' && (
            <div>No use cases are available to display a comment thread.</div>
          )}
          {commentsStatus === 'error' && (
            <div role="alert" aria-live="assertive">{commentsError}</div>
          )}
        </div>
      );
    }
    if (view === 'collab-notifications') return <NotificationsPage onBack={() => setView('dashboard')} username={username} />;
    return <div style={{ padding: '40px', textAlign: 'center', color: 'var(--neutral-500)' }}>Select a section from the sidebar</div>;
  };

  return (
    <>
      <style>{`@keyframes spin { to { transform: rotate(360deg); } }
        #mobile-nav-toggle, #mobile-nav-close, #mobile-nav-backdrop { display: none; }
        #navigation-shell { display: contents; }
        @media (max-width: 700px) {
          #mobile-nav-toggle, #mobile-nav-close { display: inline-flex; }
          #mobile-nav-backdrop[data-open="true"] { display: block; position: fixed; inset: 0; z-index: 199; border: 0; background: rgba(0,0,0,.45); }
          #navigation-shell { display: none; position: fixed; inset: 0 auto 0 0; z-index: 200; max-width: 100vw; }
          #navigation-shell[data-open="true"] { display: block; }
          #navigation-shell aside { max-width: 100vw; }
          #main-content { min-width: 0; }
        }
        @media (max-width: 250px) { #main-content > header { flex-wrap: wrap; } #main-content details button { max-width: 100%; overflow-wrap: anywhere; } }`}</style>
      <div style={{ display: 'flex', minHeight: 'var(--full-viewport, 100vh)', background: 'var(--neutral-0)' }}>
      <button id="mobile-nav-backdrop" data-open={mobileNavOpen} aria-hidden="true" tabIndex={-1} onClick={closeMobileNav} />
      <div id="navigation-shell" data-open={mobileNavOpen} role={mobileNavOpen ? 'dialog' : undefined} aria-modal={mobileNavOpen ? true : undefined} aria-label={mobileNavOpen ? 'Navigation' : undefined} onKeyDown={event => {
        // The focus trap (and Escape-to-close) is dialog behavior: it only
        // applies while the mobile drawer is open. On desktop the shell is a
        // plain navigation region — Tab must escape into the main content,
        // and a stray Escape must not be swallowed. (CO-04 keyboard
        // acceptance 2026-11-06: the unconditional trap held Tab inside the
        // sidebar at 768/1024/1440.)
        if (!mobileNavOpen) return;
        if (event.key === 'Escape') { event.preventDefault(); closeMobileNav(); return; }
        if (event.key !== 'Tab') return;
        const controls = Array.from(event.currentTarget.querySelectorAll<HTMLElement>('button:not([disabled]), a[href], input:not([disabled]), select:not([disabled]), [tabindex="0"]')).filter(el => el.getClientRects().length > 0);
        if (!controls.length) { event.preventDefault(); return; }
        const first = controls[0], last = controls[controls.length - 1];
        if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
        else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
      }}>
      <button id="mobile-nav-close" type="button" aria-label="Close navigation" onClick={closeMobileNav} style={{ position: 'absolute', right: '8px', top: '8px', zIndex: 1, padding: '8px', border: '1px solid var(--divider)', borderRadius: 'var(--radius)', cursor: 'pointer' }}>✕</button>
      <Sidebar
        activeView={view}
        onNavigate={next => { handleNav(next); if (mobileNavOpen) closeMobileNav(); }}
        username={username}
        onLogout={handleLogout}
        isCollapsed={sidebarCollapsed}
        onToggle={() => setSidebarCollapsed(prev => !prev)}
        is_admin={userIsAdmin}
        userRole={userRole}
        canCreateProspects={!userIsAdmin && canCreateAccounts}
      />
      </div>

      <main id="main-content" ref={mainRef} style={{ flex: 1, overflow: 'auto' }} tabIndex={-1}>
        <header style={{
          background: 'var(--neutral-0)',
          borderBottom: '1px solid var(--divider)',
          padding: '12px clamp(8px, 3vw, 24px)',
          gap: '8px',
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          position: 'sticky',
          top: 0,
          zIndex: 100,
        }}>
          <button id="mobile-nav-toggle" type="button" aria-label={mobileNavOpen ? 'Close navigation' : 'Open navigation'} aria-expanded={mobileNavOpen} aria-controls="navigation-shell" onClick={() => { setMobileNavOpen(true); setTimeout(() => document.getElementById('mobile-nav-close')?.focus(), 0); }} style={{ border: '1px solid var(--divider)', borderRadius: 'var(--radius)', padding: '8px', background: 'var(--neutral-0)', cursor: 'pointer' }}>☰</button>
          <h2 style={{ margin: 0, fontSize: '1.2rem', color: 'var(--ink)', fontWeight: 600 }}>
            {getViewLabel(view)}
          </h2>

          {/* Notification Bell */}
          <Suspense fallback={
            <span
              aria-hidden="true"
              style={{ display: 'inline-block', width: '32px', height: '32px', borderRadius: '50%', border: '2px solid var(--divider)', borderTopColor: 'var(--brand-500)', animation: reducedMotion ? 'none' : 'spin 1s linear infinite' }}
            />
          }>
            <NotificationBell unreadCount={unreadCount} stale={unreadStale} onNavigate={handleNav} />
          </Suspense>
        </header>

        {error && (
          <div role="alert" aria-live="assertive" style={{
            padding: '12px 24px',
            background: 'var(--status-negative-soft)',
            borderLeft: '4px solid var(--status-negative)',
            margin: 0,
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
          }}>
            <span style={{ color: 'var(--status-negative)', fontWeight: 500 }}><span aria-hidden="true">⚠️ </span>{error}</span>
            <button role="button" aria-label="Dismiss error notification"
              onClick={() => setError(null)}
              style={{ background: 'none', border: 'none', color: 'var(--status-negative)', cursor: 'pointer', fontSize: '1.2rem' }}
            >
              X
            </button>
          </div>
        )}

        {loading && createPortal(
          <div role="status" aria-live="polite" aria-busy="true" style={{
            position: 'fixed',
            top: 0,
            left: 0,
            right: 0,
            bottom: 0,
            background: 'color-mix(in srgb, var(--neutral-0) 90%, transparent)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            zIndex: 1000,
          }}>
            {/* F4(a): the operation in flight is named (not the generic
                "Loading content…") + elapsed time; Cancel aborts the client
                wait (F4c — the server-side work may still finish). */}
            <div style={{ textAlign: 'center', color: 'var(--neutral-700)' }}>
              <div style={{ fontSize: '1.1rem', fontWeight: 500 }}>{loadingLabel || 'Loading content…'}</div>
              {elapsed > 0 && (
                <div style={{ fontSize: '0.85rem', color: 'var(--neutral-500)', marginTop: '6px' }}>{elapsed}s elapsed</div>
              )}
              <button role="button" aria-label="Cancel long operation"
                onClick={cancelLoading}
                style={{ marginTop: '14px', padding: '8px 18px', background: 'var(--neutral-0)', color: 'var(--status-negative)', border: '1px solid var(--status-negative)', borderRadius: 'var(--radius)', cursor: 'pointer', fontSize: '0.9rem', fontWeight: 600 }}
              >
                Cancel
              </button>
            </div>
          </div>,
          document.body
        )}

        {/* FE-12: guard for leaving a dirty assessment wizard via sidebar /
            in-page navigation. Stay cancels the navigation (keeps the draft);
            Discard clears the dirty flag and navigates once. */}
        {confirmLeaveWizard && createPortal(
          <div role="dialog" aria-modal="true" aria-label="Discard unsaved assessment?"
            style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.5)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 1200, padding: 16 }}>
            <div style={{ background: 'var(--neutral-0)', borderRadius: 'var(--radius)', boxShadow: 'var(--shadow-card)', maxWidth: 440, width: '100%', padding: 24 }}>
              <h2 style={{ margin: '0 0 8px', fontSize: '1.1rem', color: 'var(--ink)' }}>Leave this assessment?</h2>
              <p style={{ margin: '0 0 20px', color: 'var(--neutral-500)', fontSize: '0.9rem' }}>
                You have unsaved changes in the assessment wizard. If you leave now, they will be lost.
              </p>
              <div style={{ display: 'flex', gap: 12, justifyContent: 'flex-end' }}>
                <button role="button" aria-label="Stay and keep editing"
                  onClick={() => { setConfirmLeaveWizard(false); pendingWizardNav.current = null; }}
                  style={{ padding: '10px 18px', background: 'var(--neutral-100)', border: '1px solid var(--divider)', borderRadius: 'var(--radius)', cursor: 'pointer', fontSize: '0.9rem', color: 'var(--neutral-700)', fontWeight: 600 }}>
                  Stay
                </button>
                <button role="button" aria-label="Discard and leave"
                  onClick={() => { const target = pendingWizardNav.current; pendingWizardNav.current = null; setConfirmLeaveWizard(false); setWizardDirty(false); if (target) doNav(target); }}
                  style={{ padding: '10px 18px', background: 'var(--status-negative)', border: 'none', borderRadius: 'var(--radius)', cursor: 'pointer', fontSize: '0.9rem', color: 'var(--neutral-0)', fontWeight: 600 }}>
                  Discard
                </button>
              </div>
            </div>
          </div>,
          document.body
        )}

        <div style={{ paddingTop: '20px' }}>
          <Suspense fallback={<LoadingFallback />}>
            {renderContent()}
          </Suspense>
        </div>
      </main>
    </div>
    </>
  );
}
