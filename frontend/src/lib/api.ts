import {
  UseCase,
  UseCaseCreate,
  UseCaseUpdate,
  ScoredUseCaseResponse,
  CustomerUserResponse,
  CustomerSalesTeam,
  CustomerSalesTeamUpdate,
  StatsResponse,
  Department,
  MyCustomerAccess,
  InferenceConfigResponse,
  ScoreTrend,
  TemplateListResponse,
  BulkScoreResult,
  ImpactMatrixResponse,
  DeptComparisonResponse,
  DrillDownResponse,
  Comment,
  NotificationItem,
  DepartmentTrend,
  Customer,
  CustomerAlias,
  GlobalStats,
  GlobalAdminStats,
  PortfolioAccountImpact,
  CustomerAssessment,
  AssessmentType,
  AIPrediction,
  UserResponse,
  AccessCheckResponse,
  Projection,
  VerticalsResponse,
  BootstrapResult,
  ReadinessInsight,
  ReadinessInsightResponse,
  OwnershipReviewItem,
  AccountMembership,
} from "../types/use_case";
import type { AccountBrief } from "../types/brief";
import type { AccountTimelineResponse } from "../types/accountTimeline";
import type { AccountSearchResponse } from "../types/accountSearch";
import type { SavedViewsResponse, SaveViewResponse, WorklistResponse } from "../types/savedViews";
import type { TeamRollupResponse } from '../types/teamRollup';
import type { Deal, DealHistoryEntry, DealInput, PipelineStage } from '../types/deals';
import type { AccountHealthResponse } from "../types/accountHealth";
import type { RedHatOpportunityImportResult, RedHatOpportunityImportSummary, RedHatOpportunityReport } from "../types/redhatOpportunity";
import type { Activity, ActivityCreate, ActivityUpdate, MyTask, Task, TaskCreate, TaskPromote, TaskPromotionResponse, TaskUpdate } from "../types/engagement";
import type { ContactCoverage, ContactCreate, ContactUpdate, CustomerContact } from "../types/contact";
import type {
  StrategyLinks, StrategyLinksUpdate, StrategyPlan, StrategySnapshot, StrategySnapshotList,
  StrategySnapshotPublish, StrategySnapshotSummary, StrategyUpdate, StrategyView,
} from "../types/strategy";
import {
  CustomerTechnology,
  CustomerTechnologyCreate,
  SalesNote,
  SalesNoteCreate,
  CustomerIntelligenceOverview,
  SalesPersona,
  SalesEvaluationPreview,
  AccountWorkspace,
  CustomerIntelligenceGraph,
  ThirdPartyService,
  ThirdPartyServiceCreate,
  ThirdPartyServiceUpdate,
  ThirdPartyServiceDocument,
} from "../types/sail";
import type {
  IntelligenceImportResult,
  IntelligenceImportSummary,
  IntelligenceImportDetail,
  IntelligenceImportDeleteResult,
  CustomerPipeline,
} from "../types/intelligence_import";
import type {
  RepIntelligenceResult,
  RepIntelligenceSummary,
  RepIntelligenceDetail,
  RepIntelligenceDeleteResult,
} from "../types/rep_intelligence";
import type {
  NetSuiteImportDetail,
  NetSuiteImportRow,
  NetSuiteImportSummary,
} from "../types/netsuite_import";
import type {
  RVToolsImportTarget,
  RVToolsImportDetail,
  RVToolsImportSummary,
  RVToolsImportDeleteResult,
  CustomerRvTools,
} from "../types/rvtools_import";
import type { KnowledgeContentResponse, KnowledgeEnrichmentItem } from "../types/customer_knowledge";
import { setAuth, clearAuth, getAuthToken, getAuthUsername, getAuthIsAdmin, getAuthRole, getAuthSalesRole } from "./auth";
import { beginSessionRedirect, markSessionExpired, saveSessionReturn } from "./sessionRedirect";

export { setAuth, clearAuth, getAuthToken, getAuthUsername, getAuthIsAdmin, getAuthRole, getAuthSalesRole };

export class SessionExpiredError extends Error {
  constructor() {
    super('Session expired. Please log in again.');
    this.name = 'SessionExpiredError';
  }
}

const API_BASE = "/api";

// Connection trust model (SSL/TLS): full = verify
// chain + hostname; skip = TLS on, verification off (high-risk); ca = verify
// against an uploaded CA bundle. Applied to inference + Docling connections
// (and LDAP from P1) via the backend ssl_trust seam.
export type SslVerifyMode = "full" | "skip" | "ca";

export interface DoclingConfigResponse {
  server_url: string;
  timeout_seconds: number | null;
  ssl_verify: SslVerifyMode;
  ssl_ca_bundle: string | null;
}

// Document processing provider. The Azure API key is
// deliberately absent: it is env-only (SAIL_AZURE_DI_API_KEY) and only its
// configured state crosses the API (api_key_configured, ignored on write).
export type DocumentProvider = "docling" | "azure_document_intelligence";

export interface DocumentProcessingConfig {
  provider: DocumentProvider;
  azure_endpoint: string;
  azure_timeout_seconds: number | null;
  azure_ssl_verify: SslVerifyMode;
  azure_ssl_ca_bundle: string | null;
  api_key_configured: boolean;
}

// Directory (LDAP/AD) authentication. The service bind
// password is deliberately absent: it is env/Secret-only and never part of
// the API surface.
export interface LdapSettingsResponse {
  enabled: boolean;
  server_uri: string;
  service_bind_dn: string;
  user_search_base_dn: string;
  user_search_filter: string;
  start_tls: boolean;
  require_tls: boolean;
  ssl_verify: SslVerifyMode;
  ssl_ca_bundle: string | null;
  timeout_seconds: number;
  email_attr: string;
  display_name_attr: string;
  department_attr: string;
  external_id_attr: string;
  auto_approve: boolean;
  default_role: string;
  login_disabled: boolean;
  local_register_enabled: boolean;
}

// Email notifications (EL-05/06). The SMTP password is env-only
// (SAIL_EMAIL_SMTP_PASSWORD) and never part of the API surface.
export type SmtpSecurityMode = 'starttls' | 'ssl' | 'none';
export interface EmailConfigResponse {
  enabled: boolean;
  smtp_host: string;
  smtp_port: number;
  smtp_username: string;
  smtp_security: SmtpSecurityMode;
  from_address: string;
  password_configured: boolean;
}
export interface EmailTestResponse {
  ok: boolean;
  latency_ms: number;
  error: string | null;
}

export interface LdapTestResponse {
  ok: boolean;
  latency_ms: number;
  user_count_sampled: number;
  error: string | null;
}

// Unauthenticated public auth settings (drives the Login page).
export interface AuthPublicSettingsResponse {
  local_register_enabled: boolean;
  ldap_enabled: boolean;
  login_hint: string;
}

type InferenceConfigResponseWithSsl = InferenceConfigResponse & {
  ssl_verify: SslVerifyMode;
  ssl_ca_bundle: string | null;
};

