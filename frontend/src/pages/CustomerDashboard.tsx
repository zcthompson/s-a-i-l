import { useWorkspaceActions } from '../lib/useWorkspaceActions';
import { useAssessmentRounds } from '../lib/useAssessmentRounds';
import { KIND_AREAS, useCustomerRecord } from '../lib/useCustomerRecord';
import { SelectedCustomerRecord } from '../components/SelectedCustomerRecord';
import { lazy, useEffect, useId, useMemo, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { api, getAuthIsAdmin, getAuthSalesRole } from '../lib/api';
import { ws } from '../lib/websocket';
import { UseCase, Customer, AssessmentType } from '../types/use_case';
import { AssessmentForm } from '../components/AssessmentForm';
import { UseCaseDetail } from '../components/UseCaseDetail';
import { TemplatesPage } from './TemplatesPage';
import { BusinessImpact } from './BusinessImpact';
import { BulkScore, AI_SCORING_REQUIRES_AI_ASSESSMENT } from '../components/BulkScore';
import { DeptComparison } from '../components/DeptComparison';
import { AnalyticsDashboard } from '../components/AnalyticsDashboard';
import { CustomerExport } from '../components/CustomerExport';
import { CustomerProjections } from '../components/CustomerProjections';
import { CustomerKnowledgeBrowser } from '../components/CustomerKnowledgeBrowser';
import { TechnologyInventory } from '../components/TechnologyInventory';
import { SalesNotes } from '../components/SalesNotes';
import { ContactsPanel } from '../components/ContactsPanel';
import { ActivitiesPanel } from '../components/ActivitiesPanel';
import { TasksPanel } from '../components/TasksPanel';
import { AccountBriefPanel } from '../components/AccountBriefPanel';
import { AccountTimelinePanel } from '../components/AccountTimelinePanel';
import AccountSearchPanel from '../components/AccountSearchPanel';
import { AccountStrategyPanel } from '../components/AccountStrategyPanel';
import { AccountOverview, IntelligencePanels } from '../components/AccountOverview';
import { CustomerIntelligenceConstellation } from '../components/CustomerIntelligenceConstellation';
import { CustomerTeam } from '../components/CustomerTeam';
import { SalesEvaluation } from '../components/SalesEvaluation';
import { DepartmentManager } from '../components/DepartmentManager';
import { CustomerHeader } from '../components/CustomerHeader';
import { CustomerAliasesField } from '../components/CustomerAliasesField';
import { CustomerSalesTeam } from '../components/CustomerSalesTeam';
import { Breadcrumbs, RowActions, SegmentedNav } from '../components/workspacePrimitives';
import { OpportunitiesPanel } from '../components/OpportunitiesPanel';
import { DealsPanel } from '../components/DealsPanel';
import { CustomerPipeline } from '../components/CustomerPipeline';
import { CustomerRedHatOpportunities } from '../components/CustomerRedHatOpportunities';
import { CustomerRvTools } from '../components/CustomerRvTools';
import { CustomerListPager } from '../components/CustomerListPager';
import { PortfolioFilterBar } from '../components/PortfolioFilterBar';
import { activeFilterSummary, filterRows, isFiltered, sortRows } from '../lib/portfolioNav';
import type { NavDefaults, PortfolioNavRow, SortKey } from '../lib/portfolioNav';
import { paginateNav, usePortfolioNavState } from '../lib/usePortfolioNavState';
import { useCustomerArea } from '../lib/useCustomerArea';

const ThirdPartyServices = lazy(() => import('../components/ThirdPartyServices'));

// the My Customers side list defaults to A–Z (client-side over
// the complete authorized list; 'newest' stays = payload order). The default
// state serializes to no nav params.
const SIDE_LIST_NAV_DEFAULTS: NavDefaults = { defaultSort: { sort: 'name', dir: 'asc' } };
const SIDE_LIST_SORT_KEYS: readonly SortKey[] = ['name', 'newest', 'vertical', 'branch', 'owner'];
type SideListRow = PortfolioNavRow & { source: Customer };

interface DepartmentObject {
  id: number;
  name: string;
  use_case_count: number;
}

interface CustomerDashboardProps {
  onNavigate: (view: string) => void;
  onEditUseCase?: (useCase: UseCase) => void;
  // (F1): cross-view handoff — the parent (Home) receives the
  // locally-selected use case when the detail tab opens the scoring
  // dashboard / drill-down / comments, so those views render for THAT
  // use case (the pre-fix behavior navigated without a selection:
  // dead-end, or the auto-selected first accessible use case).
  onOpenScoring?: (useCase: UseCase) => void;
  onOpenDrilldown?: (useCase: UseCase) => void;
  onOpenComments?: (useCase: UseCase) => void;
  // F5: in-page customer selection is synced to the URL (?customer=)
  // by the parent (Home) — called with the selected name (or null when
  // cleared) so refresh / Back / Forward restore the selection.
  onCustomerSelect?: (name: string | null) => void;
  isNewCustomer?: boolean;
  selectedCustomerName?: string | null;
  initialAction?: string | null;
}

export function CustomerDashboard({ onNavigate, onEditUseCase, onOpenScoring, onOpenDrilldown, onOpenComments, onCustomerSelect, isNewCustomer, selectedCustomerName, initialAction }: CustomerDashboardProps) {
  const [customers, setCustomers] = useState<Customer[]>([]);
  const [selectedCustomer, setSelectedCustomer] = useState<Customer | null>(null);
  const [customerUseCases, setCustomerUseCases] = useState<UseCase[]>([]);
  const [departmentObjects, setDepartmentObjects] = useState<DepartmentObject[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedUseCase, setSelectedUseCase] = useState<UseCase | null>(null);
  const [newAssessmentOpen, setNewAssessmentOpen] = useState(false);
  const [newAssessmentMode, setNewAssessmentMode] = useState<'template' | 'blank'>('template');
  // the customer workspace navigation is two levels deep
  // a primary area (Overview | Sales | Intelligence |
  // Discovery & Value | Team) plus a per-area secondary rail. `area`
  // owns both levels — the detail view is a transient secondary of the
  // current area (use-case rows still open it from any table).
  const [area, setArea, detailId, openCustomerDetail] = useCustomerArea();
  const { data: workspaceActions, error: actionsError, retry: retryActions } = useWorkspaceActions(selectedCustomer?.id);
  const [quickCreate, setQuickCreate] = useState<{ customer: number; target: string; request: number; id?: number } | null>(null);
  const [recordRefresh, setRecordRefresh] = useState(0);
  const workspacePanelId = useId();
  const customerRecord = useCustomerRecord(selectedCustomer?.id, area);
  const [detailError, setDetailError] = useState<string | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [scoreLoading, setScoreLoading] = useState(false);
  const [showNewCustomerForm, setShowNewCustomerForm] = useState(false);
  const [newCustomerName, setNewCustomerName] = useState('');
  const [newCustomerDesc, setNewCustomerDesc] = useState('');
  const [newCustomerVertical, setNewCustomerVertical] = useState('');
  const [editVertical, setEditVertical] = useState('');
  const [verticals, setVerticals] = useState<string[]>([]);
  const [creating, setCreating] = useState(false);
  const [userRole, setUserRole] = useState<string>('member');
  const [userAccess, setUserAccess] = useState<boolean>(false);
  const [userLoading, setUserLoading] = useState(true);
  const [userAccessError, setUserAccessError] = useState(false);
  const [accessCustomer, setAccessCustomer] = useState<string | null>(null);
  const [accessRetry, setAccessRetry] = useState(0);
  const accessCheckSeq = useRef(0);
  const { assessments, roundsLoading, roundsLoadError, loadAssessments } = useAssessmentRounds(selectedCustomer?.name);
  const [newRoundName, setNewRoundName] = useState('');
  // the round type is an explicit choice — null until the
  // user picks one (no silent default in the UI). Purpose is optional.
  const [newRoundType, setNewRoundType] = useState<AssessmentType | null>(null);
  const [newRoundPurpose, setNewRoundPurpose] = useState('');
  const [roundsBusy, setRoundsBusy] = useState(false);
  const [editDescription, setEditDescription] = useState('');
  const [mutationBusy, setMutationBusy] = useState(false);
  const [mutationError, setMutationError] = useState<string | null>(null);
  const [mutationStatus, setMutationStatus] = useState<string | null>(null);
  // F12: round create/archive failures are a local, inline error in
  // the Assessment Rounds card — not the view-level load error (which used
  // to unmount the whole dashboard for a page reload).
  const [roundError, setRoundError] = useState<string | null>(null);
  // direct use-case add/remove from the Overview. The backend CRUD +
  // junction authorization already exist (/api/use-cases/); these hold the
  // missing frontend affordance's state.
  const [showNewUcForm, setShowNewUcForm] = useState(false);
  const [newUcTitle, setNewUcTitle] = useState('');
  const [newUcDesc, setNewUcDesc] = useState('');
  const [newUcDept, setNewUcDept] = useState('');
  const [newUcStatus, setNewUcStatus] = useState('draft');
  const [ucBusy, setUcBusy] = useState(false);
  const [ucError, setUcError] = useState<string | null>(null);
  const [ucStatus, setUcStatus] = useState<string | null>(null);
  // account management (Edit Customer /
  // Departments / Remove Customer) lives in the header settings menu, not
  // in the tab model — `settingsDialog` holds the transient destination
  // (null = none). `edit` / `remove` remain valid deep-link targets from
  // MyDashboard (rendered as this overlay, never as nav areas).
  const [settingsDialog, setSettingsDialog] = useState<'edit' | 'remove' | null>(null);
  const appliedAction = useRef<string | null>(null);
  const canManageCustomer = getAuthIsAdmin() || userRole === 'owner';
  // Aliases: owner or admin PLUS sales_admin (the alias section is
  // import-matching metadata the sales admin manages;
  // mirrors the backend gate exactly). Separate from canManageCustomer —
  // the sales admin must NOT gain use-case delete etc. from this.
  const canManageAliases = canManageCustomer || getAuthSalesRole() === 'sales_admin';
  // a non-admin sales manager creates an admin-reviewed prospect.
  const creatingProspect = !getAuthIsAdmin() && getAuthSalesRole() === 'sales_manager';
  // role gates mirror the backend authorization exactly:
  // create → owner or member (auditor/none get 403), delete → owner or admin
  // (members get 403 — do not surface a delete they cannot execute).
  const canAddUseCase = workspaceActions?.capabilities.use_case ?? false;
  const canDeleteUseCase = canManageCustomer && canAddUseCase;

  // Prefill the edit form and clear mutation state when the selected
  // customer changes. Keyed on id ONLY (not description): after a Save the
  // description changes too, and a description dep would re-fire this effect
  // and wipe the "saved" confirmation immediately.
  useEffect(() => {
    setEditDescription(selectedCustomer?.description || '');
    setEditVertical(selectedCustomer?.vertical || '');
    setMutationError(null);
    setMutationStatus(null);
    setRoundError(null);
    setNewAssessmentOpen(false);
    setNewRoundType(null);
    setNewRoundPurpose('');
    setSettingsDialog(null);
  // eslint-disable-next-line react-hooks/exhaustive-deps -- pre-existing dependency list; change only with UI verification
  }, [selectedCustomer?.id]);

  // Transient deep-link action (MyDashboard View/Score/Edit/Remove). Home
  // clears the action on sidebar navigation, which resets the ref; switching
  // customers in-page keeps the last applied action (the sub-view follows the
  // selected customer). Not URL-synced, matching the selectedCustomerName
  // transient pattern.
  //
  // the deep-link targets live under the restructured
  // navigation — bulk-score under the Discovery & Value area (PRIMARY_OF below);
  // edit/remove render inside the Overview area (moved out of the
  // tab model into the header settings menu).
  useEffect(() => {
    if (selectedCustomer && initialAction?.startsWith('deal:') && appliedAction.current !== initialAction) {
      const id = Number(initialAction.slice(5));
      if (Number.isSafeInteger(id) && id > 0) customerRecord.select('deal', id);
      appliedAction.current = initialAction;
      return;
    }
    const allowed = ['overview', 'bulk-score', 'edit', 'remove'];
    if (selectedCustomer && initialAction && allowed.includes(initialAction) && appliedAction.current !== initialAction) {
      // edit/remove are no longer areas — the settings overlay
      // renders them (MyDashboard deep links still resolve here).
      if (initialAction === 'edit' || initialAction === 'remove') {
        setSettingsDialog(initialAction);
        setArea('overview');
      } else {
        setArea(initialAction);
      }
      appliedAction.current = initialAction;
    }
    if (!initialAction) appliedAction.current = null;
  // eslint-disable-next-line react-hooks/exhaustive-deps -- pre-existing dependency list; change only with UI verification
  }, [initialAction, selectedCustomer?.id]);

  useEffect(() => {
    api.listVerticals().then((v) => setVerticals(v.verticals)).catch(() => setVerticals([]));
  }, []);

  const activeRound = assessments.find((a) => a.status === 'active');
  // a use case in a GENERIC round has no AI scoring
  // (the backend 422s it); a NULL assessment_id is legacy → AI (allowed).
  const genericRoundIds = new Set(
    assessments.filter((a) => a.assessment_type === 'generic').map((a) => a.id),
  );
  const isGenericRoundUseCase = (uc: UseCase) =>
    uc.assessment_id != null && genericRoundIds.has(uc.assessment_id);
  // Templates are AI use-case templates: never offered when a generic round
  // is being created or is the active round (it would seed AI content).
  const templatesBlocked = newRoundType === 'generic' || activeRound?.assessment_type === 'generic';

  const handleCreateRound = async () => {
    if (!selectedCustomer || !newRoundName.trim() || !newRoundType) return;
    setRoundsBusy(true);
    setRoundError(null);
    try {
      const purpose = newRoundPurpose.trim();
      await api.createAssessment(selectedCustomer.name, newRoundName.trim(), {
        type: newRoundType,
        ...(purpose ? { purpose } : {}),
      });
      setNewRoundName('');
      setNewRoundType(null);
      setNewRoundPurpose('');
      await loadAssessments();
    } catch (err: any) {
      // F12: inline error in the rounds card (the view stays mounted).
      setRoundError(err?.message || 'Failed to create assessment round');
    } finally {
      setRoundsBusy(false);
    }
  };

  const handleArchiveRound = async (assessmentId: number) => {
    if (!selectedCustomer) return;
    setRoundsBusy(true);
    setRoundError(null);
    try {
      await api.archiveAssessment(selectedCustomer.name, assessmentId);
      await loadAssessments();
    } catch (err: any) {
      // F12: inline error in the rounds card (the view stays mounted).
      setRoundError(err?.message || 'Failed to archive assessment round');
    } finally {
      setRoundsBusy(false);
    }
  };

  useEffect(() => {
    // F5: the prop also tracks IN-PAGE selection (URL-synced) — when the
    // prop change is an echo of an in-page click, selectCustomer has
    // already loaded this customer: skip the redundant refetch.
    if (selectedCustomerName && selectedCustomer?.name === selectedCustomerName) return;
    // If a specific customer name is provided (from MyDashboard), load that customer's data
    if (selectedCustomerName) {
      loadCustomerAndDepartments(selectedCustomerName);
    } else {
      customerLoadSeq.current += 1;
      loadCustomers();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedCustomerName]);

  // FE-05: monotonically increasing identity for loadCustomerAndDepartments
  // requests — guards against a late response from a superseded customer.
  const customerLoadSeq = useRef(0);

  const loadCustomerAndDepartments = async (customerName: string) => {
    // FE-05: request-identity guard — a response only commits if the
    // requested customer is STILL the selected one. A late response for a
    // previous customer must not clobber the new customer's content (or
    // error state) while it is loading.
    const seq = ++customerLoadSeq.current;
    setLoading(true);
    setError(null);
    try {
      const [customerData, useCasesData, deptData] = await Promise.all([
        api.getCustomer(customerName),
        api.getCustomerUseCases(customerName),
        api.listDepartments(customerName),
      ]);
      if (seq !== customerLoadSeq.current) return;
      setCustomerUseCases(useCasesData);
      setDepartmentObjects(deptData.map((d: any) => ({
        id: d.id,
        name: d.name,
        use_case_count: d.use_case_count || 0,
      })));
      setSelectedCustomer({
        id: customerData.id,
        name: customerData.name,
        description: customerData.description || '',
        vertical: customerData.vertical ?? null,
        branch: customerData.branch ?? null,
        primary_rep: customerData.primary_rep ?? null,
        manager_name: customerData.manager_name ?? null,
        inside_sales: customerData.inside_sales ?? [],
        sales_ops: customerData.sales_ops ?? [],
        created_at: customerData.created_at,
        updated_at: customerData.updated_at,
        use_case_count: customerData.use_case_count,
        departments: customerData.departments || [],
        total_impact: customerData.total_impact || 0,
      });
    } catch (err) {
      if (seq !== customerLoadSeq.current) return; // superseded — a later load owns the state
      setError(err instanceof Error ? err.message : 'Failed to load customer');
      setSelectedCustomer(null);
      setCustomerUseCases([]);
      setDepartmentObjects([]);
    } finally {
      if (seq === customerLoadSeq.current) setLoading(false);
    }
  };

  useEffect(() => {
    if (isNewCustomer && (getAuthIsAdmin() || getAuthSalesRole() === 'sales_manager')) {
      // F19: only admins (customers) and sales managers (admin-reviewed
      // prospects) may create accounts; no other identity sees the form.
      setShowNewCustomerForm(true);
    }
  }, [isNewCustomer]);

  // Auto-select customer when coming from MyDashboard with a customer name
  useEffect(() => {
    if (selectedCustomerName && customers.length > 0 && !selectedCustomer) {
      const customer = customers.find(c => c.name === selectedCustomerName);
      if (customer) {
        selectCustomer(customer);
      }
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps -- pre-existing dependency list; change only with UI verification
  }, [selectedCustomerName, customers, selectedCustomer]);

  // Reset the new-assessment starter to the template grid when the selected customer changes
  useEffect(() => {
    setNewAssessmentMode('template');
  }, [selectedCustomer]);

  useEffect(() => {
    const seq = ++accessCheckSeq.current;
    if (selectedCustomer?.name) {
      // Fail-closed while the role resolves: a stale 'owner' left over from a
      // previously selected customer must not briefly expose the Edit/Remove
      // surfaces (the backend enforces 403 either way).
      setUserRole('member');
      setAccessCustomer(selectedCustomer.name);
      setUserAccess(false);
      setUserAccessError(false);
      setUserLoading(true);
      api.checkAccess(selectedCustomer.name)
        .then(res => {
          if (seq !== accessCheckSeq.current) return;
          if (res.has_access === true) {
            setUserAccess(true);
            setUserRole(res.permission_level || 'member');
          } else if (res.has_access === false) {
            setUserAccess(false);
          } else {
            setUserAccessError(true);
          }
        })
        .catch(() => {
          if (seq !== accessCheckSeq.current) return;
          setUserAccess(false);
          setUserAccessError(true);
        })
        .finally(() => {
          if (seq === accessCheckSeq.current) setUserLoading(false);
        });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- pre-existing dependency list; change only with UI verification
    return () => { ++accessCheckSeq.current; };
  }, [selectedCustomer?.name, accessRetry]);

  // Resolve the record through the selected customer's authorized list. A
  // foreign or removed ID gets the same unavailable state; stale responses
  // cannot replace a later customer or route.
  useEffect(() => {
    let active = true;
    setSelectedUseCase(null);
    setDetailError(null);
    if (area !== 'detail') { setDetailLoading(false); return () => { active = false; }; }
    if (!detailId) { setDetailLoading(false); setDetailError('Use case not found or unavailable.'); return () => { active = false; }; }
    if (!selectedCustomer || (selectedCustomerName && selectedCustomer.name !== selectedCustomerName)
      || userLoading || accessCustomer !== selectedCustomer.name || !userAccess) {
      setDetailLoading(true);
      return () => { active = false; };
    }
    const customer = selectedCustomer;
    setDetailLoading(true);
    api.getCustomerUseCases(customer.name).then((items) => {
      if (!active) return;
      const found = items.find((item) => item.id === detailId && item.customer_id === customer.id);
      if (found) setSelectedUseCase(found);
      else setDetailError('Use case not found or unavailable.');
    }).catch(() => { if (active) setDetailError('Use case not found or unavailable.'); })
      .finally(() => { if (active) setDetailLoading(false); });
    return () => { active = false; };
  // eslint-disable-next-line react-hooks/exhaustive-deps -- pre-existing dependency list; change only with UI verification
  }, [area, detailId, selectedCustomer?.id, selectedCustomer?.name, selectedCustomerName, userLoading, userAccess, accessCustomer]);

  // F4(d): a WS scoring event for this customer → refresh the use
  // case scores (single list refetch) so a background score completion
  // lands in the table + the open detail without a manual reload; clear
  // the busy state if the score fetch is in flight. The event is a
  // notification row (type + customer_id) — matched on customer_id.
  const scoreLoadingRef = useRef(false);
  useEffect(() => { scoreLoadingRef.current = scoreLoading; }, [scoreLoading]);
  const selectedUseCaseRef = useRef<UseCase | null>(null);
  useEffect(() => { selectedUseCaseRef.current = selectedUseCase; }, [selectedUseCase]);

  useEffect(() => {
    if (!selectedCustomer) return;
    const cust = selectedCustomer;
    const unsubscribe = ws.subscribe('*', (message: { type: string; data: unknown; timestamp: string }) => {
      if (message.type !== 'scoring') return;
      const dataObj = message.data as { customer_id?: number } | undefined;
      if (dataObj?.customer_id != null && dataObj.customer_id !== cust.id) return;
      if (scoreLoadingRef.current) setScoreLoading(false);
      api.getCustomerUseCases(cust.name).then((useCases) => {
        setCustomerUseCases(useCases);
        if (selectedUseCaseRef.current) {
          const refreshed = useCases.find((u) => u.id === selectedUseCaseRef.current?.id);
          if (refreshed) setSelectedUseCase(refreshed);
        }
      }).catch(() => { /* advisory refresh — keep the last known state */ });
    });
    return unsubscribe;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedCustomer?.id]);

  const handleCreateCustomer = async () => {
    if (!newCustomerName.trim()) return;
    setCreating(true);
    try {
      const created = await api.createCustomer({ name: newCustomerName.trim(), description: newCustomerDesc.trim() || undefined, vertical: newCustomerVertical || undefined });
      setNewCustomerName('');
      setNewCustomerDesc('');
      setNewCustomerVertical('');
      setShowNewCustomerForm(false);
      await loadCustomers();
      // Land on the new customer instead of leaving the user hunting for it
      // in a 900+ row, paginated list. The list is now newest-first, but
      // selecting it directly is the reliable post-create surface.
      if (created && created.id != null) {
        void selectCustomer(created);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to create customer');
    } finally {
      setCreating(false);
    }
  };

  const loadCustomers = async () => {
    try {
      setLoading(true);
      const data = await api.listCustomers();
      setCustomers(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load customers');
    } finally {
      setLoading(false);
    }
  };

  const selectCustomer = async (customer: Customer) => {
    const seq = ++customerLoadSeq.current;
    setCustomerUseCases([]);
    setDepartmentObjects([]);
    setSelectedCustomer(customer);
    setSelectedUseCase(null);
    // F5: sync the in-page selection up (→ Home state → ?customer= URL).
    onCustomerSelect?.(customer.name);
    try {
      const [useCases, deptData] = await Promise.all([
        api.getCustomerUseCases(customer.name),
        api.listDepartments(customer.name),
      ]);
      if (seq !== customerLoadSeq.current) return;
      setCustomerUseCases(useCases);
      setDepartmentObjects(deptData.map((d: any) => ({
        id: d.id,
        name: d.name,
        use_case_count: d.use_case_count || 0,
      })));
    } catch {
      if (seq === customerLoadSeq.current) setCustomerUseCases([]);
    }
  };

  const selectUseCase = (useCase: UseCase) => {
    openCustomerDetail(useCase.id);
  };

  const startNewAssessment = () => {
    setNewAssessmentOpen(true);
    setArea('assessments');
    // We'll create a new assessment form inside the assessments tab
  };

  const saveCustomer = async () => {
    if (!selectedCustomer) return;
    setMutationBusy(true); setMutationError(null); setMutationStatus(null);
    try {
      const updated = await api.updateCustomer(selectedCustomer.name, { description: editDescription, vertical: editVertical });
      setSelectedCustomer({ ...selectedCustomer, description: updated.description || '', vertical: updated.vertical });
      // the edit form is a settings-menu overlay — close it on
      // successful save (the header metadata updates in place).
      setSettingsDialog(null);
      setMutationStatus('Customer saved.');
    } catch (err) {
      setMutationError(err instanceof Error ? err.message : 'Failed to update customer');
    } finally { setMutationBusy(false); }
  };

  const removeCustomer = async () => {
    if (!selectedCustomer) return;
    // the removal overlay IS the confirmation
    // surface — no second window.confirm on top of it.
    setMutationBusy(true); setMutationError(null);
    try {
      await api.deleteCustomer(selectedCustomer.name);
      setSettingsDialog(null);
      setSelectedCustomer(null); setCustomerUseCases([]); setDepartmentObjects([]);
      // F5: clear the URL-synced selection (the customer no longer exists).
      onCustomerSelect?.(null);
      // Refresh the left-panel customer list so the removed customer does not
      // linger as a stale row when the Remove sub-view was reached from the
      // in-page list (selectedCustomerName is already null there, so the
      // [selectedCustomerName] reload effect would not fire).
      loadCustomers();
      onNavigate('customers');
    } catch (err) {
      setMutationError(err instanceof Error ? err.message : 'Failed to remove customer');
      setMutationBusy(false);
    }
  };

  // after a use-case add/delete, refresh the list AND the customer
  // aggregate so the "Total Use Cases" KPI (selectedCustomer.use_case_count)
  // and the department counts stay live instead of stale.
  const refreshCustomerData = async () => {
    if (!selectedCustomer) return;
    const [useCasesData, customerData] = await Promise.all([
      api.getCustomerUseCases(selectedCustomer.name),
      api.getCustomer(selectedCustomer.name),
    ]);
    setCustomerUseCases(useCasesData);
    setSelectedCustomer({
      id: customerData.id,
      name: customerData.name,
      description: customerData.description || '',
      vertical: customerData.vertical ?? null,
      branch: customerData.branch ?? null,
      primary_rep: customerData.primary_rep ?? null,
      manager_name: customerData.manager_name ?? null,
      inside_sales: customerData.inside_sales ?? [],
      sales_ops: customerData.sales_ops ?? [],
      created_at: customerData.created_at,
      updated_at: customerData.updated_at,
      use_case_count: customerData.use_case_count,
      departments: customerData.departments || [],
      total_impact: customerData.total_impact || 0,
    });
  };

  // direct single-use-case add (bypasses the assessment/template
  // flow on purpose: a use case is a first-class record with its own CRUD).
  const handleCreateUseCase = async () => {
    if (!selectedCustomer || !newUcTitle.trim() || ucBusy) return;
    setUcBusy(true);
    setUcError(null);
    setUcStatus(null);
    try {
      const deptObj = departmentObjects.find((d) => d.name === newUcDept);
      await api.create({
        title: newUcTitle.trim(),
        description: newUcDesc.trim() || undefined,
        department_id: deptObj?.id,
        department: newUcDept || undefined,
        status: newUcStatus,
        customer_id: selectedCustomer.id,
      });
      setShowNewUcForm(false);
      setNewUcTitle('');
      setNewUcDesc('');
      setNewUcDept('');
      setNewUcStatus('draft');
      await refreshCustomerData();
      setUcStatus('Use case created.');
    } catch (err) {
      setUcError(err instanceof Error ? err.message : 'Failed to create use case');
    } finally {
      setUcBusy(false);
    }
  };

  // delete with a consequence-stating confirm (the backend cascades
  // the use case's comments, score history, and AI predictions).
  const handleDeleteUseCase = async (useCase: UseCase) => {
    if (ucBusy) return;
    if (!window.confirm(
      `Permanently delete use case "${useCase.title}"? Its comments, scores, and predictions are removed too.`
    )) return;
    setUcBusy(true);
    setUcError(null);
    setUcStatus(null);
    try {
      await api.deleteUseCase(useCase.id);
      // If the deleted use case was open in the detail tab, fall back to
      // Overview (the detail view renders on selectedUseCase).
      if (selectedUseCase?.id === useCase.id) {
        setSelectedUseCase(null);
        setArea('overview');
      }
      await refreshCustomerData();
      setUcStatus('Use case deleted.');
    } catch (err) {
      setUcError(err instanceof Error ? err.message : 'Failed to delete use case');
    } finally {
      setUcBusy(false);
    }
  };

  const handleScore = async (useCaseId: number) => {
    if (!canAddUseCase || scoreLoading) return;
    setScoreLoading(true);
    // F4(c): 300s cap on the scoring fetch (client-side — the model
    // may keep running on the server; the abort message says so). The busy
    // surface is the shared detail's disabled buttons + "Scoring…" labels
    // (busy prop) — the guard above is the re-entry prevention.
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 300_000);
    try {
      await api.score(useCaseId, controller.signal);
      // Refresh use cases
      if (selectedCustomer) {
        const useCases = await api.getCustomerUseCases(selectedCustomer.name);
        setCustomerUseCases(useCases);
      }
      // Refresh selected use case data
      const refreshed = await api.get(useCaseId);
      if (refreshed) {
        setSelectedUseCase(refreshed);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Scoring failed');
    } finally {
      clearTimeout(timer);
      setScoreLoading(false);
    }
  };

  const getScoreColor = (score?: number) => {
    if (!score) return 'var(--neutral-400)';
    if (score >= 70) return 'var(--status-positive)';
    if (score >= 35) return 'var(--status-warning)';
    return 'var(--status-negative)';
  };

  // F12: retry the same load that failed (the mount-time refetch) — no
  // page reload; the view state (selection, tab, round input) survives.
  const retryLoad = () => {
    setError(null);
    if (selectedCustomerName) {
      loadCustomerAndDepartments(selectedCustomerName);
    } else if (selectedCustomer) {
      loadCustomerAndDepartments(selectedCustomer.name);
    } else {
      loadCustomers();
    }
  };

  // ── — two-level customer workspace navigation (1-5, 50-53) ──
  // Primary areas: Overview | Sales | Intelligence | Discovery & Value |
  // Team. Secondary rails — the existing
  // functionality is MOVED underneath these areas, not duplicated.
  // `edit` / `remove` (account management) render inside
  // the Overview area before moving into the header settings menu.
  const PRIMARY_AREAS = [
    { id: 'overview', label: 'Overview' },
    { id: 'sales', label: 'Sales' },
    { id: 'intelligence', label: 'Intelligence' },
    { id: 'assessments', label: 'Discovery & Value' },
    { id: 'team', label: 'Team' },
  ] as const;

  const SECONDARY_OF: Record<string, { id: string; label: string }[]> = {
    // customer intelligence sources and structured observations
    intelligence: [
      { id: 'intelligence-summary', label: 'Summary' },
      { id: 'technology-inventory', label: 'Technology' },
      { id: 'customer-knowledge', label: 'Knowledge' },
      { id: 'sales-notes', label: 'Sales Notes' },
      { id: 'contacts', label: 'Contacts' },
      { id: 'activities', label: 'Activities' },
      { id: 'tasks', label: 'Tasks' },
      { id: 'account-brief', label: 'Brief' },
      { id: 'account-timeline', label: 'Timeline' },
      { id: 'third-party-services', label: 'Third-Party Services' },
    ],
    // Rounds | Use Cases | Analytics | Business Impact |
    // Forecasting — plus Bulk Score and Export
    // (the report's export path).
    assessments: [
      { id: 'assessments', label: 'Summary' },
      { id: 'use-cases', label: 'Use Cases' },
      { id: 'bulk-score', label: 'Bulk Score' },
      { id: 'analytics', label: 'Analytics' },
      { id: 'business-impact', label: 'Business Impact' },
      { id: 'business-impact-forecasting', label: 'Forecasting' },
      { id: 'export', label: 'Export' },
    ],
    // Opportunities | Evaluations | Account Strategy
    sales: [
      { id: 'sales-deals', label: 'Deals' },
      { id: 'sales-opportunities', label: 'Attention' },
      { id: 'sales-pipeline', label: 'Partner Pipeline' },
      { id: 'sales-vendor-intelligence', label: 'Vendor Intelligence' },
      { id: 'sales-evaluations', label: 'Evaluations' },
      { id: 'account-strategy', label: 'Account Strategy' },
    ],
    // account-management destinations (Team stays a primary
    // area; Departments is the admin surface for the account).
    team: [
      { id: 'team', label: 'Team' },
      { id: 'departments', label: 'Departments' },
    ],
  };

  const PRIMARY_OF: Record<string, string> = {
    overview: 'overview',
    'intelligence-summary': 'intelligence',
    'technology-inventory': 'intelligence',
    'customer-knowledge': 'intelligence',
    'sales-notes': 'intelligence',
    contacts: 'intelligence',
    activities: 'intelligence',
    tasks: 'intelligence',
    'account-brief': 'intelligence',
    'account-timeline': 'intelligence',
    'third-party-services': 'intelligence',
    assessments: 'assessments',
    'bulk-score': 'assessments',
    'use-cases': 'assessments',
    analytics: 'assessments',
    'business-impact': 'assessments',
    'business-impact-forecasting': 'assessments',
    export: 'assessments',
    'sales-deals': 'sales',
    'sales-opportunities': 'sales',
    'sales-pipeline': 'sales',
    'sales-vendor-intelligence': 'sales',
    'sales-evaluations': 'sales',
    'account-strategy': 'sales',
    team: 'team',
    departments: 'team',
    // The detail view is a transient secondary of the current area.
    detail: 'assessments',
  };

  const primaryActive = PRIMARY_OF[area] || 'overview';
  // The rail lookup is keyed by the PRIMARY area (area holds the secondary
  // id, e.g. 'intelligence-summary').
  const secondary = SECONDARY_OF[primaryActive] || [];
  // The use-case detail is a transient secondary of the Discovery & Value area:
  // its rail item appears only while a use case is open.
  const secondaryItems: { id: string; label: string }[] = [
    ...secondary,
    ...(area === 'detail' && selectedUseCase
      ? [{ id: 'detail', label: selectedUseCase.title }]
      : []),
  ];

  const { state: nav, update: updateNav, reset: resetNav } = usePortfolioNavState(SIDE_LIST_NAV_DEFAULTS);
  const sideRows: SideListRow[] = useMemo(() => customers.map((c): SideListRow => ({
    id: c.id,
    name: c.name,
    description: c.description ?? null,
    vertical: c.vertical ?? null,
    branch: c.branch ?? null,
    salesArea: c.sales_area ?? null,
    primarySubsidiary: c.primary_subsidiary ?? null,
    primaryRep: c.primary_rep ?? null,
    managerName: c.manager_name ?? null,
    aliases: c.aliases ?? [],
    knownMetadata: true,
    source: c,
  })), [customers]);
  // Search/filter/sort span the FULL authorized list; the pager only slices.
  const shownSideRows = useMemo(() => sortRows(filterRows(sideRows, nav), nav), [sideRows, nav]);
  const pager = paginateNav(shownSideRows, nav, updateNav);

  if (loading) return <div role="status" aria-live="polite" style={{ padding: '40px', textAlign: 'center', color: 'var(--neutral-500)' }}>Loading...</div>;

  return (
    <div style={{ display: 'flex', minHeight: '100vh', background: 'var(--neutral-0)' }}>
      {/* Left Panel - Customer List (only shown in multi-customer mode) */}
      {!selectedCustomerName && (
        <div style={{ width: '340px', background: 'var(--neutral-0)', borderRight: '1px solid var(--divider)', overflow: 'auto', display: 'flex', flexDirection: 'column' }}>
          <div style={{ padding: '20px', borderBottom: '1px solid var(--divider)' }}>
            <h2 style={{ margin: '0 0 12px 0', fontSize: '1.2rem', color: 'var(--ink)' }}>My Customers</h2>
            {customers.length > 0 && (
              <>
                <PortfolioFilterBar rows={sideRows} state={nav} onChange={updateNav} onReset={resetNav} filteredCount={shownSideRows.length} sortKeys={SIDE_LIST_SORT_KEYS} defaults={SIDE_LIST_NAV_DEFAULTS} alwaysShowCount />
                <CustomerListPager {...pager.pagerProps} />
              </>
            )}
          </div>

          {/* New Customer Form */}
          {showNewCustomerForm && (
            <div style={{ padding: '16px', borderBottom: '1px solid var(--divider)', background: 'var(--neutral-0)' }}>
              <h4 style={{ margin: '0 0 12px 0', fontSize: '0.95rem', color: 'var(--ink)', fontWeight: 600 }}>{creatingProspect ? 'New Prospect' : 'New Customer'}</h4>
              {creatingProspect && (
                <p data-testid="prospect-review-note" style={{ margin: '0 0 10px', fontSize: '0.8rem', color: 'var(--neutral-600)' }}>
                  You will own this prospect provisionally. An administrator reviews new prospects and confirms or reassigns the owner.
                </p>
              )}
              <input aria-label="Enter customer name"
                type="text"
                placeholder="Customer name"
                value={newCustomerName}
                onChange={e => setNewCustomerName(e.target.value)}
                style={{ width: '100%', padding: '8px 10px', marginBottom: '8px', border: '1px solid var(--divider)', borderRadius: 'var(--radius)', fontSize: '0.9rem', boxSizing: 'border-box' }}
                autoFocus
              />
              <input aria-label="Description (optional)"
                type="text"
                placeholder="Description (optional)"
                value={newCustomerDesc}
                onChange={e => setNewCustomerDesc(e.target.value)}
                style={{ width: '100%', padding: '8px 10px', marginBottom: '8px', border: '1px solid var(--divider)', borderRadius: 'var(--radius)', fontSize: '0.9rem', boxSizing: 'border-box' }}
              />
              <select
                aria-label="New customer vertical"
                value={newCustomerVertical}
                onChange={e => setNewCustomerVertical(e.target.value)}
                style={{ width: '100%', padding: '8px 10px', marginBottom: '12px', border: '1px solid var(--divider)', borderRadius: 'var(--radius)', fontSize: '0.9rem', boxSizing: 'border-box', background: 'var(--neutral-0)' }}
              >
                <option value="">Select vertical… (optional)</option>
                {verticals.map(v => <option key={v} value={v}>{v}</option>)}
              </select>
              {newCustomerVertical === 'Other' && (
                <p style={{ margin: '-4px 0 12px', color: 'var(--neutral-500)', fontSize: '0.8rem' }}>
                  Describe the customer's industry in the description.
                </p>
              )}
              <div style={{ display: 'flex', gap: '8px' }}>
                <button role="button" aria-label="Create customer"
                  onClick={handleCreateCustomer}
                  disabled={creating || !newCustomerName.trim()}
                  style={{ flex: 1, padding: '8px', background: newCustomerName.trim() && !creating ? 'var(--brand-500)' : 'var(--neutral-400)', color: 'var(--neutral-0)', border: 'none', borderRadius: 'var(--radius)', cursor: newCustomerName.trim() && !creating ? 'pointer' : 'not-allowed', fontSize: '0.85rem', fontWeight: 600 }}
                >
                  {creating ? 'Creating...' : 'Create'}
                </button>
                <button role="button" aria-label="Cancel creating customer"
                  onClick={() => setShowNewCustomerForm(false)}
                  style={{ padding: '8px 12px', background: 'var(--neutral-100)', color: 'var(--neutral-500)', border: '1px solid var(--divider)', borderRadius: 'var(--radius)', cursor: 'pointer', fontSize: '0.85rem' }}
                >
                  Cancel
                </button>
              </div>
            </div>
          )}

          <div style={{ padding: '12px', flex: 1, overflowY: 'auto' }}>
            {customers.length === 0 ? (
              <p style={{ margin: '0', color: 'var(--neutral-500)', fontSize: '0.9rem', textAlign: 'center', padding: '20px 0' }}>No customers yet</p>
            ) : shownSideRows.length === 0 ? (
              <div data-testid="no-matches" style={{ textAlign: 'center', padding: '20px 0' }}>
                <p style={{ margin: '0 0 8px', color: 'var(--neutral-500)', fontSize: '0.9rem' }}>{activeFilterSummary(nav)}</p>
                {isFiltered(nav, SIDE_LIST_NAV_DEFAULTS) && (
                  <button type="button" aria-label="Reset filters" onClick={resetNav} style={{ padding: '6px 12px', background: 'var(--neutral-100)', color: 'var(--neutral-700)', border: '1px solid var(--divider)', borderRadius: 'var(--radius)', cursor: 'pointer', fontSize: '0.85rem' }}>Reset filters</button>
                )}
              </div>
            ) : (
              pager.visible.map(row => row.source).map(customer => (
                <div
                  key={customer.id}
                  role="button"
                  tabIndex={0}
                  aria-label={`Select customer ${customer.name}`}
                  onClick={() => selectCustomer(customer)}
                  onKeyDown={(event) => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); selectCustomer(customer); } }}
                  style={{
                    padding: '12px',
                    marginBottom: '8px',
                    background: selectedCustomer?.id === customer.id ? 'var(--brand-100)' : 'transparent',
                    border: selectedCustomer?.id === customer.id ? '1px solid var(--brand-500)' : '1px solid transparent',
                    borderRadius: 'var(--radius)',
                    cursor: 'pointer',
                    transition: 'all 0.2s',
                  }}
                >
                  <div style={{ fontWeight: 600, color: 'var(--ink)', marginBottom: '4px' }}>{customer.name}</div>
                  {customer.description && (
                    <div style={{ fontSize: '0.8rem', color: 'var(--neutral-500)', marginBottom: '4px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                      {customer.description}
                    </div>
                  )}
                  <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.8rem', color: 'var(--neutral-500)' }}>
                    <span>{customer.use_case_count} use cases</span>
                    <span>{customer.departments.length} departments</span>
                  </div>
                  {((customer as any).total_impact ?? 0) > 0 && (
                    <div style={{ fontSize: '0.75rem', color: 'var(--status-positive)', marginTop: '4px' }}>
                      Impact: ${((customer as any).total_impact ?? 0).toLocaleString()}
                    </div>
                  )}
                </div>
              ))
            )}
          </div>
        </div>
      )}

      {/* Right Panel - Customer Detail (or single-customer full-width view) */}
      <div style={{ flex: 1, minWidth: 0, overflow: 'auto' }}>
        {/* F12: a transient load failure is an inline banner with a Retry
            that re-runs the same load — the view (selection, tab, round
            input) is no longer unmounted for a full page reload. */}
        {error && (
          <div role="alert" aria-live="assertive" style={{ padding: '12px 24px', background: 'var(--status-negative-soft)', borderLeft: '4px solid var(--status-negative)', display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: '12px' }}>
            <span style={{ color: 'var(--status-negative)', fontSize: '0.9rem', fontWeight: 500 }}><span aria-hidden="true">⚠️ </span>{error}</span>
            <button role="button" aria-label="Retry loading customer dashboard"
              onClick={retryLoad}
              style={{ padding: '6px 12px', border: '1px solid var(--status-negative)', borderRadius: 'var(--radius-sm)', background: 'var(--neutral-0)', color: 'var(--status-negative)', cursor: 'pointer', fontWeight: 600, whiteSpace: 'nowrap' }}
            >
              Retry
            </button>
          </div>
        )}
        {!selectedCustomer ? (
          <div style={{ padding: '40px', textAlign: 'center', color: 'var(--neutral-500)' }}>
            <h2 style={{ margin: '0 0 12px 0', color: 'var(--neutral-700)' }}>Select a Customer</h2>
            <p>Choose a customer from the left panel to view their assessments and analytics.</p>
          </div>
        ) : userLoading || accessCustomer !== selectedCustomer.name ? (
          <div style={{ padding: '40px', textAlign: 'center' }}>Checking access...</div>
        ) : userAccessError ? (
          <div role="alert" style={{ padding: '40px', textAlign: 'center', color: 'var(--status-negative)' }}>
            <h2 style={{ margin: '0 0 12px 0', color: 'var(--status-negative)' }}>Access Check Failed</h2>
            <p>The access check could not be completed.</p>
            <button onClick={() => setAccessRetry(count => count + 1)}>Retry</button>
          </div>
        ) : !userAccess ? (
          <div style={{ padding: '40px', textAlign: 'center', color: 'var(--status-negative)' }}>
            <h2 style={{ margin: '0 0 12px 0', color: 'var(--status-negative)' }}>No Access</h2>
            <p>You do not have access to view this customer's data.</p>
          </div>
        ) : (
          <div className="crm-workspace" style={{ padding: '24px', minWidth: 0 }}>
            {/* Breadcrumbs: replace the
                "Back to Dashboard" + "My Customers" button pair with a
                standard Dashboard / Customers / {customer} path. */}
            <Breadcrumbs
              onHome={() => onNavigate('dashboard')}
              crumbs={[
                { label: 'Customers', onCrumbClick: () => onNavigate('customers') },
                { label: selectedCustomer.name },
              ]}
            />

            {/* Compact persistent customer header: name/description/ownership/departments/
                metadata in one unified surface; the full-width active-
                assessment banner is now a compact status element inside
                the header; Edit/Remove live in the overflow settings
                menu, and a single "+ Add" control exposes create actions. */}
            <CustomerHeader
              name={selectedCustomer.name}
              description={selectedCustomer.description || undefined}
              vertical={selectedCustomer.vertical}
              branch={selectedCustomer.branch}
              primaryRep={selectedCustomer.primary_rep}
              managerName={selectedCustomer.manager_name}
              insideSales={(selectedCustomer.inside_sales ?? []).map((rep) => rep.name)}
              salesOps={(selectedCustomer.sales_ops ?? []).map((rep) => rep.name)}
              userRole={userRole}
              canManageCustomer={canManageCustomer}
              canManageAliases={canManageAliases}
              canAddUseCase={canAddUseCase}
              createPermissions={workspaceActions?.capabilities}
              activeRound={primaryActive === 'assessments' && activeRound ? {
                generic: activeRound.assessment_type === 'generic',
                completed: customerUseCases.filter(u => u.assessment_id === activeRound.id && u.status === 'completed').length,
                name: activeRound.name,
                total: activeRound.use_case_count ?? 0,
                scored: customerUseCases.filter(
                  (u) => u.assessment_id == activeRound.id && u.overall_score != null
                ).length,
              } : null}
              onManageRounds={() => setArea('assessments')}
              onAdd={(target) => {
                const destinations: Record<string, string> = { contact: 'contacts', activity: 'activities', task: 'tasks', deal: 'sales-deals' };
                if (destinations[target] && workspaceActions?.capabilities[target]) {
                  setQuickCreate(previous => ({ customer: selectedCustomer.id, target, request: (previous?.request ?? 0) + 1 }));
                  setArea(destinations[target]);
                } else if (target === 'use-case') {
                  setUcError(null);
                  setUcStatus(null);
                  setShowNewUcForm(true);
                } else if (target === 'technology') {
                  setArea('technology-inventory');
                } else if (target === 'sales-note') {
                  setArea('sales-notes');
                } else if (target === 'knowledge') {
                  setArea('customer-knowledge');
                } else if (target === 'assessment') {
                  startNewAssessment();
                }
              }}
              onOpenSettings={(target) => {
                // all account-management
                // destinations (Edit Customer / Departments / Remove) are
                // transient surfaces opened from this menu — never primary
                // navigation areas. 'team' stays a real area (rail default).
                if (target === 'edit' || target === 'remove') {
                  setSettingsDialog(target);
                } else {
                  setArea(target);
                }
              }}
            />

            {actionsError && <p role="status">Create actions unavailable. <button type="button" onClick={retryActions}>Retry actions</button></p>}

            {/* in-account cross-module search (the account workspace's
                one search box; results deep-link to the owning rail area). */}
            <AccountSearchPanel key={selectedCustomer.id}
              customerId={selectedCustomer.id}
              onSelect={(module, id) => {
                customerRecord.select(module, id);
              }}
            />

            {/* Admin-only per-customer sales-team correction surface. */}
            {getAuthIsAdmin() && (
              <details className="crm-disclosure"><summary>Sales team administration</summary>
              <CustomerSalesTeam
                customerName={selectedCustomer.name}
                onSaved={refreshCustomerData}
              /></details>
            )}

            {/* Two-level customer workspace navigation: the ~5 primary areas plus the
                per-area secondary rail. The use-case detail is a
                transient secondary of the Discovery & Value area (it is only
                reached from the Use Cases table). */}
            <SegmentedNav
              panelId={workspacePanelId}
              variant="primary"
              ariaLabel="Customer areas"
              items={PRIMARY_AREAS.map((a) => ({ id: a.id, label: a.label }))}
              activeId={primaryActive}
              onChange={(id) => setArea(SECONDARY_OF[id]?.[0]?.id || id)}
            />
            {secondaryItems.length > 0 && (
              <SegmentedNav
                panelId={workspacePanelId}
                variant="secondary"
                ariaLabel={`${primaryActive} sections`}
                items={secondaryItems}
                activeId={area}
                onChange={(id) => setArea(id)}
              />
            )}

            <section id={workspacePanelId} role="tabpanel" aria-label={`${PRIMARY_AREAS.find(item => item.id === primaryActive)?.label || primaryActive} content`} tabIndex={0}>
            {customerRecord.record && <SelectedCustomerRecord onChanged={() => setRecordRefresh(value => value + 1)} customerName={selectedCustomer.name} onOpenRecord={customerRecord.select} key={`${customerRecord.record.customerId}-${customerRecord.record.module}-${customerRecord.record.id}-${recordRefresh}`} onEditDeal={id => setQuickCreate(previous => ({ customer: selectedCustomer.id, target: 'deal-edit', request: (previous?.request ?? 0) + 1, id }))} selection={customerRecord.record} onClose={customerRecord.clear} />}

            {/* Area content */}
            {area === 'overview' && (
              <div>
                {/* executive account view: balanced headline
                    metrics, the Account Snapshot, the four actionable
                    intelligence summaries, and the small Priority Use
                    Cases list. Deterministic
                    fed by the account-workspace endpoint; provenance via
                    tooltip, not a "Derived" label. The dense
                    use-case working table stays one rail step away. */}
                <AccountOverview
                  customerId={selectedCustomer.id}
                  userRole={userRole}
                  onNavigate={(target) => {
                    if (target.startsWith('deal:')) customerRecord.select('deal', Number(target.slice(5)));
                    else if (target === 'tasks-overdue') setArea('tasks', { customerId: selectedCustomer.id, prefix: 'task', params: { view: 'overdue' } });
                    else if (target === 'renewals-due') setArea('sales-pipeline', { customerId: selectedCustomer.id, prefix: 'renewal', params: { bucket: 'due' } });
                    else if (target === 'buying-gaps') setArea('contacts', { customerId: selectedCustomer.id, prefix: 'contact', params: { coverage: 'gaps' } });
                    else setArea(target);
                  }}
                />

              </div>
            )}

            {area === 'intelligence-summary' && (
              <div>
                {/* Intelligence ▸ Summary: the actionable
                    customer-intelligence summaries on their own. F4: the
                    Customer Intelligence Constellation (deterministic
                    graph projection of this customer's technologies, use
                    cases, notes, assessments + opportunities, with
                    dependency relationships) is the principal analytical
                    visualization of this section — it is NOT copied into
                    the Overview (which keeps only a lightweight teaser).
                    The dense use-case working view is one rail step over.
                    Departments (account management) is under the Team area. */}
                <CustomerIntelligenceConstellation
                  customerId={selectedCustomer.id}
                  customerName={selectedCustomer.name || ''}
                  onNavigate={(target) => {
                    if (target.startsWith('deal:')) customerRecord.select('deal', Number(target.slice(5)));
                    else if (target === 'tasks-overdue') setArea('tasks', { customerId: selectedCustomer.id, prefix: 'task', params: { view: 'overdue' } });
                    else if (target === 'renewals-due') setArea('sales-pipeline', { customerId: selectedCustomer.id, prefix: 'renewal', params: { bucket: 'due' } });
                    else if (target === 'buying-gaps') setArea('contacts', { customerId: selectedCustomer.id, prefix: 'contact', params: { coverage: 'gaps' } });
                    else setArea(target);
                  }}
                />
                <IntelligencePanels customerId={selectedCustomer.id} />
              </div>
            )}

            {area === 'use-cases' && (
              <div>
                {/* Use Cases working view (moved here from Overview —
                    the dense operational table lives in the working view
                    the user intentionally navigates to).
                    The Overview includes a small Priority Use Cases section. */}
                <div style={{ background: 'var(--neutral-0)', borderRadius: 'var(--radius)', boxShadow: 'var(--shadow-card)', overflow: 'hidden' }}>
                  <div style={{ padding: '16px 20px', borderBottom: '1px solid var(--divider)', display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: '12px', flexWrap: 'wrap' }}>
                    <h3 style={{ margin: 0, fontSize: '1rem', color: 'var(--neutral-700)' }}>Use Cases ({customerUseCases.length})</h3>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '12px', flexWrap: 'wrap' }}>
                      {ucStatus && <span role="status" aria-live="polite" style={{ fontSize: '0.85rem', color: 'var(--status-positive)' }}>{ucStatus}</span>}
                      {ucError && <span role="alert" aria-live="assertive" style={{ fontSize: '0.85rem', color: 'var(--status-negative)' }}>{ucError}</span>}
                      {/* UX audit #9: the disabled reason was only in `title`
                          (not announced to screen readers) — mirror it into
                          aria-label so SR users learn WHY the control is off. */}
                      <button role="button"
                        aria-label={!canAddUseCase ? 'Add use case — read-only access: adding use cases requires account edit permission' : 'Add use case'}
                        disabled={!canAddUseCase || ucBusy}
                        title={!canAddUseCase ? 'Read-only access: adding use cases requires account edit permission' : undefined}
                        onClick={() => { setUcError(null); setUcStatus(null); setShowNewUcForm((v) => !v); }}
                        style={{ padding: '6px 14px', background: canAddUseCase ? 'var(--brand-500)' : 'var(--neutral-100)', color: canAddUseCase ? 'var(--neutral-0)' : 'var(--neutral-500)', border: canAddUseCase ? 'none' : '1px solid var(--divider)', borderRadius: 'var(--radius)', cursor: canAddUseCase && !ucBusy ? 'pointer' : 'not-allowed', fontSize: '0.85rem', fontWeight: 600 }}
                      >
                        + Add Use Case
                      </button>
                    </div>
                  </div>
                  {showNewUcForm && canAddUseCase && (
                    <div style={{ padding: '16px 20px', borderBottom: '1px solid var(--divider)', background: 'var(--neutral-50)' }}>
                      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: '10px', marginBottom: '10px' }}>
                        <input aria-label="New use case title"
                          type="text" placeholder="Use case title"
                          value={newUcTitle}
                          onChange={(e) => setNewUcTitle(e.target.value)}
                          style={{ padding: '8px 10px', border: '1px solid var(--divider)', borderRadius: 'var(--radius)', fontSize: '0.9rem', boxSizing: 'border-box' }}
                          autoFocus
                        />
                        <input aria-label="New use case description"
                          type="text" placeholder="Description (optional)"
                          value={newUcDesc}
                          onChange={(e) => setNewUcDesc(e.target.value)}
                          style={{ padding: '8px 10px', border: '1px solid var(--divider)', borderRadius: 'var(--radius)', fontSize: '0.9rem', boxSizing: 'border-box' }}
                        />
                        <select aria-label="New use case department"
                          value={newUcDept}
                          onChange={(e) => setNewUcDept(e.target.value)}
                          style={{ padding: '8px 10px', border: '1px solid var(--divider)', borderRadius: 'var(--radius)', fontSize: '0.9rem', background: 'var(--neutral-0)' }}
                        >
                          <option value="">— No department —</option>
                          {departmentObjects.map((d) => <option key={d.id} value={d.name}>{d.name}</option>)}
                        </select>
                        <select aria-label="New use case status"
                          value={newUcStatus}
                          onChange={(e) => setNewUcStatus(e.target.value)}
                          style={{ padding: '8px 10px', border: '1px solid var(--divider)', borderRadius: 'var(--radius)', fontSize: '0.9rem', background: 'var(--neutral-0)' }}
                        >
                          <option value="draft">Draft</option>
                          <option value="active">Active</option>
                          <option value="completed">Completed</option>
                        </select>
                      </div>
                      <div style={{ display: 'flex', gap: '8px' }}>
                        <button role="button" aria-label="Create use case"
                          disabled={ucBusy || !newUcTitle.trim()}
                          onClick={handleCreateUseCase}
                          style={{ padding: '8px 16px', background: ucBusy || !newUcTitle.trim() ? 'var(--neutral-400)' : 'var(--brand-500)', color: 'var(--neutral-0)', border: 'none', borderRadius: 'var(--radius)', cursor: ucBusy || !newUcTitle.trim() ? 'not-allowed' : 'pointer', fontSize: '0.85rem', fontWeight: 600 }}
                        >
                          {ucBusy ? 'Saving…' : 'Create use case'}
                        </button>
                        <button role="button" aria-label="Cancel add use case"
                          onClick={() => { setShowNewUcForm(false); setNewUcTitle(''); setNewUcDesc(''); setNewUcDept(''); setNewUcStatus('draft'); }}
                          style={{ padding: '8px 16px', background: 'var(--neutral-0)', color: 'var(--neutral-500)', border: '1px solid var(--neutral-400)', borderRadius: 'var(--radius)', cursor: 'pointer', fontSize: '0.85rem' }}
                        >
                          Cancel
                        </button>
                      </div>
                    </div>
                  )}
                  {customerUseCases.length === 0 ? (
                    <div style={{ padding: '40px', textAlign: 'center', color: 'var(--neutral-500)' }}>
                      <p>No use cases for this customer yet.</p>
                      <p style={{ fontSize: '0.85rem', color: 'var(--neutral-500)' }}>Use "Add Use Case" above to create the first one.</p>
                    </div>
                  ) : (
                    <div style={{ overflowX: 'auto' }}>
                      <table style={{ width: '100%', borderCollapse: 'collapse' }}>
                        <thead>
                          <tr style={{ borderBottom: '2px solid var(--divider)' }}>
                            {[...['Title', 'Department', 'Status', 'Score', 'Savings', 'Revenue', 'Created'], ...(canDeleteUseCase ? ['Actions'] : [])].map(h => (
                              <th key={h} style={{ padding: '12px 16px', textAlign: 'left', fontSize: '0.85rem', fontWeight: 600, color: 'var(--neutral-500)' }}>{h}</th>
                            ))}
                          </tr>
                        </thead>
                        <tbody>
                          {customerUseCases.map(uc => (
                            <tr key={uc.id} role="button" tabIndex={0} aria-label={`Open assessment ${uc.title}`} style={{ borderBottom: '1px solid var(--neutral-100)', cursor: 'pointer' }} onClick={() => selectUseCase(uc)} onKeyDown={(event) => { if (event.target instanceof HTMLButtonElement) return; if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); selectUseCase(uc); } }}>
                              <td style={{ padding: '12px 16px', fontWeight: 500, color: 'var(--ink)' }}>{uc.title}</td>
                              <td style={{ padding: '12px 16px', color: 'var(--neutral-500)' }}>{uc.department || '-'}</td>
                              <td style={{ padding: '12px 16px' }}>
                                <span style={{
                                  padding: '4px 10px',
                                  borderRadius: 'var(--radius)',
                                  background: `${uc.status === 'active' ? 'var(--status-positive)' : uc.status === 'completed' ? 'var(--brand-500)' : 'var(--status-warning)'}20`,
                                  color: uc.status === 'active' ? 'var(--status-positive)' : uc.status === 'completed' ? 'var(--brand-700)' : 'var(--status-warning)',
                                  fontSize: '0.8rem',
                                  fontWeight: 600,
                                  textTransform: 'capitalize',
                                }}>{uc.status}</span>
                              </td>
                              <td style={{ padding: '12px 16px', fontWeight: 'bold', color: getScoreColor(uc.overall_score) }}>
                                {uc.overall_score != null ? uc.overall_score.toFixed(1) : '—'}
                              </td>
                              <td style={{ padding: '12px 16px', color: 'var(--status-positive)' }}>
                                {uc.estimated_savings ? `$${uc.estimated_savings.toLocaleString()}` : '—'}
                              </td>
                              <td style={{ padding: '12px 16px', color: 'var(--brand-700)' }}>
                                {uc.estimated_revenue ? `$${uc.estimated_revenue.toLocaleString()}` : '—'}
                              </td>
                              <td style={{ padding: '12px 16px', color: 'var(--neutral-500)', fontSize: '0.85rem' }}>
                                {new Date(uc.created_at).toLocaleDateString()}
                              </td>
                              {canDeleteUseCase && (
                                <td style={{ padding: '12px 16px', textAlign: 'right' }}>
                                  {/* per-row
                                      overflow menu instead of a repetitive
                                      Delete button — the destructive action
                                      keeps its confirmation flow. */}
                                  <RowActions
                                    ariaLabel={`Actions for use case ${uc.title}`}
                                    items={[{
                                      label: `Delete use case ${uc.title}`,
                                      onClick: () => handleDeleteUseCase(uc),
                                      destructive: true,
                                      disabled: ucBusy,
                                    }]}
                                  />
                                </td>
                              )}
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  )}
                </div>
              </div>
            )}

            {/* Account-management surface
                opened from the header settings menu (or the MyDashboard
                edit/remove deep links) as a transient overlay on top of the
                current area — no more edit/remove nav areas, no more
                confirmation-less direct remove. */}
            {((settingsDialog === 'edit' && (canManageCustomer || canManageAliases)) || (settingsDialog === 'remove' && canManageCustomer)) && createPortal(
              <div
                role="dialog"
                aria-modal="true"
                aria-label={settingsDialog === 'edit' ? 'Edit customer' : 'Remove customer'}
                style={{ position: 'fixed', inset: 0, zIndex: 40, background: 'rgba(15, 23, 42, 0.45)', display: 'flex', alignItems: 'center', justifyContent: 'center', padding: '24px' }}
              >
                {settingsDialog === 'edit' ? (
                  <div style={{ background: 'var(--neutral-0)', borderRadius: 'var(--radius)', padding: '24px', boxShadow: 'var(--shadow-card)', maxWidth: '720px', width: '100%', maxHeight: '90vh', overflowY: 'auto' }}>
                    <h2 style={{ margin: '0 0 20px', color: 'var(--ink)' }}>Edit customer</h2>
                    <div style={{ marginBottom: '18px' }}><div style={{ fontWeight: 600, color: 'var(--neutral-700)' }}>Name</div><div style={{ padding: '10px 0', color: 'var(--neutral-500)' }}>{selectedCustomer.name}</div><div style={{ fontSize: '0.82rem', color: 'var(--neutral-500)' }}>The name is fixed because use cases and projections reference it.</div></div>
                    {/* Description + vertical are customer metadata (owner/admin);
                        a sales admin opens this dialog for the Aliases only. */}
                    {canManageCustomer && (
                      <>
                        <label style={{ display: 'block', fontWeight: 600, color: 'var(--neutral-700)', marginBottom: '8px' }}>Description</label>
                        <textarea value={editDescription} onChange={(e) => setEditDescription(e.target.value)} rows={6} style={{ width: '100%', boxSizing: 'border-box', padding: '12px', border: '1px solid var(--neutral-400)', borderRadius: 'var(--radius)', font: 'inherit', resize: 'vertical' }} />
                        <label style={{ display: 'block', fontWeight: 600, color: 'var(--neutral-700)', margin: '18px 0 8px' }}>Vertical</label>
                        <select value={editVertical} onChange={(e) => setEditVertical(e.target.value)} style={{ width: '100%', boxSizing: 'border-box', padding: '10px 12px', border: '1px solid var(--neutral-400)', borderRadius: 'var(--radius)', font: 'inherit', background: 'var(--neutral-0)' }}>
                          <option value="">— None —</option>
                          {verticals.map(v => <option key={v} value={v}>{v}</option>)}
                        </select>
                      </>
                    )}
                    {/* aliases are edited here,
                        under Edit Customer — not as an Overview card. */}
                    <CustomerAliasesField
                      customerName={selectedCustomer.name}
                      canManage={canManageAliases}
                      onChange={(names) => {
                        // Keep the list payload's aliases (My Customers
                        // alias-aware search) current without a reload.
                        setCustomers((prev) => prev.map((c) => (c.id === selectedCustomer.id ? { ...c, aliases: names } : c)));
                        setSelectedCustomer({ ...selectedCustomer, aliases: names });
                      }}
                    />
                    {mutationStatus && <div role="status" style={{ color: 'var(--status-positive)', marginTop: '12px' }}>{mutationStatus}</div>}
                    {mutationError && <div role="alert" style={{ color: 'var(--status-negative)', marginTop: '12px' }}>{mutationError}</div>}
                    <div style={{ display: 'flex', gap: '10px', marginTop: '18px' }}>{canManageCustomer && <button role="button" aria-label="Save customer settings" disabled={mutationBusy} onClick={saveCustomer} style={{ padding: '10px 20px', background: 'var(--brand-500)', color: 'var(--neutral-0)', border: 'none', borderRadius: 'var(--radius)', cursor: mutationBusy ? 'not-allowed' : 'pointer' }}>{mutationBusy ? 'Saving…' : 'Save'}</button>}<button role="button" aria-label="Cancel customer settings" onClick={() => { setSettingsDialog(null); setMutationStatus(null); }} style={{ padding: '10px 20px', background: 'var(--neutral-0)', color: 'var(--neutral-500)', border: '1px solid var(--neutral-400)', borderRadius: 'var(--radius)', cursor: 'pointer' }}>{canManageCustomer ? 'Cancel' : 'Close'}</button></div>
                  </div>
                ) : (
                  <div style={{ background: 'var(--neutral-0)', borderRadius: 'var(--radius)', padding: '24px', boxShadow: 'var(--shadow-card)', maxWidth: '720px', width: '100%', border: '1px solid var(--status-negative)' }}>
                    <h2 style={{ margin: '0 0 14px', color: 'var(--status-negative)' }}>Remove customer?</h2>
                    <p style={{ color: 'var(--neutral-700)' }}>Removing <strong>{selectedCustomer.name}</strong> will permanently delete:</p>
                    <ul style={{ color: 'var(--neutral-500)', lineHeight: 1.8 }}><li>{customerUseCases.length} use cases</li><li>{departmentObjects.length} departments</li><li>{assessments.length} assessment rounds</li><li>All projections</li><li>All rep-owned deals, stage history and evidence links</li><li>All team assignments (owner/member/auditor junction rows)</li><li>All notifications</li></ul>
                    <p style={{ fontWeight: 700, color: 'var(--status-negative)' }}>This action is permanent and cannot be undone.</p>
                    {mutationError && <div role="alert" style={{ color: 'var(--status-negative)', marginBottom: '12px' }}>{mutationError}</div>}
                    <div style={{ display: 'flex', gap: '10px' }}><button role="button" aria-label="Confirm removing customer" disabled={mutationBusy} onClick={removeCustomer} style={{ padding: '10px 20px', background: 'var(--status-negative)', color: 'var(--neutral-0)', border: 'none', borderRadius: 'var(--radius)', cursor: mutationBusy ? 'not-allowed' : 'pointer', fontWeight: 600 }}>{mutationBusy ? 'Removing…' : 'Confirm remove'}</button><button role="button" aria-label="Cancel removing customer" onClick={() => { setSettingsDialog(null); setMutationError(null); }} style={{ padding: '10px 20px', background: 'var(--neutral-0)', color: 'var(--neutral-500)', border: '1px solid var(--neutral-400)', borderRadius: 'var(--radius)', cursor: 'pointer' }}>Cancel</button></div>
                  </div>
                )}
              </div>,
              document.body,
            )}

            {area === 'assessments' && (
              <div>
                <section aria-label="Customer discovery overview" style={{ marginBottom: '24px' }}>
                  <h2 style={{ margin: '0 0 8px', color: 'var(--ink)' }}>Customer discovery &amp; value</h2>
                  <p style={{ margin: '0 0 16px', color: 'var(--neutral-500)' }}>
                    Capture customer needs, evaluate use cases, and connect findings to the account plan. Assessment rounds preserve each discovery cycle.
                  </p>
                  <dl style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))', gap: '12px', margin: '0 0 16px' }}>
                    {[
                      ['Active rounds', roundsLoading ? 'Loading…' : roundsLoadError ? 'Unavailable' : assessments.filter((round) => round.status === 'active').length],
                      ['Customer use cases', loading ? 'Loading…' : error ? 'Unavailable' : customerUseCases.length],
                      ['AI use cases scored', loading || roundsLoading ? 'Loading…' : error || roundsLoadError ? 'Unavailable' : customerUseCases.filter((useCase) => !genericRoundIds.has(useCase.assessment_id ?? -1) && useCase.overall_score != null).length],
                      ['Draft use cases', loading ? 'Loading…' : error ? 'Unavailable' : customerUseCases.filter((useCase) => useCase.status === 'draft').length],
                    ].map(([label, value]) => (
                      <div key={label} style={{ padding: '16px', border: '1px solid var(--divider)', borderRadius: 'var(--radius)' }}>
                        <dt style={{ color: 'var(--neutral-500)', fontSize: '0.85rem' }}>{label}</dt>
                        <dd style={{ margin: '6px 0 0', color: 'var(--ink)', fontSize: '1.6rem', fontWeight: 600 }}>{value}</dd>
                      </div>
                    ))}
                  </dl>
                  {activeRound && <section className="crm-surface" aria-label="Active discovery cycle" style={{ marginBottom: 16 }}>
                    <h3 style={{ marginTop: 0 }}>{activeRound.name}</h3>
                    {activeRound.purpose && <p>{activeRound.purpose}</p>}
                    <p>{activeRound.assessment_type === 'generic' ? 'Discovery cycle · track use-case completion' : 'AI readiness cycle · score eligible use cases'}</p>
                    <p>{customerUseCases.filter(u => u.assessment_id === activeRound.id && u.status === 'completed').length} use cases completed · {customerUseCases.filter(u => u.assessment_id === activeRound.id && u.status === 'draft').length} drafts</p>
                    <button type="button" onClick={() => setArea('use-cases')}>Continue reviewing use cases</button>
                  </section>}
                  <nav aria-label="Discovery next steps" style={{ display: 'flex', flexWrap: 'wrap', gap: '8px' }}>
                    {[
                      ['use-cases', 'Review customer use cases'],
                      ['business-impact', 'Explore business impact'],
                      ['account-strategy', 'Open account plan'],
                    ].map(([destination, label]) => (
                      <button key={destination} type="button" onClick={() => setArea(destination)}
                        style={{ padding: '8px 12px', border: '1px solid var(--divider)', borderRadius: 'var(--radius)', background: 'var(--brand-50)', color: 'var(--brand-700)', cursor: 'pointer' }}>
                        {label} →
                      </button>
                    ))}
                  </nav>
                </section>
                {/* one consolidated card for the
                    Rounds area — the round registry, the round workflow
                    (create/archive), and starting a new assessment. The
                    duplicated "Assessment Report" use-case table is gone
                    (the dense working table lives one rail step over under
                    Use Cases) and the customer name is not
                    repeated inside the workspace. */}
                <div style={{ background: 'var(--neutral-0)', borderRadius: 'var(--radius)', padding: '20px', boxShadow: 'var(--shadow-card)' }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '12px', marginBottom: '16px' }}>
                    <h2 style={{ margin: 0, fontSize: '1.2rem', color: 'var(--ink)' }}>Assessment Rounds</h2>
                  </div>
                  {canAddUseCase && <details className="crm-disclosure">
                    <summary>New assessment round</summary>
                    <div className="crm-actions">
                      <input aria-label="New round name" type="text" placeholder="Round name (e.g. Q4 2026)"
                        value={newRoundName}
                        onChange={(e) => setNewRoundName(e.target.value)}
                        style={{ padding: '8px 12px', border: '1px solid var(--divider)', borderRadius: 'var(--radius)', fontSize: '0.9rem' }} />
                      <button role="button" aria-label="Create assessment round"
                        disabled={roundsBusy || !newRoundName.trim() || !newRoundType}
                        onClick={handleCreateRound}
                        style={{ padding: '8px 16px', background: roundsBusy || !newRoundName.trim() || !newRoundType ? 'var(--neutral-400)' : 'var(--brand-500)', color: 'var(--neutral-0)', border: 'none', borderRadius: 'var(--radius)', cursor: 'pointer', fontSize: '0.85rem', fontWeight: 600 }}>
                        + New Round
                      </button>
                    </div>
                  {/*explicit round type — neither option is
                      preselected, and + New Round stays disabled until one is
                      chosen. Purpose is optional for both types. */}
                  <fieldset style={{ border: '1px solid var(--divider)', borderRadius: 'var(--radius)', padding: '10px 14px', margin: '0 0 16px 0' }}>
                    <legend style={{ fontSize: '0.85rem', fontWeight: 600, color: 'var(--neutral-700)', padding: '0 4px' }}>Round type</legend>
                    <div role="radiogroup" aria-label="Round type" style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
                      <label style={{ display: 'flex', gap: '8px', alignItems: 'center', fontSize: '0.9rem', color: 'var(--ink)', cursor: 'pointer' }}>
                        <input type="radio" name="new-round-type" value="ai"
                          checked={newRoundType === 'ai'}
                          onChange={() => setNewRoundType('ai')} />
                        AI readiness assessment (dimension scoring, forecasts, readiness insight)
                      </label>
                      <label style={{ display: 'flex', gap: '8px', alignItems: 'center', fontSize: '0.9rem', color: 'var(--ink)', cursor: 'pointer' }}>
                        <input type="radio" name="new-round-type" value="generic"
                          checked={newRoundType === 'generic'}
                          onChange={() => setNewRoundType('generic')} />
                        Generic discovery assessment (no AI scoring)
                      </label>
                    </div>
                    {newRoundType && (
                      <textarea aria-label="Round purpose (optional)"
                        placeholder="Purpose (optional) — why this round is being run"
                        value={newRoundPurpose}
                        onChange={(e) => setNewRoundPurpose(e.target.value)}
                        rows={2}
                        style={{ marginTop: '10px', width: '100%', boxSizing: 'border-box', padding: '8px 12px', border: '1px solid var(--divider)', borderRadius: 'var(--radius)', fontSize: '0.9rem', font: 'inherit' }} />
                    )}
                  </fieldset>
                  </details>}
                  {roundError && (
                    <div role="alert" aria-live="assertive" style={{ padding: '10px 14px', background: 'var(--status-negative-soft)', borderLeft: '4px solid var(--status-negative)', borderRadius: 'var(--radius-sm)', color: 'var(--status-negative)', fontSize: '0.85rem', marginBottom: '12px' }}>
                      <span aria-hidden="true">⚠️ </span>{roundError}
                    </div>
                  )}
                  {roundsLoading ? <p role="status">Loading assessment rounds…</p> : roundsLoadError ? (
                    <div role="alert">Assessment rounds unavailable. <button type="button" onClick={() => void loadAssessments()}>Retry rounds</button></div>
                  ) : assessments.length === 0 ? (
                    <p style={{ color: 'var(--neutral-500)', fontSize: '0.9rem', margin: 0 }}>No assessment rounds yet. Create a discovery or AI readiness round to organize this customer's needs and use cases.</p>
                  ) : (
                    <div role="region" aria-label="Assessment rounds" tabIndex={0} style={{ overflowX: 'auto' }}><table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.9rem' }}>
                      <thead>
                        <tr style={{ borderBottom: '1px solid var(--divider)', color: 'var(--neutral-500)', textAlign: 'left' }}>
                          <th style={{ padding: '8px' }}>Round</th>
                          <th style={{ padding: '8px' }}>Status</th>
                          <th style={{ padding: '8px' }}>Use cases</th>
                          <th style={{ padding: '8px' }}>Created</th>
                          <th style={{ padding: '8px' }} aria-label="Round actions"></th>
                        </tr>
                      </thead>
                      <tbody>
                        {assessments.map((a) => (
                          <tr key={a.id} style={{ borderBottom: '1px solid var(--divider)' }}>
                            <td style={{ padding: '8px', fontWeight: 600, color: 'var(--ink)' }}>
                              {a.name}
                              <span data-testid={`round-type-${a.id}`} style={{ marginLeft: '8px', padding: '1px 8px', borderRadius: 'var(--radius)', fontSize: '0.7rem', fontWeight: 600, background: a.assessment_type === 'generic' ? 'var(--neutral-100)' : 'var(--brand-100)', color: a.assessment_type === 'generic' ? 'var(--neutral-700)' : 'var(--brand-700)' }}>
                                {a.assessment_type === 'generic' ? 'Generic' : 'AI'}
                              </span>
                              {a.purpose?.trim() && (
                                <div data-testid={`round-purpose-${a.id}`} style={{ fontWeight: 400, fontSize: '0.8rem', color: 'var(--neutral-500)', marginTop: '2px' }}>{a.purpose}</div>
                              )}
                            </td>
                            <td style={{ padding: '8px' }}>
                              <span style={{ padding: '2px 10px', borderRadius: 'var(--radius)', fontSize: '0.75rem', fontWeight: 600, background: a.status === 'active' ? 'var(--status-positive-soft)' : 'var(--neutral-100)', color: a.status === 'active' ? 'var(--status-positive)' : 'var(--neutral-500)' }}>
                                {a.status}
                              </span>
                            </td>
                            <td style={{ padding: '8px' }}>{a.use_case_count ?? 0}</td>
                            <td style={{ padding: '8px', color: 'var(--neutral-500)' }}>{a.created_at ? new Date(a.created_at).toLocaleDateString() : '—'}</td>
                            <td style={{ padding: '8px', textAlign: 'right' }}>
                              {/* the round action
                                  moves into a per-row overflow menu. */}
                              {a.status === 'active' && canAddUseCase && (
                                <RowActions
                                  ariaLabel={`Actions for round ${a.name}`}
                                  items={[{
                                    label: 'Archive round',
                                    onClick: () => handleArchiveRound(a.id),
                                    disabled: roundsBusy,
                                  }]}
                                />
                              )}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table></div>
                  )}
                  {canAddUseCase && <details className="crm-disclosure" open={newAssessmentOpen} onToggle={event => setNewAssessmentOpen(event.currentTarget.open)} style={{ marginTop: '28px' }}>
                    <summary>Start a new assessment</summary>
                    <h3 style={{ fontSize: '1.1rem', margin: '0 0 4px 0' }}>Start a New Assessment</h3>
                    {templatesBlocked ? (
                      <p role="note" style={{ color: 'var(--neutral-500)', margin: '0 0 16px 0', fontSize: '0.9rem' }}>
                        Templates are AI use-case templates — generic rounds start blank
                      </p>
                    ) : (
                      <p style={{ color: 'var(--neutral-500)', margin: '0 0 16px 0', fontSize: '0.9rem' }}>
                        Pick an AI template to pre-fill the assessment — or start from a blank page if none fits.
                      </p>
                    )}
                    {newAssessmentMode === 'template' && !templatesBlocked ? (
                      <TemplatesPage
                        key={`assessment-tpl-${selectedCustomer.id}`}
                        customer={selectedCustomer}
                        onStartBlank={() => setNewAssessmentMode('blank')}
                        onCreated={async () => {
                          // The template flow now bootstraps departments + one
                          // draft use case per goal via the backend. Refresh the
                          // use cases, departments, and rounds to reflect it.
                          const [useCases, deptData] = await Promise.all([
                            api.getCustomerUseCases(selectedCustomer.name),
                            api.listDepartments(selectedCustomer.name),
                          ]);
                          setCustomerUseCases(useCases);
                          setDepartmentObjects(deptData.map((d: any) => ({ id: d.id, name: d.name, use_case_count: d.use_case_count || 0 })));
                          loadAssessments();
                        }}
                        onCancel={() => setNewAssessmentOpen(false)}
                      />
                    ) : (
                      <div>
                        <AssessmentForm
                          key={`assessment-form-${selectedCustomer.id}`}
                          initialCustomerName={selectedCustomer.name}
                          onSubmit={async (data) => {
                            // Create assessment with pre-selected customer
                            await api.create(data);
                            // Refresh use cases
                            const useCases = await api.getCustomerUseCases(selectedCustomer.name);
                            setCustomerUseCases(useCases);
                          }}
                          onCancel={() => setNewAssessmentOpen(false)}
                        />
                      </div>
                    )}
                  </details>}
                </div>
              </div>
            )}

            {area === 'bulk-score' && (
              <div>
                <h2 style={{ margin: '0 0 16px 0', fontSize: '1.3rem', color: 'var(--ink)' }}>
                  Bulk Score for {selectedCustomer.name}
                </h2>
                {/* F10: onBack KEEPS the customer (the old handler evicted
                    the selection → "Select a Customer") and refetches the
                    use cases so the fresh scores show in the Overview. */}
                <BulkScore
                  key={`bulk-score-${selectedCustomer.id}`}
                  onBack={() => {
                    setArea('assessments');
                    (async () => {
                      try {
                        const [useCases, deptData] = await Promise.all([
                          api.getCustomerUseCases(selectedCustomer.name),
                          api.listDepartments(selectedCustomer.name),
                        ]);
                        setCustomerUseCases(useCases);
                        setDepartmentObjects(deptData.map((d: any) => ({
                          id: d.id,
                          name: d.name,
                          use_case_count: d.use_case_count || 0,
                        })));
                      } catch { /* keep the last known state on refetch failure */ }
                    })();
                  }}
                  selectedCustomerId={selectedCustomer.id}
                  selectedCustomerName={selectedCustomer.name}
                  aiScoringBlockedRoundIds={genericRoundIds}
                />
              </div>
            )}

            {area === 'analytics' && (
              <div>
                <h2 style={{ margin: '0 0 16px 0', fontSize: '1.3rem', color: 'var(--ink)' }}>
                  Analytics for {selectedCustomer.name}
                </h2>
                {/* 1. Analytics Dashboard (department trend analysis) */}
                <AnalyticsDashboard
                  key={`analytics-dash-${selectedCustomer.id}`}
                  selectedCustomerId={selectedCustomer.id}
                  selectedCustomerName={selectedCustomer.name}
                  section="trends"
                />
                {/* 2. Department Summary */}
                <DeptComparison
                  key={`dept-summary-${selectedCustomer.id}`}
                  customerId={selectedCustomer.id}
                  section="summary"
                />
                {/* 3. Department Comparison */}
                <DeptComparison
                  key={`dept-comparison-${selectedCustomer.id}`}
                  customerId={selectedCustomer.id}
                  section="comparison"
                />
                {/* 4. Departmental Breakdown (use-case volume + avg readiness per department) */}
                <DeptComparison
                  key={`dept-breakdown-${selectedCustomer.id}`}
                  customerId={selectedCustomer.id}
                  section="breakdown"
                />
                {/* 5. Trend Predictions (AI model, 45/135/270-day horizons) */}
                <AnalyticsDashboard
                  key={`predictions-${selectedCustomer.id}`}
                  selectedCustomerId={selectedCustomer.id}
                  section="predictions"
                />
              </div>
            )}

            {area === 'business-impact' && (
              <BusinessImpact
                key={`biz-impact-${selectedCustomer.id}`}
                customer={selectedCustomer}
                embedded
              />
            )}

            {area === 'export' && selectedCustomer && (
              <CustomerExport
                customer={selectedCustomer}
                useCases={customerUseCases}
                onBack={() => setArea('assessments')}
              />
            )}

            {area === 'business-impact-forecasting' && selectedCustomer && (
              <CustomerProjections
                customerName={selectedCustomer.name}
                customerId={selectedCustomer.id}
                userRole={userRole}
              />
            )}

            {area === 'customer-knowledge' && selectedCustomer && (
              <CustomerKnowledgeBrowser
                allowWrite={workspaceActions?.capabilities.knowledge ?? false}
                key={selectedCustomer.id}
                customerId={selectedCustomer.id}
                onClose={() => setArea('intelligence-summary')}
              />
            )}

            {area === 'technology-inventory' && selectedCustomer && (
              <TechnologyInventory allowWrite={workspaceActions?.capabilities.technology ?? false} customerId={selectedCustomer.id} userRole={userRole} />
            )}

            {area === 'sales-notes' && selectedCustomer && (
              <SalesNotes allowWrite={workspaceActions?.capabilities.note ?? false} key={selectedCustomer.id} customerId={selectedCustomer.id} userRole={userRole} />
            )}

            {area === 'contacts' && selectedCustomer && (
              <ContactsPanel key={`contact-${selectedCustomer.id}`} allowCreate={workspaceActions?.capabilities.contact ?? false} createRequest={quickCreate?.customer === selectedCustomer.id && quickCreate.target === 'contact' ? quickCreate.request : 0} customerId={selectedCustomer.id} userRole={userRole} />
            )}

            {area === 'activities' && selectedCustomer && (
              <ActivitiesPanel key={`activity-${selectedCustomer.id}`} allowCreate={workspaceActions?.capabilities.activity ?? false} createRequest={quickCreate?.customer === selectedCustomer.id && quickCreate.target === 'activity' ? quickCreate.request : 0} customerId={selectedCustomer.id} userRole={userRole} />
            )}

            {area === 'tasks' && selectedCustomer && (
              <TasksPanel key={`task-${selectedCustomer.id}`} allowCreate={workspaceActions?.capabilities.task ?? false} createRequest={quickCreate?.customer === selectedCustomer.id && quickCreate.target === 'task' ? quickCreate.request : 0}
                customerId={selectedCustomer.id}
                userRole={userRole}
                assignees={workspaceActions?.assignees ?? []}
                assigneeHints={[
                  selectedCustomer.primary_rep,
                  selectedCustomer.manager_name,
                  ...(selectedCustomer.inside_sales ?? []).map((u) => u.name),
                  ...(selectedCustomer.sales_ops ?? []).map((u) => u.name),
                ].filter((n): n is string => !!n)}
              />
            )}

            {area === 'account-brief' && selectedCustomer && (
              <AccountBriefPanel customerId={selectedCustomer.id} userRole={userRole} />
            )}

            {area === 'account-timeline' && selectedCustomer && (
              <AccountTimelinePanel
                customerId={selectedCustomer.id}
                onSelect={(module, id) => {
                  if (KIND_AREAS[module]) setArea(KIND_AREAS[module]);
                  else customerRecord.select(module, id);
                }}
              />
            )}

            {area === 'third-party-services' && selectedCustomer && (
              <ThirdPartyServices customerId={selectedCustomer.id} userRole={userRole} />
            )}

            {/* Sales workspace: Opportunities
                (the synthesis panel as a standalone Sales destination), Evaluations
                (persona-driven
                generation), and the Account Strategy placeholder for future
                planning functionality. */}
            {area === 'sales-deals' && selectedCustomer && (
              <DealsPanel refreshRequest={recordRefresh} onOpenDeal={id => customerRecord.select('deal', id)} onChanged={() => setRecordRefresh(value => value + 1)} editRecordId={quickCreate?.customer === selectedCustomer.id ? quickCreate.id : undefined} editRequest={quickCreate?.target === 'deal-edit' ? quickCreate.request : 0} key={`deal-${selectedCustomer.id}`} allowCreate={workspaceActions?.capabilities.deal ?? false} createRequest={quickCreate?.customer === selectedCustomer.id && quickCreate.target === 'deal' ? quickCreate.request : 0} customerId={selectedCustomer.id} userRole={userRole} />
            )}

            {area === 'sales-opportunities' && (
              <div>
                {/* UX audit #10: dropped the outer <h2> — the panel owns the
                    heading (incl. the live count). The duplicate rendered
                    "Opportunities & Attention" twice. */}
                <OpportunitiesPanel
                  customerId={selectedCustomer.id}
                  onExplore={() => setArea('sales-evaluations')}
                  userRole={userRole}
                  allowDeals={workspaceActions?.capabilities.deal ?? false}
                  onOpenDeal={id => customerRecord.select('deal', id)}
                />
                <CustomerRedHatOpportunities customerId={selectedCustomer.id} />
              </div>
            )}

            {area === 'sales-pipeline' && <CustomerPipeline customerName={selectedCustomer.name} customerId={selectedCustomer.id} allowDeals={workspaceActions?.capabilities.deal ?? false} onOpenDeal={id => customerRecord.select('deal', id)} />}
            {area === 'sales-vendor-intelligence' && <CustomerRvTools customerName={selectedCustomer.name} />}

            {area === 'sales-evaluations' && selectedCustomer && (
              <SalesEvaluation customerId={selectedCustomer.id} customerName={selectedCustomer.name} />
            )}

            {/* Account Strategy (H7): plan + evidence-derived suggestions +
                linked next actions + immutable snapshots. Suggestions are
                computed server-side and never applied automatically. */}
            {area === 'account-strategy' && selectedCustomer && (
              <AccountStrategyPanel customerId={selectedCustomer.id} userRole={userRole} />
            )}

            {area === 'team' && selectedCustomer && (
              <CustomerTeam
                customerName={selectedCustomer.name}
                customerId={selectedCustomer.id}
                userRole={userRole}
              />
            )}

            {area === 'departments' && selectedCustomer && (
              <DepartmentManager
                customerName={selectedCustomer.name}
                userRole={userRole}
                departments={departmentObjects}
                onDepartmentChange={() => loadCustomerAndDepartments(selectedCustomer.name)}
              />
            )}

            {area === 'detail' && detailLoading && <div role="status">Loading use case…</div>}
            {area === 'detail' && detailError && <div role="alert">{detailError} <button type="button" onClick={() => setArea('use-cases')}>Return to use cases</button></div>}
            {area === 'detail' && !detailLoading && selectedUseCase && selectedUseCase.id === detailId && selectedUseCase.customer_id === selectedCustomer.id && (!selectedCustomerName || selectedCustomer.name === selectedCustomerName) && (
              // (F6): the shared detail component — this
              // ~185-line inline copy (already diverged from Home's:
              // labels + navigation targets) is gone. The callbacks hand
              // the use case up to Home for cross-view navigation (F1
              // fix) and drive local state for edit/delete/score/back.
              <UseCaseDetail
                allowWrite={canAddUseCase}
                useCase={selectedUseCase}
                userRole={userRole}
                busy={scoreLoading}
                scoringUnavailableReason={isGenericRoundUseCase(selectedUseCase) ? AI_SCORING_REQUIRES_AI_ASSESSMENT : null}
                onEdit={(uc) => (onEditUseCase ? onEditUseCase(uc) : onNavigate('assessment-create'))}
                onDelete={canDeleteUseCase ? handleDeleteUseCase : undefined}
                onScore={(uc) => handleScore(uc.id)}
                onOpenScoring={(uc) => (onOpenScoring ? onOpenScoring(uc) : onNavigate('scoring-dashboard'))}
                onOpenDrilldown={(uc) => (onOpenDrilldown ? onOpenDrilldown(uc) : onNavigate('scoring-drilldown'))}
                onOpenComments={(uc) => (onOpenComments ? onOpenComments(uc) : onNavigate('collab-comments'))}
                onBack={() => { setSelectedUseCase(null); setArea('use-cases'); }}
                commentsLabel="💬 Open Comments"
              />
            )}
            </section>
          </div>
        )}
      </div>
    </div>
  );
}
export default CustomerDashboard;