async function request<T>(endpoint: string, queryParams?: Record<string, string>, options?: RequestInit): Promise<T> {
  let url = `${API_BASE}${endpoint}`;
  if (queryParams && Object.keys(queryParams).length > 0) {
    const search = new URLSearchParams(queryParams).toString();
    url += `?${search}`;
  }
  const token = getAuthToken();
  const fetchHeaders = new Headers(options?.headers as Record<string, string> || {});
  if (!(options?.body instanceof FormData)) fetchHeaders.set("Content-Type", "application/json");
  // Don't send auth token to auth endpoints — login/register/approve don't use JWT,
  // and sending an expired token causes 401 → "session expired" redirect loops.
  const authEndpointPrefixes = ["/auth/login", "/auth/register", "/auth/approve"];
  if (token && !authEndpointPrefixes.some(prefix => endpoint.startsWith(prefix))) {
    fetchHeaders.set("Authorization", `Bearer ${token}`);
  }
  // F4: fetch can reject with AbortError — a manual cancel (the
  // overlay's Cancel button) or the 300s cap aborting the wait. Map it to
  // a clear, actionable message instead of the raw "The operation was
  // aborted.". Client-side only: the server-side work may still run to
  // completion (no server cancel protocol exists — note for a future
  // backend WP).
  let response: Response;
  try {
    response = await fetch(url, {
      ...options,
      headers: fetchHeaders,
    });
  } catch (err: any) {
    if (err?.name === 'AbortError') {
      throw new Error('Operation cancelled — the server may still be finishing the work.');
    }
    throw err;
  }

  // 401: clear auth and redirect to login (but not if already on /login).
  // Don't treat 401s from auth endpoints as session expiration — those are
  // actual login failures that should show the backend's error message.
  // FE-08: preserve the current internal destination (pathname+search+hash)
  // so signing back in returns the user there, and collapse simultaneous 401s
  // into a single transition (only the first one redirects).
  if (response.status === 401) {
    const isAuthEndpoint = endpoint.startsWith('/auth/');
    if (!isAuthEndpoint && window.location.pathname !== '/login') {
      if (beginSessionRedirect()) {
        saveSessionReturn();
        markSessionExpired();
        clearAuth();
        window.history.replaceState(null, '', '/login');
        window.dispatchEvent(new PopStateEvent('popstate'));
      }
    }
    if (!isAuthEndpoint) throw new SessionExpiredError();
    throw new Error('Invalid credentials');
  }

  if (!response.ok) {
    const text = await response.text().catch(() => '');
    let error: any;
    try { error = JSON.parse(text); } catch { error = { detail: text || response.statusText }; }
    // status rides on the Error so callers can tell 403 (access denied) apart.
    throw Object.assign(new Error(formatApiError(error, response.status)), { status: response.status });
  }
  if (response.status === 204) return undefined as T;
  const text = await response.text().catch(() => '');
  if (!text) return undefined as T;
  return JSON.parse(text);
}

/**
 * F2: deterministic API error rendering (single code path for every
 * `request()` caller — the banners already display `err.message`).
 *
 * FastAPI validation errors (422) carry `detail` as an ARRAY of
 * `{loc, msg, type}` objects; the previous `new Error(error.detail)`
 * stringified them to "[object Object],[object Object]". Rule: one
 * "field: message" per entry — `loc` minus the leading route segment
 * ('body'/'query'/'path') so the message names the FIELD, not the route
 * (`['body','title']` → "title: field required") — joined with "; ".
 * String `detail` and non-JSON bodies keep the previous behavior.
 */
function formatApiError(error: any, status: number): string {
  const detail = error?.detail;
  if (Array.isArray(detail)) {
    const parts = detail
      .map((entry: any): string => {
        if (typeof entry === 'string') return entry;
        if (entry && typeof entry === 'object') {
          const loc = Array.isArray(entry.loc) ? entry.loc : [];
          const field = loc.slice(1).join('.');
          const msg = typeof entry.msg === 'string' ? entry.msg : JSON.stringify(entry);
          return field ? `${field}: ${msg}` : msg;
        }
        return String(entry);
      })
      .filter((s: string) => s.length > 0);
    if (parts.length > 0) return parts.join('; ');
  }
  if (typeof detail === 'string' && detail) return detail;
  return `HTTP ${status}`;
}

/**
 * F3: blob downloads must not swallow HTTP errors. The export
 * functions previously did `res.blob()` with no `res.ok` check — a 500
 * downloaded the JSON error body as the "export" file (a corrupt
 * report.pdf/.xlsx/.csv). Parse the error detail (same helper as
 * request()) and throw; the export surfaces (ExportPage, CustomerExport)
 * already surface errors in banners, so the corrupt-download path dies
 * and the user sees the real reason. Success path unchanged (blob).
 */
async function fetchBlobOrThrow(res: Response): Promise<Blob> {
  if (!res.ok) {
    const text = await res.text().catch(() => '');
    let error: any;
    try { error = JSON.parse(text); } catch { error = { detail: text || res.statusText }; }
    throw new Error(formatApiError(error, res.status));
  }
  return res.blob();
}

// F4: the export fetch paths (manual cancel / 300s cap abort the
// fetch BEFORE fetchBlobOrThrow runs, so map the AbortError here — same
// clear message as request()).
function mapAbortError<T>(p: Promise<T>): Promise<T> {
  return p.catch((err: any) => {
    if (err?.name === 'AbortError') {
      throw new Error('Operation cancelled — the server may still be finishing the work.');
    }
    throw err;
  });
}

export const api = {
  // Use cases
  list: (params?: { skip?: number; limit?: number; department?: string; status?: string; search?: string; customer_id?: string; sort?: string }) => {
    if (!params) return request<UseCase[]>("/use-cases/");
    const strParams: Record<string, string> = {};
    for (const [k, v] of Object.entries(params)) {
      if (v !== undefined && v !== null) strParams[k] = String(v);
    }
    return request<UseCase[]>("/use-cases/", strParams);
  },
  get: (id: number) => request<UseCase>(`/use-cases/${id}/`),
  create: (data: UseCaseCreate, signal?: AbortSignal) => request<UseCase>(`/use-cases/`, undefined, { method: "POST", body: JSON.stringify(data), signal }),
  update: (id: number, data: UseCaseUpdate, signal?: AbortSignal) => request<UseCase>(`/use-cases/${id}/`, undefined, { method: "PUT", body: JSON.stringify(data), signal }),
  // DELETE /use-cases/{id}/ → 204 (no body). Backend authorization:
  // non-admin callers need the owner role on the use case's customer.
  deleteUseCase: (id: number) => request<void>(`/use-cases/${id}/`, undefined, { method: "DELETE" }),

  // Scoring
  // POST /scoring/ returns the {use_case, scores} envelope (ScoredUseCaseResponse)
  // F4: `signal` — the caller's AbortController (300s cap / cancel).
  score: (use_case_id: number, signal?: AbortSignal) => request<ScoredUseCaseResponse>("/scoring/", undefined, {
    method: "POST",
    body: JSON.stringify({ use_case_id }),
    signal,
  }),

  // Stats
  aggregateStats: () => request<StatsResponse>("/stats/aggregate/"),
  scoreTrends: (days?: number) => request<ScoreTrend[]>("/stats/trends/", days ? { days: String(days) } : undefined),
  exportCSV: (customer_name?: string, use_case_ids?: number[], assessment_id?: number, signal?: AbortSignal) => {
    const token = getAuthToken();
    const qs = [
      customer_name ? `customer_name=${encodeURIComponent(customer_name)}` : '',
      use_case_ids && use_case_ids.length ? `use_case_ids=${use_case_ids.join(',')}` : '',
      assessment_id != null ? `assessment_id=${assessment_id}` : '',
    ].filter(Boolean).join('&');
    const url = `${API_BASE}/stats/export/csv/${qs ? `?${qs}` : ''}`;
    return mapAbortError(fetch(url, { headers: token ? { Authorization: `Bearer ${token}` } : undefined, signal }).then(fetchBlobOrThrow));
  },
  exportExcel: (customer_name?: string, use_case_ids?: number[], assessment_id?: number, signal?: AbortSignal) => {
    const token = getAuthToken();
    const qs = [
      customer_name ? `customer_name=${encodeURIComponent(customer_name)}` : '',
      use_case_ids && use_case_ids.length ? `use_case_ids=${use_case_ids.join(',')}` : '',
      assessment_id != null ? `assessment_id=${assessment_id}` : '',
    ].filter(Boolean).join('&');
    const url = `${API_BASE}/stats/export/excel/${qs ? `?${qs}` : ''}`;
    return mapAbortError(fetch(url, { headers: token ? { Authorization: `Bearer ${token}` } : undefined, signal }).then(fetchBlobOrThrow));
  },
  exportPdf: (customer_name?: string, use_case_ids?: number[], assessment_id?: number, signal?: AbortSignal) => {
    const token = getAuthToken();
    const qs = [
      customer_name ? `customer_name=${encodeURIComponent(customer_name)}` : '',
      use_case_ids && use_case_ids.length ? `use_case_ids=${use_case_ids.join(',')}` : '',
      assessment_id != null ? `assessment_id=${assessment_id}` : '',
    ].filter(Boolean).join('&');
    const url = `${API_BASE}/export/pdf/${qs ? `?${qs}` : ''}`;
    return mapAbortError(fetch(url, { headers: token ? { Authorization: `Bearer ${token}` } : undefined, signal }).then(fetchBlobOrThrow));
  },

  // Bulk operations
  // The backend binds the entire body as a bare JSON array of ids (FastAPI:
  // a bare List[int] parameter without Query() IS the request body).
  // F4: `signal` — the caller's AbortController (300s cap / cancel).
  bulkScore: (use_case_ids: number[], signal?: AbortSignal) => request<BulkScoreResult>("/bulk/score-multiple/", undefined, {
    method: "POST",
    body: JSON.stringify(use_case_ids),
    signal,
  }),
  // Routes live under /api/bulk (backend/routes/bulk.py)
  templates: () => request<TemplateListResponse>("/bulk/templates/"),

  // Advanced visualizations
  impactMatrix: (params?: Record<string, string>) => request<ImpactMatrixResponse>(`/advanced/impact-matrix/`, params),
  deptComparison: (params?: Record<string, string>) => request<DeptComparisonResponse>(`/advanced/dept-comparison/`, params),
  drillDown: (use_case_id: number) => request<DrillDownResponse>(`/advanced/drill-down/${use_case_id}/`),

  // Comments — the author is derived from the JWT (no user_name payload)
  getComments: (use_case_id: number) => request<Comment[]>(`/use-cases/${use_case_id}/comments/`),
  createComment: (use_case_id: number, content: string) =>
    request<Comment>(`/use-cases/${use_case_id}/comments/`, undefined, {
      method: 'POST',
      body: JSON.stringify({ content }),
    }),
  updateComment: (comment_id: number, content: string) =>
    request<Comment>(`/use-cases/comments/${comment_id}/`, undefined, {
      method: 'PUT',
      body: JSON.stringify({ content }),
    }),
  deleteComment: (comment_id: number) => request<void>(`/use-cases/comments/${comment_id}/`, undefined, { method: 'DELETE' }),
  // Notifications — the caller's own only (identity from the JWT)
  getNotifications: (limit?: number, unread_only?: boolean, customer_id?: number) => {
    const params: Record<string, string> = {};
    if (limit) params.limit = String(limit);
    if (unread_only) params.unread_only = 'true';
    if (customer_id !== undefined) params.customer_id = String(customer_id);
    return request<NotificationItem[]>(`/use-cases/notifications/`, params);
  },
  markNotificationRead: (notification_id: number) => request<void>(`/use-cases/notifications/${notification_id}/read/`, undefined, { method: 'POST' }),

  // Analytics
  departmentTrends: (customer_id?: number | null) => request<DepartmentTrend[]>(`/analytics/department-trends/`, customer_id != null ? { customer_id: String(customer_id) } : undefined),
  // Persisted, LLM-generated per-customer readiness insight.
  readinessInsight: (customer_id: number) => request<ReadinessInsightResponse>(`/analytics/readiness-insight/`, { customer_id: String(customer_id) }),
  generateReadinessInsight: (customer_id: number, signal?: AbortSignal) => request<ReadinessInsight>(`/analytics/readiness-insight/generate/`, { customer_id: String(customer_id) }, { method: "POST", signal }),

  // Integrations
  integrationStatus: () => request<Record<string, boolean>>(`/integrations/status/`),
  getDatabaseDiagnostics: () => request<{ database: { backend?: string; connected: boolean } }>('/monitoring/health/detailed'),
  sendSlack: (message: string, title?: string) =>
    request<void>(`/integrations/slack/send/`, undefined, {
      method: 'POST',
      body: JSON.stringify({ message, title: title || 'S-A-I-L' }),
    }),
  sendTeams: (message: string, title?: string) =>
    request<void>(`/integrations/teams/send/`, undefined, {
      method: 'POST',
      body: JSON.stringify({ message, title: title || 'S-A-I-L' }),
    }),

  // Authentication
  login: (username: string, password: string) => {
    return request<{ username: string; email: string; display_name: string; token: string; department: string; is_admin: boolean; role: string; sales_role: string | null }>(
      `/auth/login/`, undefined, {
        method: 'POST',
        body: JSON.stringify({ username, password }),
      }
    );
  },
  register: (data: { username: string; email: string; password: string; display_name?: string; department?: string }) => {
    const body: Record<string, string | number | undefined> = {
      username: data.username,
      email: data.email,
      password: data.password,
      display_name: data.display_name || undefined,
    };
    if (data.department) body.department = data.department;
    return request<{ id: number; username: string; email: string; display_name: string; department: string; created_at: string; is_active: number; approved: number }>(
      `/auth/register/`, undefined, {
        method: 'POST',
        body: JSON.stringify(body),
      }
    );
  },

  // Admin endpoints
  approveUser: (username: string) => request<UserResponse>(`/auth/approve/${encodeURIComponent(username)}/`, undefined, { method: 'POST' }),
  getPendingUsers: () => request<UserResponse[]>("/auth/users/pending/"),
  getAllUsers: () => request<UserResponse[]>("/auth/users/all/"),
  createUser: (data: { username: string; email?: string; password: string; display_name?: string; department?: string; role: string; sales_role?: string; approved: boolean; is_active: boolean }) =>
    request<UserResponse>('/auth/users/', undefined, { method: 'POST', body: JSON.stringify(data) }),
  updateUser: (id: number, data: { display_name?: string | null; email?: string | null; department?: string | null; role?: string; sales_role?: string | null }) =>
    request<UserResponse>(`/auth/users/${id}/`, undefined, { method: 'PUT', body: JSON.stringify(data) }),
  resetUserPassword: (id: number, new_password: string) =>
    request<{ message: string }>(`/auth/users/${id}/reset-password/`, undefined, { method: 'POST', body: JSON.stringify({ new_password }) }),
  deactivateUser: (id: number) => request<UserResponse>(`/auth/users/${id}/deactivate/`, undefined, { method: 'POST' }),
  activateUser: (id: number) => request<UserResponse>(`/auth/users/${id}/activate/`, undefined, { method: 'POST' }),
  deleteUser: (id: number) => request<{ message: string }>(`/auth/users/${id}/`, undefined, { method: 'DELETE' }),

  // ── Customer Endpoints ───────────────────────────────────────────────
  listCustomers: () => request<Customer[]>('/customers/'),
  getCustomer: (name: string) => request<Customer>(`/customers/${encodeURIComponent(name)}/`),
  createCustomer: (data: { name: string; description?: string; vertical?: string }) =>
    request<Customer>('/customers/', undefined, {
      method: 'POST',
      body: JSON.stringify(data),
    }),
  updateCustomer: (name: string, data: { description?: string; vertical?: string }) =>
    request<Customer>(`/customers/${encodeURIComponent(name)}/`, undefined, { method: 'PUT', body: JSON.stringify(data) }),
  // customer alias tags (owner/admin write; any reader lists)
  listAliases: (customerName: string) =>
    request<CustomerAlias[]>(`/customers/${encodeURIComponent(customerName)}/aliases/`),
  addAlias: (customerName: string, alias: string) =>
    request<CustomerAlias>(`/customers/${encodeURIComponent(customerName)}/aliases/`, undefined, { method: 'POST', body: JSON.stringify({ alias }) }),
  removeAlias: (customerName: string, aliasId: number) =>
    request<void>(`/customers/${encodeURIComponent(customerName)}/aliases/${aliasId}/`, undefined, { method: 'DELETE' }),
  // The canonical vertical list + seed departments per vertical
  listVerticals: () => request<VerticalsResponse>('/customers/verticals/'),
  // Bootstrap a vertical-aware template assessment for a customer
  startTemplateAssessment: (customerName: string, templateId: string) =>
    request<BootstrapResult>(
      `/customers/${encodeURIComponent(customerName)}/assessments/from-template/`,
      undefined,
      { method: 'POST', body: JSON.stringify({ template_id: templateId }) },
    ),
  deleteCustomer: (name: string) =>
    request<void>(`/customers/${encodeURIComponent(name)}/`, undefined, { method: 'DELETE' }),
  getCustomerUseCases: (name: string) => request<UseCase[]>(`/customers/${encodeURIComponent(name)}/use-cases/`),
  // Assessment rounds (one active per customer)
  listAssessments: (name: string) => request<CustomerAssessment[]>(`/customers/${encodeURIComponent(name)}/assessments/`),
  // The route requires an AssessmentNameIn JSON body (name as a query param 422s)
  // optional `type` (server default 'ai') + `purpose` —
  // omitted keys keep the body byte-identical for existing callers.
  createAssessment: (name: string, assessmentName: string, opts?: { type?: AssessmentType; purpose?: string }) => request<CustomerAssessment>(`/customers/${encodeURIComponent(name)}/assessments/`, undefined, { method: "POST", body: JSON.stringify({ name: assessmentName, ...(opts?.type ? { type: opts.type } : {}), ...(opts?.purpose ? { purpose: opts.purpose } : {}) }) }),
  archiveAssessment: (name: string, assessmentId: number) => request<CustomerAssessment>(`/customers/${encodeURIComponent(name)}/assessments/${assessmentId}/archive/`, undefined, { method: "POST" }),
  // Model-generated predictions (persisted)
  savedPredictions: (customer_id?: number | null) => request<AIPrediction[]>(`/analytics/predictions/`, customer_id != null ? { customer_id: String(customer_id) } : undefined),
  // F4: `signal` — the caller's AbortController (300s cap / cancel).
  generatePrediction: (use_case_id: number, days: number, signal?: AbortSignal) => request<AIPrediction>(`/analytics/predictions/generate/`, { use_case_id: String(use_case_id), days: String(days) }, { method: "POST", signal }),
  deletePrediction: (id: number) => request<{ message: string }>(`/analytics/predictions/${id}/`, undefined, { method: "DELETE" }),

  // ── Customer Aggregate Stats ─────────────────────────────────────────
  // /customers/stats/ returns the AGGREGATE shape (GlobalStats) — the
  // per-customer shape (CustomerStats) is /customers/{name}/stats/
  getCustomersStats: (my_view?: boolean) =>
    request<GlobalStats>(
      "/customers/stats/",
      my_view !== undefined ? { my_view: String(my_view) } : undefined,
    ),

  // Account impact — the single money source for the global surfaces
  // (read-only; value null = "Not quantified").
  getPortfolioAccountImpact: (my_view?: boolean) =>
    request<PortfolioAccountImpact>(
      "/account-impact/portfolio/",
      my_view !== undefined ? { my_view: String(my_view) } : undefined,
    ),

  // ── Department Endpoints ─────────────────────────────────────────────
  listDepartments: (customer_name?: string) =>
    request<Department[]>('/departments/', customer_name ? { customer_name } : undefined),
  createDepartment: (data: { name: string; customer_name: string }) =>
    request<Department>('/departments/', undefined, {
      method: 'POST',
      body: JSON.stringify(data),
    }),
  updateDepartment: (id: number, data: { name: string }) =>
    request<Department>(`/departments/${id}/`, undefined, {
      method: 'PUT',
      body: JSON.stringify(data),
    }),
  deleteDepartment: (id: number) => request<void>(`/departments/${id}/`, undefined, { method: 'DELETE' }),

  // ── Customer Sharing ────────────────────────────────────────────────
  // The route returns a {"users": [...]} envelope — unwrap to the plain array
  listCustomerUsers: (customer_name: string) =>
    request<CustomerUserResponse>(`/customers/${encodeURIComponent(customer_name)}/users/`).then((r) => r.users),
  addUserToCustomer: (customer_name: string, user_id: number, role: string) =>
    request<any>(`/customers/${encodeURIComponent(customer_name)}/users/`, { user_id: String(user_id), role }, { method: 'POST' }),
  removeUserFromCustomer: (customer_name: string, user_id: number) =>
    request<any>(`/customers/${encodeURIComponent(customer_name)}/users/${user_id}/`, undefined, { method: 'DELETE' }),
  updateUserRole: (customer_name: string, user_id: number, role: string) =>
    request<any>(`/customers/${encodeURIComponent(customer_name)}/users/${user_id}/`, { role }, { method: 'PUT' }),
  checkAccess: (customer_name: string) =>
    request<AccessCheckResponse>(`/customers/${encodeURIComponent(customer_name)}/access/`),
  getCustomerSalesTeam: (customer_name: string) =>
    request<CustomerSalesTeam>(`/customers/${encodeURIComponent(customer_name)}/sales-team/`),
  updateCustomerSalesTeam: (customer_name: string, payload: CustomerSalesTeamUpdate) =>
    request<CustomerSalesTeam>(`/customers/${encodeURIComponent(customer_name)}/sales-team/`, undefined, {
      method: 'PUT',
      body: JSON.stringify(payload),
    }),
  // ── Account memberships + ownership review queue (RBAC model) ──
  getOwnershipReview: () =>
    request<{ items: OwnershipReviewItem[] }>('/admin/ownership-review/'),
  resolveOwnershipReview: (customer_id: number, user_id: number) =>
    request<Record<string, unknown>>(`/admin/ownership-review/${customer_id}/`, undefined, {
      method: 'POST',
      body: JSON.stringify({ user_id }),
    }),
  getCustomerMemberships: (customer_name: string) =>
    request<{ customer_id: number; members: AccountMembership[] }>(
      `/customers/${encodeURIComponent(customer_name)}/memberships/`),
  getMyCustomers: () => request<MyCustomerAccess[]>('/customers/me/customers/'),

  // ── Projections ───────────────────────────────────────────────
  // F4: `signal` — the caller's AbortController (300s cap / cancel).
  generateProjection: (customer_name: string, horizon?: string, signal?: AbortSignal) =>
    request<Projection>(`/customers/${encodeURIComponent(customer_name)}/projections/${horizon ? `?horizon=${encodeURIComponent(horizon)}` : ''}`, undefined, { method: "POST", signal }),
  getProjection: (customer_name: string) =>
    request<Projection>(`/customers/${encodeURIComponent(customer_name)}/projections/`),
  clearProjection: (customer_name: string) =>
    request<{ message: string }>(`/customers/${encodeURIComponent(customer_name)}/projections/`, undefined, { method: 'DELETE' }),

  // ── Global Admin ────────────────────────────────────────────────
  getGlobalAdminStats: () => request<GlobalAdminStats>('/global-admin/stats'),
  getInferenceConfig: () => request<InferenceConfigResponseWithSsl>('/admin/config/inference'),
  updateInferenceConfig: (payload: Partial<InferenceConfigResponseWithSsl>) => request<InferenceConfigResponseWithSsl>('/admin/config/inference', undefined, { method: 'PUT', body: JSON.stringify(payload) }),
  getDoclingConfig: () => request<DoclingConfigResponse>('/admin/config/docling'),
  updateDoclingConfig: (payload: Partial<DoclingConfigResponse>) => request<DoclingConfigResponse>('/admin/config/docling', undefined, { method: 'PUT', body: JSON.stringify(payload) }),
  getDocumentProcessingConfig: () => request<DocumentProcessingConfig>('/admin/config/documents'),
  updateDocumentProcessingConfig: (payload: Partial<DocumentProcessingConfig>) => request<DocumentProcessingConfig>('/admin/config/documents', undefined, { method: 'PUT', body: JSON.stringify(payload) }),
  getLdapSettings: () => request<LdapSettingsResponse>('/admin/config/auth_ldap'),
  updateLdapSettings: (payload: Partial<LdapSettingsResponse>) => request<LdapSettingsResponse>('/admin/config/auth_ldap', undefined, { method: 'PUT', body: JSON.stringify(payload) }),
  testLdapConnection: () => request<LdapTestResponse>('/admin/config/auth_ldap/test', undefined, { method: 'POST', body: JSON.stringify({}) }),
  getEmailConfig: () => request<EmailConfigResponse>('/admin/config/email'),
  updateEmailConfig: (payload: Partial<EmailConfigResponse>) => request<EmailConfigResponse>('/admin/config/email', undefined, { method: 'PUT', body: JSON.stringify(payload) }),
  testEmailConnection: () => request<EmailTestResponse>('/admin/config/email/test', undefined, { method: 'POST', body: JSON.stringify({}) }),
  getAuthPublicSettings: () => request<AuthPublicSettingsResponse>('/auth/settings/public/'),
  getIntegrationConfig: () =>
    request<{ slack?: Record<string, any>; teams?: Record<string, any>; jira?: Record<string, any> }>('/admin/config/integration'),
  updateIntegrationConfig: (platform: string, data: Record<string, any>) =>
    request<{ slack?: Record<string, any>; teams?: Record<string, any>; jira?: Record<string, any> }>(`/admin/config/integration/${platform}`, undefined, { method: 'PUT', body: JSON.stringify(data) }),
  deleteConfigEntry: (category: string, key: string) =>
    request<void>(`/admin/config/category/${category}/${encodeURIComponent(key)}`, undefined, { method: 'DELETE' }),
  appHealth: async () => {
    const token = getAuthToken();
    const res = await fetch("/health", {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    });
    if (!res.ok) throw new Error(`Backend health ${res.status}`);
    return res.json();
  },

  // ── Customer Knowledge (Phase 2 + Docling normalization) ──
  listCustomerKnowledge: (customerId?: number) => request<any[]>(
    '/customer-knowledge/',
    customerId !== undefined ? { customer_id: String(customerId) } : undefined,
  ),
  getCustomerKnowledge: (id: number) => request<any>(`/customer-knowledge/${id}`),
  deleteCustomerKnowledge: (id: number) =>
    request<void>(`/customer-knowledge/${id}`, undefined, { method: 'DELETE' }),
  getKnowledgeContent: (id: number) =>
    request<KnowledgeContentResponse>(`/customer-knowledge/${id}/content`),
  reprocessKnowledge: (id: number) =>
    request<any>(`/customer-knowledge/${id}/reprocess`, undefined, { method: 'POST' }),
  /** Retry LLM analysis only (item 16): Docling is NOT rerun. */
  retryKnowledgeEnrichment: (id: number) =>
    request<any>(`/customer-knowledge/${id}/enrich`, undefined, { method: 'POST' }),
  /** LLM-extracted intelligence items for one document (items 6, 13). */
  listKnowledgeItems: (id: number) =>
    request<KnowledgeEnrichmentItem[]>(`/customer-knowledge/${id}/items`),
  /** Original-document download URL (auth-gated; opens in a new tab). */
  knowledgeDownloadUrl: (id: number) =>
    `${API_BASE}/customer-knowledge/${id}/download`,
  uploadCustomerKnowledge: (file: File, customerId?: number, knowledgeCategory?: string) => {
    const token = getAuthToken();
    const formData = new FormData();
    formData.append('file', file);
    if (customerId !== undefined) formData.append('customer_id', String(customerId));
    if (knowledgeCategory) formData.append('knowledge_category', knowledgeCategory);
    const headers: Record<string, string> = {};
    if (token) headers['Authorization'] = `Bearer ${token}`;
    return fetch(`${API_BASE}/customer-knowledge/`, {
      method: 'POST',
      headers,
      body: formData,
    }).then(res => {
      if (!res.ok) throw new Error(`Upload failed: ${res.statusText}`);
      return res.json();
    });
  },

  // ── Intelligence Import (Global Intelligence) ─────────────────────
  uploadRedHatOpportunityImport: (file: File) => {
    const body = new FormData();
    body.append('file', file);
    return request<RedHatOpportunityImportResult>('/redhat-opportunity-import/', undefined, { method: 'POST', body });
  },
  listRedHatOpportunityImports: () => request<RedHatOpportunityImportSummary[]>('/redhat-opportunity-import/'),
  getRedHatOpportunityUnmatched: (id: number) =>
    request<RedHatOpportunityImportResult['skipped']>(`/redhat-opportunity-import/${id}/unmatched/`),
  getRedHatOpportunityReport: (customerId: number) =>
    request<RedHatOpportunityReport>(`/customers/${customerId}/redhat-opportunities/`),
  uploadIntelligenceImport: async (file: File): Promise<IntelligenceImportResult> => {
    const token = getAuthToken();
    const formData = new FormData();
    formData.append('file', file);
    const headers: Record<string, string> = {};
    if (token) headers.Authorization = `Bearer ${token}`;
    const response = await fetch(`${API_BASE}/intelligence-import/`, {
      method: 'POST', headers, body: formData,
    });
    if (response.status === 401) {
      if (window.location.pathname !== '/login' && beginSessionRedirect()) {
        saveSessionReturn();
        markSessionExpired();
        clearAuth();
        window.history.replaceState(null, '', '/login');
        window.dispatchEvent(new PopStateEvent('popstate'));
      }
      throw new SessionExpiredError();
    }
    if (!response.ok) {
      const body = await response.text().catch(() => '');
      let parsed: any;
      try { parsed = JSON.parse(body); } catch { parsed = { detail: body || response.statusText }; }
      const err: Error & { status?: number } = new Error(formatApiError(parsed, response.status));
      err.status = response.status;
      throw err;
    }
    return response.json() as Promise<IntelligenceImportResult>;
  },
  listIntelligenceImports: () =>
    request<IntelligenceImportSummary[]>('/intelligence-import/'),
  getIntelligenceImport: (id: number) =>
    request<IntelligenceImportDetail>(`/intelligence-import/${id}/`),
  deleteIntelligenceImport: (id: number) =>
    request<IntelligenceImportDeleteResult>(`/intelligence-import/${id}/`, undefined, { method: 'DELETE' }),
  getCustomerPipeline: (customerName: string, compareWith?: number) =>
    request<CustomerPipeline>(
      `/customers/${encodeURIComponent(customerName)}/pipeline/`
        + (compareWith != null ? `?compare_with=${encodeURIComponent(String(compareWith))}` : ''),
    ),

  // ── RVTools (VMware) Intelligence Import ──────────────────────────
  uploadRvToolsImport: async (file: File, target: RVToolsImportTarget): Promise<RVToolsImportDetail> => {
    const token = getAuthToken();
    const formData = new FormData();
    formData.append('file', file);
    formData.append('customer_name', target.customer_name);
    const headers: Record<string, string> = {};
    if (token) headers.Authorization = `Bearer ${token}`;
    const response = await fetch(`${API_BASE}/rvtools-import/`, {
      method: 'POST', headers, body: formData,
    });
    if (response.status === 401) {
      if (window.location.pathname !== '/login' && beginSessionRedirect()) {
        saveSessionReturn();
        markSessionExpired();
        clearAuth();
        window.history.replaceState(null, '', '/login');
        window.dispatchEvent(new PopStateEvent('popstate'));
      }
      throw new SessionExpiredError();
    }
    if (!response.ok) {
      const body = await response.text().catch(() => '');
      let parsed: any;
      try { parsed = JSON.parse(body); } catch { parsed = { detail: body || response.statusText }; }
      const err: Error & { status?: number } = new Error(formatApiError(parsed, response.status));
      err.status = response.status;
      throw err;
    }
    return response.json() as Promise<RVToolsImportDetail>;
  },
  listRvToolsImports: () =>
    request<RVToolsImportSummary[]>('/rvtools-import/'),
  getRvToolsImport: (id: number, vmLimit?: number, vmOffset?: number) => {
    const q: Record<string, string> = {};
    if (vmLimit !== undefined) q.vm_limit = String(vmLimit);
    if (vmOffset !== undefined) q.vm_offset = String(vmOffset);
    return request<RVToolsImportDetail>(`/rvtools-import/${id}/`, q);
  },
  deleteRvToolsImport: (id: number) =>
    request<RVToolsImportDeleteResult>(`/rvtools-import/${id}/`, undefined, { method: 'DELETE' }),
  getCustomerRvTools: (customerName: string) =>
    request<CustomerRvTools>(`/customers/${encodeURIComponent(customerName)}/rvtools/`),

  // ── Rep Intelligence Import (generic account-intelligence CSV) ────
  uploadRepIntelligenceImport: async (file: File): Promise<RepIntelligenceResult> => {
    const token = getAuthToken();
    const formData = new FormData();
    formData.append('file', file);
    const headers: Record<string, string> = {};
    if (token) headers.Authorization = `Bearer ${token}`;
    const response = await fetch(`${API_BASE}/rep-intelligence/`, {
      method: 'POST', headers, body: formData,
    });
    if (response.status === 401) {
      if (window.location.pathname !== '/login' && beginSessionRedirect()) {
        saveSessionReturn();
        markSessionExpired();
        clearAuth();
        window.history.replaceState(null, '', '/login');
        window.dispatchEvent(new PopStateEvent('popstate'));
      }
      throw new SessionExpiredError();
    }
    if (!response.ok) {
      const body = await response.text().catch(() => '');
      let parsed: any;
      try { parsed = JSON.parse(body); } catch { parsed = { detail: body || response.statusText }; }
      const err: Error & { status?: number } = new Error(formatApiError(parsed, response.status));
      err.status = response.status;
      throw err;
    }
    return response.json() as Promise<RepIntelligenceResult>;
  },
  listRepIntelligenceImports: () =>
    request<RepIntelligenceSummary[]>('/rep-intelligence/'),
  getRepIntelligenceImport: (id: number) =>
    request<RepIntelligenceDetail>(`/rep-intelligence/${id}/`),
  deleteRepIntelligenceImport: (id: number) =>
    request<RepIntelligenceDeleteResult>(`/rep-intelligence/${id}/`, undefined, { method: 'DELETE' }),
  downloadRepIntelligenceTemplate: async (): Promise<Blob> => {
    const token = getAuthToken();
    const response = await fetch(`${API_BASE}/rep-intelligence/template/`, {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    });
    return fetchBlobOrThrow(response);
  },
  downloadRepIntelligenceSource: async (id: number): Promise<Blob> => {
    const token = getAuthToken();
    const response = await fetch(`${API_BASE}/rep-intelligence/${id}/source/`, {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    });
    return fetchBlobOrThrow(response);
  },
  downloadRepIntelligenceIssues: async (id: number): Promise<Blob> => {
    const token = getAuthToken();
    const response = await fetch(`${API_BASE}/rep-intelligence/${id}/issues.csv/`, {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    });
    return fetchBlobOrThrow(response);
  },

  // ── NetSuite Intelligence Import (distributor subscription billing) ──
  // Manager-gated on the backend (system admins + sales managers); a 403
  // rides on the thrown Error's `status` so the pane renders its denied state.
  uploadNetSuiteImport: async (file: File): Promise<NetSuiteImportDetail> => {
    const token = getAuthToken();
    const formData = new FormData();
    formData.append('file', file);
    const headers: Record<string, string> = {};
    if (token) headers.Authorization = `Bearer ${token}`;
    const response = await fetch(`${API_BASE}/netsuite-import/`, {
      method: 'POST', headers, body: formData,
    });
    if (response.status === 401) {
      if (window.location.pathname !== '/login' && beginSessionRedirect()) {
        saveSessionReturn();
        markSessionExpired();
        clearAuth();
        window.history.replaceState(null, '', '/login');
        window.dispatchEvent(new PopStateEvent('popstate'));
      }
      throw new SessionExpiredError();
    }
    if (!response.ok) {
      const body = await response.text().catch(() => '');
      let parsed: any;
      try { parsed = JSON.parse(body); } catch { parsed = { detail: body || response.statusText }; }
      const err: Error & { status?: number } = new Error(formatApiError(parsed, response.status));
      err.status = response.status;
      throw err;
    }
    return response.json() as Promise<NetSuiteImportDetail>;
  },
  listNetSuiteImports: () =>
    request<NetSuiteImportSummary[]>('/netsuite-import/'),
  getNetSuiteImport: (id: number) =>
    request<NetSuiteImportDetail>(`/netsuite-import/${id}/`),
  getNetSuiteImportUnmatched: (id: number) =>
    request<NetSuiteImportRow[]>(`/netsuite-import/${id}/unmatched/`),
  rematchNetSuiteImport: (id: number) =>
    request<NetSuiteImportDetail>(`/netsuite-import/${id}/rematch/`, undefined, { method: 'POST' }),

  // ── Sales Evaluations (Phase 3) ─────────────────────────────────
  listSalesEvaluations: (customerId: number) => request<any[]>(`/sales-evaluations/`, { customer_id: String(customerId) }),
  createSalesEvaluation: (customerId: number, evaluationName: string) => request<any>(`/sales-evaluations/`, { customer_id: String(customerId) }, {
    method: "POST",
    body: JSON.stringify({ evaluation_name: evaluationName }),
  }),
  getSalesEvaluation: (id: number) => request<any>(`/sales-evaluations/${id}/`),
  updateSalesEvaluation: (id: number, data: { evaluation_name?: string; status?: string }) => request<any>(`/sales-evaluations/${id}/`, undefined, {
    method: "PUT",
    body: JSON.stringify(data),
  }),
  deleteSalesEvaluation: (id: number) => request<void>(`/sales-evaluations/${id}/`, undefined, { method: "DELETE" }),

  // ── Sales Readiness (Phase 3) ─────────────────────────────────
  getSalesUseCases: (customerId: number) =>
    request<UseCase[]>(`/sales/customers/${customerId}/usecases`),
  getSalesKnowledge: (customerId: number) =>
    request<any[]>(`/sales/customers/${customerId}/knowledge`),
  getSalesReadiness: (customerId: number) =>
    request<Record<string, unknown>>(`/sales/customers/${customerId}/readiness`),

  // ── Technology Inventory ─────────────────────────────────
  listCustomerTechnology: (customerId: number, params?: { category?: string; vendor?: string; verification_state?: string; search?: string; sort?: string }) => {
    const strParams: Record<string, string> = {};
    for (const [k, v] of Object.entries(params ?? {})) {
      if (v !== undefined && v !== null && v !== "") strParams[k] = String(v);
    }
    return request<CustomerTechnology[]>(`/customers/${customerId}/technology/`, strParams);
  },
  getTechnology: (id: number) => request<CustomerTechnology>(`/technology/${id}/`),
  createTechnology: (customerId: number, data: CustomerTechnologyCreate) =>
    request<CustomerTechnology>(`/customers/${customerId}/technology/`, undefined, { method: "POST", body: JSON.stringify(data) }),
  updateTechnology: (id: number, data: Partial<CustomerTechnologyCreate>) =>
    request<CustomerTechnology>(`/technology/${id}/`, undefined, { method: "PUT", body: JSON.stringify(data) }),
  deleteTechnology: (id: number) => request<void>(`/technology/${id}/`, undefined, { method: "DELETE" }),

  // ── Sales Notes ──────────────────────────────────────────
  listCustomerSalesNotes: (customerId: number, params?: { category?: string; author?: string; search?: string; sort?: string }) => {
    const strParams: Record<string, string> = {};
    for (const [k, v] of Object.entries(params ?? {})) {
      if (v !== undefined && v !== null && v !== "") strParams[k] = String(v);
    }
    return request<SalesNote[]>(`/customers/${customerId}/sales-notes/`, strParams);
  },
  getSalesNote: (id: number) => request<SalesNote>(`/sales-notes/${id}/`),
  createSalesNote: (customerId: number, data: SalesNoteCreate) =>
    request<SalesNote>(`/customers/${customerId}/sales-notes/`, undefined, { method: "POST", body: JSON.stringify(data) }),
  updateSalesNote: (id: number, data: Partial<SalesNoteCreate>) =>
    request<SalesNote>(`/sales-notes/${id}/`, undefined, { method: "PUT", body: JSON.stringify(data) }),
  deleteSalesNote: (id: number) => request<void>(`/sales-notes/${id}/`, undefined, { method: "DELETE" }),

  // ── Contacts + buying coverage (H4) ────────────────────────────────
  listCustomerContacts: (customerId: number, params?: { includeArchived?: boolean; search?: string }) => {
    const strParams: Record<string, string> = {};
    if (params?.includeArchived) strParams.include_archived = "true";
    if (params?.search) strParams.search = params.search;
    return request<CustomerContact[]>(`/customers/${customerId}/contacts/`, strParams);
  },
  getContact: (id: number) => request<CustomerContact>(`/contacts/${id}/`),
  createContact: (customerId: number, data: ContactCreate) =>
    request<CustomerContact>(`/customers/${customerId}/contacts/`, undefined, { method: "POST", body: JSON.stringify(data) }),
  updateContact: (id: number, data: ContactUpdate) =>
    request<CustomerContact>(`/contacts/${id}/`, undefined, { method: "PUT", body: JSON.stringify(data) }),
  deleteContact: (id: number) => request<void>(`/contacts/${id}/`, undefined, { method: "DELETE" }),
  getContactCoverage: (customerId: number) =>
    request<ContactCoverage>(`/customers/${customerId}/contacts/coverage/`),

  // ── Activities + tasks (H5) ─────────────────────────────────────────
  getWorkspaceActions: (customerId: number) => request<{ customer_id: number; capabilities: Record<string, boolean>; assignees: { id?: number; username: string; display_name: string }[] }>(`/customers/${customerId}/workspace-actions/`),
  listActivities: (customerId: number) => request<Activity[]>(`/customers/${customerId}/activities/`),
  createActivity: (customerId: number, data: ActivityCreate) =>
    request<Activity>(`/customers/${customerId}/activities/`, undefined, { method: "POST", body: JSON.stringify(data) }),
  getActivity: (id: number) => request<Activity>(`/activities/${id}/`),
  updateActivity: (id: number, data: ActivityUpdate) =>
    request<Activity>(`/activities/${id}/`, undefined, { method: "PUT", body: JSON.stringify(data) }),
  deleteActivity: (id: number) => request<void>(`/activities/${id}/`, undefined, { method: "DELETE" }),
  listTasks: (customerId: number, params?: { status?: string; mine?: boolean }) => {
    const strParams: Record<string, string> = {};
    if (params?.status) strParams.status = params.status;
    if (params?.mine) strParams.mine = "true";
    return request<Task[]>(`/customers/${customerId}/tasks/`, strParams);
  },
  createTask: (customerId: number, data: TaskCreate) =>
    request<Task>(`/customers/${customerId}/tasks/`, undefined, { method: "POST", body: JSON.stringify(data) }),
  promoteTask: (customerId: number, data: TaskPromote) =>
    request<TaskPromotionResponse>(`/customers/${customerId}/tasks/promote/`, undefined, { method: "POST", body: JSON.stringify(data) }),
  updateTask: (id: number, data: TaskUpdate) =>
    request<Task>(`/tasks/${id}/`, undefined, { method: "PUT", body: JSON.stringify(data) }),
  // DELETE carries expected_version as a JSON BODY field.
  deleteTask: (id: number, expectedVersion: number) =>
    request<void>(`/tasks/${id}/`, undefined, { method: "DELETE", body: JSON.stringify({ expected_version: expectedVersion }) }),
  myTasks: () => request<MyTask[]>(`/tasks/mine/`),

  // ── H6 account brief (preview JSON + Markdown/PDF downloads) ───────
  getAccountBrief: (customerId: number) => request<AccountBrief>(`/customers/${customerId}/brief/`),
  downloadAccountBriefMd: (customerId: number, signal?: AbortSignal) => {
    const token = getAuthToken();
    return mapAbortError(fetch(`${API_BASE}/customers/${customerId}/brief/download/`, { headers: token ? { Authorization: `Bearer ${token}` } : undefined, signal }).then(fetchBlobOrThrow));
  },
  downloadAccountBriefPdf: (customerId: number, signal?: AbortSignal) => {
    const token = getAuthToken();
    return mapAbortError(fetch(`${API_BASE}/customers/${customerId}/brief/pdf/`, { headers: token ? { Authorization: `Bearer ${token}` } : undefined, signal }).then(fetchBlobOrThrow));
  },

  // ── account timeline + QBR cadence ─────────────────────────
  getAccountTimeline: (customerId: number, limit?: number, cursor?: string) => {
    const params = new URLSearchParams();
    if (limit !== undefined) {
      params.set("limit", String(limit));
    }
    if (cursor) {
      params.set("cursor", cursor);
    }
    const qs = params.toString();
    return request<AccountTimelineResponse>(`/customers/${customerId}/timeline/${qs ? `?${qs}` : ""}`);
  },

  // ── in-account cross-module search ─────────────────────────────
  searchAccount: (customerId: number, query: string, includeArchived = false) =>
    request<AccountSearchResponse>(
      `/customers/${customerId}/search/?q=${encodeURIComponent(query)}&include_archived=${includeArchived}`
    ),

  // ── saved views + personal worklist ────────────────────────────
  listSavedViews: (surface: string, customerId?: number) =>
    request<SavedViewsResponse>(`/saved-views/?surface=${encodeURIComponent(surface)}${customerId ? `&customer_id=${customerId}` : ''}`),
  saveView: (surface: string, name: string, params: Record<string, string | null>) =>
    request<SaveViewResponse>(`/saved-views/`, undefined, {
      method: "POST",
      body: JSON.stringify({ surface, name, params }),
    }),
  deleteSavedView: (id: number) =>
    request<void>(`/saved-views/${id}/`, undefined, { method: "DELETE" }),
  myWorklist: () => request<WorklistResponse>(`/worklist/mine/`),

  // ── deals + pipeline stages ────────────────────────────────────
  listPipelineStages: (includeInactive = false) =>
    request<PipelineStage[]>(`/pipeline-stages/?include_inactive=${includeInactive}`),
  createPipelineStage: (data: { key: string; label: string; stage_class: string; position: number; default_probability?: number | null }) =>
    request<PipelineStage>(`/admin/pipeline-stages/`, undefined, { method: "POST", body: JSON.stringify(data) }),
  updatePipelineStage: (id: number, data: { label?: string; position?: number; active?: boolean; default_probability?: number | null; remap_to_stage_id?: number }) =>
    request<PipelineStage>(`/admin/pipeline-stages/${id}/`, undefined, { method: "PUT", body: JSON.stringify(data) }),
  getDeal: (id: number) => request<Deal>(`/deals/${id}/`),
  getTask: (id: number) => request<Task>(`/tasks/${id}/`),
  promoteDeal: (customerId: number, data: { attention_id?: string; vendor?: { import_id: number; opportunity_number: string } }) => request<{ created: boolean; deal: Deal }>(`/customers/${customerId}/deals/promote/`, undefined, { method: 'POST', body: JSON.stringify(data) }),
  listDeals: (customerId: number) => request<Deal[]>(`/customers/${customerId}/deals/`),
  createDeal: (customerId: number, data: DealInput) =>
    request<Deal>(`/customers/${customerId}/deals/`, undefined, { method: "POST", body: JSON.stringify(data) }),
  updateDeal: (id: number, data: DealInput & { expected_version: number }) =>
    request<Deal>(`/deals/${id}/`, undefined, { method: "PUT", body: JSON.stringify(data) }),
  deleteDeal: (id: number, expectedVersion: number) =>
    request<void>(`/deals/${id}/`, undefined, { method: "DELETE", body: JSON.stringify({ expected_version: expectedVersion }) }),
  dealHistory: (id: number) => request<DealHistoryEntry[]>(`/deals/${id}/history/`),

  // ── manager team rollup (active sales managers only; 403 otherwise) ──
  teamRollup: () => request<TeamRollupResponse>(`/rollups/team/`),

  // ── account health components (never a composite score) ────────
  getCustomerHealth: (customerId: number) =>
    request<AccountHealthResponse>(`/customers/${customerId}/health/`),

  // ── Third-Party Professional Services ───────────────────
  listCustomerThirdPartyServices: (customerId: number, params?: { status?: string; category?: string; search?: string; sort?: string; direction?: string }) => {
    const strParams: Record<string, string> = {};
    for (const [k, v] of Object.entries(params ?? {})) {
      if (v !== undefined && v !== null && v !== "") strParams[k] = String(v);
    }
    return request<ThirdPartyService[]>(`/customers/${customerId}/third-party-services/`, strParams);
  },
  getThirdPartyService: (id: number) => request<ThirdPartyService>(`/third-party-services/${id}/`),
  createThirdPartyService: (customerId: number, data: ThirdPartyServiceCreate) =>
    request<ThirdPartyService>(`/customers/${customerId}/third-party-services/`, undefined, { method: "POST", body: JSON.stringify(data) }),
  updateThirdPartyService: (id: number, data: ThirdPartyServiceUpdate) =>
    request<ThirdPartyService>(`/third-party-services/${id}/`, undefined, { method: "PUT", body: JSON.stringify(data) }),
  deleteThirdPartyService: (id: number) => request<void>(`/third-party-services/${id}/`, undefined, { method: "DELETE" }),
  listThirdPartyServiceDocuments: (serviceId: number) =>
    request<ThirdPartyServiceDocument[]>(`/third-party-services/${serviceId}/documents/`),
  uploadThirdPartyServiceDocument: async (serviceId: number, file: File, documentType: string, title?: string) => {
    const token = getAuthToken();
    const formData = new FormData();
    formData.append('file', file);
    formData.append('document_type', documentType);
    if (title?.trim()) formData.append('title', title.trim());
    const headers: Record<string, string> = {};
    if (token) headers.Authorization = `Bearer ${token}`;
    const response = await fetch(`${API_BASE}/third-party-services/${serviceId}/documents/`, {
      method: 'POST', headers, body: formData,
    });
    if (!response.ok) {
      const body = await response.text().catch(() => '');
      let parsed: any;
      try { parsed = JSON.parse(body); } catch { parsed = { detail: body || response.statusText }; }
      throw new Error(formatApiError(parsed, response.status));
    }
    return response.json() as Promise<ThirdPartyServiceDocument>;
  },
  downloadThirdPartyServiceDocument: async (documentId: number) => {
    const token = getAuthToken();
    const response = await fetch(`${API_BASE}/third-party-services/${documentId}/download/`, {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    });
    return fetchBlobOrThrow(response);
  },
  deleteThirdPartyServiceDocument: (serviceId: number, documentId: number) =>
    request<void>(`/third-party-services/${serviceId}/documents/${documentId}/`, undefined, { method: "DELETE" }),
  listAllThirdPartyServices: (params?: { status?: string; category?: string; search?: string }) => {
    const strParams: Record<string, string> = {};
    for (const [k, v] of Object.entries(params ?? {})) {
      if (v !== undefined && v !== null && v !== "") strParams[k] = String(v);
    }
    return request<ThirdPartyService[]>('/admin/third-party-services/', strParams);
  },

  // ── Customer Intelligence Overview ──────────────────────
  getCustomerIntelligenceOverview: (customerId: number) =>
    request<CustomerIntelligenceOverview>(`/customers/${customerId}/intelligence/overview/`),

  // Account workspace context: deterministic summaries +
  // typed, evidence-backed Opportunities & Attention.
  getAccountWorkspace: (customerId: number) =>
    request<AccountWorkspace>(`/customers/${customerId}/intelligence/workspace/`),

  // Customer Intelligence graph projection (F3): the nodes/links view model
  // for the Customer Intelligence Constellation. Deterministic backend
  // projection of the authorized customer's records (canonical, deduplicated,
  // provenance + epistemic class on every link); the frontend owns layout.
  getCustomerIntelligenceGraph: (customerId: number) =>
    request<CustomerIntelligenceGraph>(`/customers/${customerId}/intelligence/graph/`),

  // ── Sales Personas + Evaluation Preview ─────────────────
  listSalesPersonas: () => request<SalesPersona[]>(`/sales-evaluations/personas/`),
  previewSalesEvaluation: (customerId: number, persona?: string | null) =>
    request<SalesEvaluationPreview>(`/sales-evaluations/preview/`, undefined, {
      method: "POST",
      body: JSON.stringify({ customer_id: customerId, persona: persona ?? null }),
    }),
  // Extended create: optional persona selects the audience context.
  createSalesEvaluationWithPersona: (customerId: number, evaluationName: string, persona?: string | null) =>
    request<any>(`/sales-evaluations/`, { customer_id: String(customerId) }, {
      method: "POST",
      body: JSON.stringify({ evaluation_name: evaluationName, ...(persona ? { persona } : {}) }),
    }),

  // ── H7 account strategy (plan + suggestions + immutable snapshots) ──
  getAccountStrategy: (customerId: number) =>
    request<StrategyView>(`/customers/${customerId}/strategy/`),
  updateAccountStrategy: (customerId: number, data: StrategyUpdate) =>
    request<StrategyPlan>(`/customers/${customerId}/strategy/`, undefined, { method: "PUT", body: JSON.stringify(data) }),
  updateStrategyLinks: (customerId: number, data: StrategyLinksUpdate) =>
    request<StrategyLinks>(`/customers/${customerId}/strategy/links/`, undefined, { method: "PUT", body: JSON.stringify(data) }),
  publishStrategySnapshot: (customerId: number, data: StrategySnapshotPublish) =>
    request<StrategySnapshotSummary>(`/customers/${customerId}/strategy/snapshots/`, undefined, { method: "POST", body: JSON.stringify(data) }),
  listStrategySnapshots: (customerId: number) =>
    request<StrategySnapshotList>(`/customers/${customerId}/strategy/snapshots/`),
  getStrategySnapshot: (snapshotId: number) =>
    request<StrategySnapshot>(`/strategy-snapshots/${snapshotId}/`),
  restoreStrategySnapshot: (snapshotId: number, expectedVersion: number) =>
    request<StrategyPlan>(`/strategy-snapshots/${snapshotId}/restore/`, undefined, { method: "POST", body: JSON.stringify({ expected_version: expectedVersion }) }),
};
